import Combine
import Foundation

/// How the last sync ended, kept across launches.
struct LastRun: Codable, Equatable, Sendable {
    enum Outcome: String, Codable, Sendable {
        case completed
        case failed
        case cancelled
    }

    var finished: Date
    var outcome: Outcome
    /// Why it failed.
    var message: String?
    var summary: SyncSummary?
}

/// Songs gone from the FLAC folder that the engine did not delete without asking.
struct PendingDeletes: Identifiable, Equatable {
    let id = UUID()
    var count: Int
    /// The library they would also be removed from, nil when only converting.
    var libraryName: String?
}

struct ConversionProgress: Equatable {
    var done: Int
    var total: Int
    var current: String
}

/// Runs `flalac-engine sync` for the main window and keeps what it reported.
@MainActor
final class SyncController: ObservableObject {
    enum Activity: Equatable {
        case idle
        case running
        case stopping
    }

    @Published private(set) var activity = Activity.idle
    /// The engine's stage: checking, converting, library or done; nil before the first.
    @Published private(set) var stage: String?
    @Published private(set) var conversion: ConversionProgress?
    /// The latest progress message (the library stage reports these).
    @Published private(set) var stageMessage: String?
    @Published private(set) var lastRun: LastRun?
    /// Set when the user has to decide about held deletions (shows the alert).
    @Published var pendingDeletes: PendingDeletes?
    @Published private(set) var engineVersion: String?
    /// Why the engine cannot be used, found when the app starts.
    @Published private(set) var engineProblem: String?

    let log = LogBuffer()

    /// Called when a sync has ended, and when it waits for the user to confirm deletions.
    var onFinish: ((LastRun) -> Void)?
    var onNeedsConfirmation: ((PendingDeletes) -> Void)?

    private let settings: AppSettings
    private let defaults: UserDefaults
    private var process: EngineProcess?
    private var cancelRequested = false
    private var stopWaiters: [() -> Void] = []
    /// The summary of a run that held deletions back, merged with the confirming run's.
    private var heldSummary: SyncSummary?

    private static let lastRunKey = "lastRun"

    init(settings: AppSettings, defaults: UserDefaults = .standard) {
        self.settings = settings
        self.defaults = defaults
        if let data = defaults.data(forKey: Self.lastRunKey) {
            lastRun = try? JSONDecoder().decode(LastRun.self, from: data)
        }
    }

    var isRunning: Bool {
        activity != .idle
    }

    func sync() {
        start(confirmDeletes: false)
    }

    /// Stops the engine: SIGTERM, then SIGKILL if it has not stopped after a while.
    func cancel() {
        guard activity == .running else { return }
        cancelRequested = true
        activity = .stopping
        process?.terminate()
    }

    /// Stops a running sync, then calls `done` once the engine has exited (for quitting).
    func stop(then done: @escaping () -> Void) {
        guard isRunning else {
            done()
            return
        }
        stopWaiters.append(done)
        cancel()
    }

    /// The user confirmed: run the sync again, now allowed to delete.
    func removeHeldDeletes() {
        pendingDeletes = nil
        start(confirmDeletes: true)
    }

    /// The user kept the songs: nothing more to do, the summary says they are still there.
    func keepHeldDeletes() {
        pendingDeletes = nil
        heldSummary = nil
    }

    /// Asks the engine for its version, to find a missing or broken engine early.
    func checkEngine() async {
        let run = await Engine.collect(EngineCommand.version, timeout: 30)
        if let problem = run.launchError {
            engineProblem = problem
            return
        }
        for case .version(let version) in run.messages where !version.isEmpty {
            engineVersion = version
        }
        if engineVersion != nil {
            engineProblem = nil
        } else if let message = run.messages.compactMap(\.errorText).first {
            engineProblem = message
        } else {
            engineProblem = run.exit.map { $0.succeeded ? "The engine did not say its version." : $0.explanation }
                ?? "The engine did not answer."
        }
    }

    // MARK: - Running

    private func start(confirmDeletes: Bool) {
        guard activity == .idle, settings.foldersChosen else { return }
        activity = .running
        cancelRequested = false
        stage = nil
        conversion = nil
        stageMessage = nil
        if confirmDeletes {
            log.append("")
            log.append("Removing the songs that are gone from the FLAC folder.")
        } else {
            log.clear()
            heldSummary = nil
        }
        Task {
            await run(confirmDeletes: confirmDeletes)
        }
    }

    private func run(confirmDeletes: Bool) async {
        let account = settings.jellyfinAccount
        var key: String?
        if account != nil {
            stageMessage = "Reading the Jellyfin key from the Keychain…"
            key = await settings.currentKey()
            stageMessage = nil
        }
        if let account, key == nil {
            log.append("Play counts are not synced: no Jellyfin API key is saved for \(account.user).")
        }
        let request = settings.syncRequest(jellyfin: key == nil ? nil : account, confirmDeletes: confirmDeletes)
        guard !cancelRequested else {
            finish(LastRun(finished: Date(), outcome: .cancelled))
            return
        }
        log.append("flalac-engine " + request.arguments.joined(separator: " "))

        let process: EngineProcess
        do {
            process = try Engine.launch(request.arguments, key: key)
        } catch {
            finish(LastRun(finished: Date(), outcome: .failed, message: error.localizedDescription))
            return
        }
        self.process = process

        var report = Report()
        for await event in process.events {
            switch event {
            case .message(let message):
                handle(message, into: &report)
            case .output(let line):
                log.append(line)
            case .exited(let exit):
                report.exit = exit
            }
        }
        self.process = nil
        conclude(report, request: request)
    }

    /// What one engine run said.
    private struct Report {
        var summary: SyncSummary?
        var error: String?
        var heldDeletes = 0
        var exit: EngineExit?
    }

    private func handle(_ message: EngineMessage, into report: inout Report) {
        switch message {
        case .stage(let newStage):
            stage = newStage
            stageMessage = nil
            if newStage != "converting" {
                conversion = nil
            }
        case .progress(let progress):
            if !progress.stage.isEmpty, progress.stage != stage {
                stage = progress.stage
                conversion = nil
                stageMessage = nil
            }
            if let done = progress.done, let total = progress.total {
                conversion = ConversionProgress(done: done, total: total, current: progress.current ?? "")
            }
            if let text = progress.message {
                stageMessage = text
            }
        case .heldDeletes(let count):
            report.heldDeletes = count
        case .summary(let summary):
            report.summary = summary
        case .error(let text):
            report.error = text
            log.append("Error: \(text)")
        case .version, .jellyfin:
            break
        case .unknown(let type):
            log.append("(A message of type \"\(type)\" was ignored.)")
        }
    }

    private func conclude(_ report: Report, request: SyncRequest) {
        let exit = report.exit ?? EngineExit(status: -1, signalled: false)
        if cancelRequested {
            log.append("Cancelled.")
            finish(LastRun(finished: Date(), outcome: .cancelled))
        } else if let error = report.error {
            finish(LastRun(finished: Date(), outcome: .failed, message: error))
        } else if !exit.succeeded {
            log.append(exit.explanation)
            finish(LastRun(finished: Date(), outcome: .failed, message: exit.explanation + " Details are in the log."))
        } else if let summary = report.summary {
            let total = request.confirmDeletes ? (heldSummary?.merged(with: summary) ?? summary) : summary
            heldSummary = nil
            if report.heldDeletes > 0, !request.confirmDeletes {
                heldSummary = summary
                pendingDeletes = PendingDeletes(count: report.heldDeletes, libraryName: request.library.appName)
            }
            finish(LastRun(finished: Date(), outcome: .completed, summary: total))
        } else {
            finish(LastRun(
                finished: Date(),
                outcome: .failed,
                message: "The engine ended without saying what it did. Details are in the log."
            ))
        }
    }

    private func finish(_ run: LastRun) {
        lastRun = run
        if let data = try? JSONEncoder().encode(run) {
            defaults.set(data, forKey: Self.lastRunKey)
        }
        activity = .idle
        stage = nil
        conversion = nil
        stageMessage = nil
        let waiters = stopWaiters
        stopWaiters = []
        waiters.forEach { $0() }
        if let pendingDeletes {
            onNeedsConfirmation?(pendingDeletes)
        } else {
            onFinish?(run)
        }
    }
}

/// The result of the Test button in Settings.
@MainActor
final class JellyfinTester: ObservableObject {
    enum State: Equatable {
        case idle
        case testing
        case passed(songs: Int?, plays: Int?)
        case failed(String)
    }

    @Published private(set) var state = State.idle

    func test(_ settings: AppSettings) {
        guard state != .testing, let account = settings.jellyfinAccount else { return }
        state = .testing
        Task {
            guard let key = await settings.currentKey() else {
                state = .failed("Enter the API key.")
                return
            }
            let run = await Engine.collect(EngineCommand.testJellyfin(account), key: key)
            state = Self.result(of: run)
        }
    }

    /// Forgets the result when the address, user or key change.
    func reset() {
        if state != .testing {
            state = .idle
        }
    }

    nonisolated static func result(of run: CollectedRun) -> State {
        if let problem = run.launchError {
            return .failed(problem)
        }
        for message in run.messages {
            if case .jellyfin(let check) = message {
                return check.ok
                    ? .passed(songs: check.songs, plays: check.plays)
                    : .failed(check.message ?? "Jellyfin did not accept the address, user or key.")
            }
        }
        if let message = run.messages.compactMap(\.errorText).first {
            return .failed(message)
        }
        if let exit = run.exit, !exit.succeeded {
            return .failed(exit.explanation)
        }
        return .failed("The engine gave no answer.")
    }
}

extension EngineMessage {
    var errorText: String? {
        if case .error(let text) = self {
            return text
        }
        return nil
    }
}

/// The text the engine wrote to stderr (and stdout lines that were not messages).
@MainActor
final class LogBuffer: ObservableObject {
    /// Only appended to; replaced when `generation` changes.
    private(set) var text = ""
    /// Changes when the text is cleared or trimmed.
    private(set) var generation = 0

    /// Older text is dropped beyond this many bytes.
    private static let limit = 4_000_000

    var isEmpty: Bool {
        text.isEmpty
    }

    func append(_ line: String) {
        objectWillChange.send()
        if !text.isEmpty {
            text.append("\n")
        }
        text.append(line)
        if text.utf8.count > Self.limit {
            text = "…" + String(text.suffix(Self.limit / 2))
            generation += 1
        }
    }

    func clear() {
        guard !text.isEmpty else { return }
        objectWillChange.send()
        text = ""
        generation += 1
    }
}
