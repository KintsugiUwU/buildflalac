import Combine
import Foundation

/// no-lyrics.txt in the state folder: FLAC files that never get lyrics (instrumental versions
/// LRCLIB has words for). One path per line, relative to the FLAC folder; lines starting with
/// "#" are comments. The engine reads the file itself on every sync; the app only edits it,
/// keeping comments and blank lines where they were.
enum NoLyricsFile {
    static let name = "no-lyrics.txt"

    enum Line: Equatable, Sendable {
        case entry(String)
        /// A comment or blank line, written back unchanged.
        case other(String)
    }

    static func parse(_ text: String) -> [Line] {
        var lines = text.components(separatedBy: "\n").map { line in
            line.hasSuffix("\r") ? String(line.dropLast()) : line
        }
        if lines.last == "" {
            lines.removeLast()
        }
        return lines.map { line in
            line.hasPrefix("#") || line.trimmingCharacters(in: .whitespaces).isEmpty ? .other(line) : .entry(line)
        }
    }

    static func render(_ lines: [Line]) -> String {
        lines.map { line in
            switch line {
            case .entry(let path): path
            case .other(let text): text
            }
        }.map { $0 + "\n" }.joined()
    }

    /// `file` relative to `folder`, or nil when it is not inside it.
    static func relativePath(of file: String, in folder: String) -> String? {
        let candidates = [
            (standardized(file), standardized(folder)),
            (resolved(file), resolved(folder)),
        ]
        for (path, base) in candidates {
            let prefix = base.hasSuffix("/") ? base : base + "/"
            if path.hasPrefix(prefix), path.count > prefix.count {
                return String(path.dropFirst(prefix.count))
            }
        }
        return nil
    }

    private static func standardized(_ path: String) -> String {
        URL(fileURLWithPath: path).standardizedFileURL.path
    }

    private static func resolved(_ path: String) -> String {
        URL(fileURLWithPath: path).resolvingSymlinksInPath().path
    }
}

/// The list "Songs without lyrics" in Settings.
@MainActor
final class NoLyricsList: ObservableObject {
    @Published private(set) var entries: [String] = []
    @Published private(set) var problem: String?
    /// The file shown, nil until the ALAC folder is chosen.
    @Published private(set) var fileURL: URL?
    private var lines: [NoLyricsFile.Line] = []

    /// Reads the file in `stateFolder` (a missing file is an empty list).
    func load(stateFolder: URL?) {
        fileURL = stateFolder?.appendingPathComponent(NoLyricsFile.name)
        lines = []
        problem = nil
        if let fileURL, FileManager.default.fileExists(atPath: fileURL.path) {
            do {
                lines = NoLyricsFile.parse(try String(contentsOf: fileURL, encoding: .utf8))
            } catch {
                problem = "\(fileURL.path) could not be read: \(error.localizedDescription)"
            }
        }
        publish()
    }

    /// Adds FLAC files from inside `flacFolder`; files elsewhere are refused.
    func add(_ files: [URL], flacFolder: String) {
        var added: [String] = []
        var refused: [String] = []
        for file in files {
            guard let path = NoLyricsFile.relativePath(of: file.path, in: flacFolder) else {
                refused.append(file.lastPathComponent)
                continue
            }
            guard !path.hasPrefix("#") else {
                refused.append(file.lastPathComponent)
                continue
            }
            if !entries.contains(path), !added.contains(path) {
                added.append(path)
            }
        }
        problem = nil
        if !added.isEmpty {
            lines += added.map(NoLyricsFile.Line.entry)
            save()
        }
        if !refused.isEmpty, problem == nil {
            problem = "Only songs inside the FLAC folder can be listed: \(refused.joined(separator: ", "))."
        }
    }

    func remove(_ entry: String) {
        guard let index = lines.firstIndex(of: .entry(entry)) else { return }
        lines.remove(at: index)
        save()
    }

    private func save() {
        guard let fileURL else {
            load(stateFolder: nil)
            problem = "Choose the ALAC folder first."
            return
        }
        let folder = fileURL.deletingLastPathComponent()
        do {
            if !FileManager.default.fileExists(atPath: folder.path) {
                // Only .flalac itself is created: a missing drive is not made up as a folder.
                guard FileManager.default.fileExists(atPath: folder.deletingLastPathComponent().path) else {
                    throw CocoaError(.fileNoSuchFile, userInfo: [NSFilePathErrorKey: folder.path])
                }
                try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: false)
            }
            try Data(NoLyricsFile.render(lines).utf8).write(to: fileURL, options: .atomic)
            problem = nil
        } catch {
            let message = "\(fileURL.path) could not be saved: \(error.localizedDescription)"
            load(stateFolder: folder)  // back to what the file holds
            problem = message
            return
        }
        publish()
    }

    private func publish() {
        entries = lines.compactMap { line in
            if case .entry(let path) = line {
                return path
            }
            return nil
        }
    }
}
