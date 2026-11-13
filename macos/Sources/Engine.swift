import Darwin
import Foundation

/// Where the engine is, and how it is started.
enum Engine {
    /// Overrides the engine inside the app (for development).
    static let overrideVariable = "FLALAC_ENGINE"

    /// `<app>/Contents/Resources/engine/flalac-engine`, or `$FLALAC_ENGINE` when set.
    static func executableURL(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        resources: URL? = Bundle.main.resourceURL
    ) -> URL? {
        if let path = environment[overrideVariable], !path.isEmpty {
            return URL(fileURLWithPath: (path as NSString).expandingTildeInPath)
        }
        return resources?.appendingPathComponent("engine/flalac-engine")
    }

    /// The app's environment for the engine, with the API key (or without any inherited one).
    static func environment(
        key: String?,
        base: [String: String] = ProcessInfo.processInfo.environment
    ) -> [String: String] {
        var environment = base
        environment[EngineCommand.keyVariable] = nil
        if let key, !key.isEmpty {
            environment[EngineCommand.keyVariable] = key
        }
        // The engine is a Python program: line-by-line output, UTF-8 whatever the locale.
        environment["PYTHONUNBUFFERED"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        return environment
    }

    /// Starts the engine, or explains why it cannot be started.
    static func launch(_ arguments: [String], key: String?) throws -> EngineProcess {
        guard let url = executableURL() else {
            throw EngineLaunchError(message: "Flalac could not find its engine.")
        }
        let path = url.path
        var isFolder: ObjCBool = false
        guard FileManager.default.fileExists(atPath: path, isDirectory: &isFolder), !isFolder.boolValue else {
            throw EngineLaunchError(message: "The engine is missing: \(path) does not exist.")
        }
        guard FileManager.default.isExecutableFile(atPath: path) else {
            throw EngineLaunchError(message: "The engine at \(path) cannot be run.")
        }
        return try EngineProcess(executable: url, arguments: arguments, environment: environment(key: key))
    }

    /// Runs a short command (version, test-jellyfin) to the end and collects what it said.
    static func collect(_ arguments: [String], key: String? = nil, timeout: TimeInterval = 60) async -> CollectedRun {
        let process: EngineProcess
        do {
            process = try launch(arguments, key: key)
        } catch {
            return CollectedRun(launchError: error.localizedDescription)
        }
        let started = Date()
        let watchdog = Task {
            try await Task.sleep(nanoseconds: UInt64(timeout * 1_000_000_000))
            process.terminate(grace: 2)
        }
        var run = CollectedRun()
        for await event in process.events {
            switch event {
            case .message(let message): run.messages.append(message)
            case .output(let line): run.output.append(line)
            case .exited(let exit): run.exit = exit
            }
        }
        watchdog.cancel()
        // Stopped by the watchdog: a slow answer, not a crash
        run.timedOut = Date().timeIntervalSince(started) >= timeout
        return run
    }
}

struct EngineLaunchError: LocalizedError {
    var message: String
    var errorDescription: String? { message }
}

/// How the engine process ended.
struct EngineExit: Equatable, Sendable {
    /// The exit code, or the signal number when `signalled`.
    var status: Int32
    var signalled: Bool

    var succeeded: Bool { !signalled && status == 0 }

    /// For an engine that stopped without saying why.
    var explanation: String {
        if signalled {
            return "The engine stopped unexpectedly (signal \(status))."
        }
        return "The engine stopped unexpectedly (exit code \(status))."
    }
}

enum EngineEvent: Sendable {
    /// A JSON message from stdout.
    case message(EngineMessage)
    /// A line of free-form text: stderr, or stdout that is not a message.
    case output(String)
    /// The process ended and its output was read to the end. Always the last event.
    case exited(EngineExit)
}

struct CollectedRun: Sendable {
    var messages: [EngineMessage] = []
    var output: [String] = []
    var exit: EngineExit?
    var launchError: String?
    /// The command did not finish within its time limit and was stopped.
    var timedOut = false
}

/// One running engine process. Its stdout and stderr are read line by line as they arrive,
/// in the background, and delivered in order through `events`.
final class EngineProcess: @unchecked Sendable {
    let events: AsyncStream<EngineEvent>

    private enum Stream: Hashable {
        case stdout
        case stderr
    }

    private let continuation: AsyncStream<EngineEvent>.Continuation
    private let process = Process()
    private let stdoutPipe = Pipe()
    private let stderrPipe = Pipe()
    /// Everything below is only touched on this queue.
    private let queue = DispatchQueue(label: "com.davidepetris.flalac.engine")
    private var sources: [Stream: DispatchSourceRead] = [:]
    private var pending: [Stream: Data] = [:]
    private var buffer = [UInt8](repeating: 0, count: 64 * 1024)
    private var exit: EngineExit?
    private var finished = false
    private var stopping = false

    /// A line longer than this without a newline is passed on in pieces.
    private static let longestLine = 1 << 20
    /// How long to wait for the output to end after the process exited (a child it left
    /// behind may still hold the pipes open).
    private static let drainSeconds = 2.0

    init(executable: URL, arguments: [String], environment: [String: String]) throws {
        (events, continuation) = AsyncStream.makeStream(of: EngineEvent.self, bufferingPolicy: .unbounded)
        process.executableURL = executable
        process.arguments = arguments
        process.environment = environment
        process.standardInput = FileHandle.nullDevice
        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe
        process.terminationHandler = { [self] process in
            let exit = EngineExit(
                status: process.terminationStatus,
                signalled: process.terminationReason == .uncaughtSignal
            )
            queue.async { self.processExited(exit) }
        }
        do {
            try process.run()
        } catch {
            continuation.finish()
            throw EngineLaunchError(
                message: "The engine could not be started: \(error.localizedDescription)"
            )
        }
        queue.async { self.startReading() }
    }

    /// Asks the engine to stop (SIGTERM) and kills it (SIGKILL) if it is still running after
    /// `grace` seconds. `events` ends with `.exited` either way.
    func terminate(grace: TimeInterval = 10) {
        queue.async { [self] in
            guard exit == nil, !stopping else { return }
            stopping = true
            if process.isRunning {
                process.terminate()
            }
            queue.asyncAfter(deadline: .now() + grace) { [self] in
                if exit == nil, process.isRunning {
                    let pid = process.processIdentifier
                    // A sync runs in its own process group (engine.py calls setpgrp), with the
                    // ffmpeg conversions in it: kill them too, not only the engine. For other
                    // commands there is no such group and this does nothing.
                    kill(-pid, SIGKILL)
                    kill(pid, SIGKILL)
                }
            }
        }
    }

    private func startReading() {
        for (stream, pipe) in [(Stream.stdout, stdoutPipe), (Stream.stderr, stderrPipe)] {
            let descriptor = pipe.fileHandleForReading.fileDescriptor
            let source = DispatchSource.makeReadSource(fileDescriptor: descriptor, queue: queue)
            source.setEventHandler { [self] in
                read(descriptor, from: stream)
            }
            // The descriptor is closed only once the source no longer uses it.
            let handle = pipe.fileHandleForReading
            source.setCancelHandler {
                try? handle.close()
            }
            sources[stream] = source
            source.resume()
        }
    }

    private func read(_ descriptor: Int32, from stream: Stream) {
        let count = buffer.withUnsafeMutableBytes { bytes in
            Darwin.read(descriptor, bytes.baseAddress, bytes.count)
        }
        if count > 0 {
            consume(Data(buffer[0 ..< count]), from: stream)
        } else if count == 0 || (errno != EINTR && errno != EAGAIN) {
            close(stream)
            finishIfDone()
        }
    }

    private func consume(_ data: Data, from stream: Stream) {
        var text = pending[stream, default: Data()]
        text.append(data)
        while let newline = text.firstIndex(of: 0x0A) {
            emit(text[text.startIndex ..< newline], from: stream)
            text.removeSubrange(text.startIndex ... newline)
        }
        if text.count > Self.longestLine {
            emit(text, from: stream)
            text.removeAll()
        }
        pending[stream] = text
    }

    private func emit(_ bytes: Data, from stream: Stream) {
        var line = String(decoding: bytes, as: UTF8.self)
        if line.hasSuffix("\r") {
            line.removeLast()
        }
        switch stream {
        case .stdout:
            if let message = EngineMessage.decode(line) {
                continuation.yield(.message(message))
            } else if !line.trimmingCharacters(in: .whitespaces).isEmpty {
                continuation.yield(.output(line))
            }
        case .stderr:
            continuation.yield(.output(line))
        }
    }

    /// Stops reading a stream and passes on its last line if it had no newline.
    private func close(_ stream: Stream) {
        guard let source = sources.removeValue(forKey: stream) else { return }
        source.cancel()
        if let rest = pending.removeValue(forKey: stream), !rest.isEmpty {
            emit(rest, from: stream)
        }
    }

    private func processExited(_ exit: EngineExit) {
        self.exit = exit
        if !sources.isEmpty {
            queue.asyncAfter(deadline: .now() + Self.drainSeconds) { [self] in
                close(.stdout)
                close(.stderr)
                finishIfDone()
            }
        }
        finishIfDone()
    }

    private func finishIfDone() {
        guard !finished, let exit, sources.isEmpty else { return }
        finished = true
        continuation.yield(.exited(exit))
        continuation.finish()
    }
}
