import Foundation

// The command line and the messages of flalac-engine, the bundled program that does the
// work. One JSON object per line on stdout; stderr is free-form log text. See README.md.

/// The library the engine keeps in step with the ALAC folder (`--library`).
enum LibraryChoice: String, CaseIterable, Codable, Sendable {
    case itunes
    case music
    case none

    var title: String {
        switch self {
        case .itunes: "iTunes"
        case .music: "Music"
        case .none: "Convert only"
        }
    }

    /// The app whose library is updated, nil when only converting.
    var appName: String? {
        switch self {
        case .itunes: "iTunes"
        case .music: "Music"
        case .none: nil
        }
    }
}

/// `--lyrics-style`.
enum LyricsStyle: String, CaseIterable, Codable, Sendable {
    case plain
    case synced

    var title: String {
        switch self {
        case .plain: "Plain"
        case .synced: "Synced"
        }
    }
}

/// `--max-bit-depth`: higher bit depths are reduced (with dither); 0 keeps the source's.
enum BitDepthLimit: Int, CaseIterable, Codable, Sendable {
    case sixteen = 16
    case twentyFour = 24
    case source = 0

    var title: String {
        switch self {
        case .sixteen: "16-bit (iPod)"
        case .twentyFour: "24-bit"
        case .source: "Same as source"
        }
    }
}

/// `--max-sample-rate`: higher rates are resampled to this one; 0 keeps the source's.
enum SampleRateLimit: Int, CaseIterable, Codable, Sendable {
    case cd = 44100
    case dvd = 48000
    case source = 0

    var title: String {
        switch self {
        case .cd: "44.1 kHz (iPod)"
        case .dvd: "48 kHz"
        case .source: "Same as source"
        }
    }
}

/// The Jellyfin server and user whose play counts are synced, and the FLAC folder's path as
/// that server sees it. The API key is not part of it: it only ever travels in the
/// environment variable `EngineCommand.keyVariable`.
struct JellyfinAccount: Equatable, Sendable {
    var url: String
    var user: String
    /// `--jellyfin-music-path`, left out when empty (the engine's default then applies).
    var musicPath = ""

    var arguments: [String] {
        var arguments = ["--jellyfin-url", url, "--jellyfin-user", user]
        if !musicPath.isEmpty {
            arguments += ["--jellyfin-music-path", musicPath]
        }
        return arguments
    }
}

/// `flalac-engine sync …`
struct SyncRequest: Equatable, Sendable {
    var source: String
    var target: String
    var state: String?
    var library: LibraryChoice
    var jellyfin: JellyfinAccount?
    var lyricsEnabled: Bool
    var lyricsStyle: LyricsStyle
    var maxBitDepth = BitDepthLimit.sixteen
    var maxSampleRate = SampleRateLimit.cd
    var confirmDeletes = false

    var arguments: [String] {
        var arguments = ["sync", "--source", source, "--target", target]
        if let state, !state.isEmpty {
            arguments += ["--state", state]
        }
        arguments += ["--library", library.rawValue]
        if let jellyfin {
            arguments += jellyfin.arguments
        }
        if lyricsEnabled {
            arguments += ["--lyrics", "lrclib", "--lyrics-style", lyricsStyle.rawValue]
        } else {
            arguments += ["--lyrics", "off"]
        }
        arguments += ["--max-bit-depth", String(maxBitDepth.rawValue)]
        arguments += ["--max-sample-rate", String(maxSampleRate.rawValue)]
        if confirmDeletes {
            arguments.append("--confirm-deletes")
        }
        return arguments
    }
}

enum EngineCommand {
    /// The environment variable that carries the Jellyfin API key. Never an argument.
    static let keyVariable = "FLALAC_JELLYFIN_KEY"

    static let version = ["version"]

    static func testJellyfin(_ account: JellyfinAccount) -> [String] {
        ["test-jellyfin"] + account.arguments
    }
}

// MARK: - Messages

/// `{"type":"progress",…}`: done/total/current while converting, message in the library stage.
struct EngineProgress: Equatable, Sendable {
    var stage: String
    var done: Int?
    var total: Int?
    var current: String?
    var message: String?
}

/// The `library` part of a summary.
struct LibrarySummary: Codable, Equatable, Sendable {
    var app: String
    var added = 0
    var removed = 0
    var moved = 0
    var refreshed = 0
    var plays = 0
    var failed = 0

    init(app: String, added: Int = 0, removed: Int = 0, moved: Int = 0, refreshed: Int = 0,
         plays: Int = 0, failed: Int = 0) {
        self.app = app
        self.added = added
        self.removed = removed
        self.moved = moved
        self.refreshed = refreshed
        self.plays = plays
        self.failed = failed
    }

    /// Missing counts are read as 0, so an engine that adds or drops a field still works.
    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        app = try values.decodeIfPresent(String.self, forKey: .app) ?? ""
        added = try values.decodeIfPresent(Int.self, forKey: .added) ?? 0
        removed = try values.decodeIfPresent(Int.self, forKey: .removed) ?? 0
        moved = try values.decodeIfPresent(Int.self, forKey: .moved) ?? 0
        refreshed = try values.decodeIfPresent(Int.self, forKey: .refreshed) ?? 0
        plays = try values.decodeIfPresent(Int.self, forKey: .plays) ?? 0
        failed = try values.decodeIfPresent(Int.self, forKey: .failed) ?? 0
    }

    var changedNothing: Bool {
        added == 0 && removed == 0 && moved == 0 && refreshed == 0 && plays == 0 && failed == 0
    }
}

/// `{"type":"summary",…}`: what one sync did.
struct SyncSummary: Codable, Equatable, Sendable {
    var converted = 0
    var retagged = 0
    var renamed = 0
    var removed = 0
    var errors = 0
    var unsettled = 0
    var heldDeletes = 0
    var seconds = 0.0
    var library: LibrarySummary?
    var notes: [String] = []

    enum CodingKeys: String, CodingKey {
        case converted, retagged, renamed, removed, errors, unsettled, seconds, library, notes
        case heldDeletes = "held_deletes"
    }

    init(converted: Int = 0, retagged: Int = 0, renamed: Int = 0, removed: Int = 0,
         errors: Int = 0, unsettled: Int = 0, heldDeletes: Int = 0, seconds: Double = 0,
         library: LibrarySummary? = nil, notes: [String] = []) {
        self.converted = converted
        self.retagged = retagged
        self.renamed = renamed
        self.removed = removed
        self.errors = errors
        self.unsettled = unsettled
        self.heldDeletes = heldDeletes
        self.seconds = seconds
        self.library = library
        self.notes = notes
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        converted = try values.decodeIfPresent(Int.self, forKey: .converted) ?? 0
        retagged = try values.decodeIfPresent(Int.self, forKey: .retagged) ?? 0
        renamed = try values.decodeIfPresent(Int.self, forKey: .renamed) ?? 0
        removed = try values.decodeIfPresent(Int.self, forKey: .removed) ?? 0
        errors = try values.decodeIfPresent(Int.self, forKey: .errors) ?? 0
        unsettled = try values.decodeIfPresent(Int.self, forKey: .unsettled) ?? 0
        heldDeletes = try values.decodeIfPresent(Int.self, forKey: .heldDeletes) ?? 0
        seconds = try values.decodeIfPresent(Double.self, forKey: .seconds) ?? 0
        library = try values.decodeIfPresent(LibrarySummary.self, forKey: .library)
        notes = try values.decodeIfPresent([String].self, forKey: .notes) ?? []
    }

    var changedNothing: Bool {
        converted == 0 && retagged == 0 && renamed == 0 && removed == 0 && errors == 0
            && unsettled == 0 && heldDeletes == 0 && (library?.changedNothing ?? true)
    }

    /// One summary for a sync that was run again with `--confirm-deletes`: what both runs did,
    /// and the state the later run left (errors, unsettled songs and held deletions are
    /// counted again by every run, so they come from `later` alone).
    func merged(with later: SyncSummary) -> SyncSummary {
        var result = later
        result.converted += converted
        result.retagged += retagged
        result.renamed += renamed
        result.removed += removed
        result.seconds += seconds
        if let first = library {
            if var second = later.library {
                second.added += first.added
                second.removed += first.removed
                second.moved += first.moved
                second.refreshed += first.refreshed
                second.plays += first.plays
                result.library = second
            } else {
                result.library = first
            }
        }
        var notes = self.notes
        for note in later.notes where !notes.contains(note) {
            notes.append(note)
        }
        result.notes = notes
        return result
    }
}

/// `{"type":"jellyfin",…}`, the answer to test-jellyfin.
struct JellyfinCheck: Equatable, Sendable {
    var ok: Bool
    var songs: Int?
    var plays: Int?
    var message: String?
}

enum EngineMessage: Equatable, Sendable {
    case stage(String)
    case progress(EngineProgress)
    case heldDeletes(Int)
    case summary(SyncSummary)
    case jellyfin(JellyfinCheck)
    case version(String)
    case error(String)
    /// A JSON object with a type this app does not know (a newer engine); ignored.
    case unknown(type: String)

    /// The message on one stdout line, or nil when the line is not a JSON object with a
    /// "type" (it is then shown in the log as text).
    static func decode(_ line: String) -> EngineMessage? {
        let trimmed = line.trimmingCharacters(in: .whitespaces)
        guard trimmed.hasPrefix("{"), let data = trimmed.data(using: .utf8) else {
            return nil
        }
        let decoder = JSONDecoder()
        guard let envelope = try? decoder.decode(Envelope.self, from: data) else {
            return nil
        }
        switch envelope.type {
        case "stage":
            guard let stage = envelope.stage else { return nil }
            return .stage(stage)
        case "progress":
            return .progress(EngineProgress(
                stage: envelope.stage ?? "",
                done: envelope.done,
                total: envelope.total,
                current: envelope.current,
                message: envelope.message
            ))
        case "held-deletes":
            return .heldDeletes(envelope.count ?? 0)
        case "summary":
            guard let summary = try? decoder.decode(SyncSummary.self, from: data) else {
                return nil
            }
            return .summary(summary)
        case "jellyfin":
            return .jellyfin(JellyfinCheck(
                ok: envelope.ok ?? false,
                songs: envelope.songs,
                plays: envelope.plays,
                message: envelope.message
            ))
        case "version":
            return .version(envelope.version ?? "")
        case "error":
            return .error(envelope.message ?? "The engine reported an error without a message.")
        default:
            return .unknown(type: envelope.type)
        }
    }

    private struct Envelope: Decodable {
        var type: String
        var stage: String?
        var done: Int?
        var total: Int?
        var current: String?
        var message: String?
        var count: Int?
        var ok: Bool?
        var songs: Int?
        var plays: Int?
        var version: String?
    }
}
