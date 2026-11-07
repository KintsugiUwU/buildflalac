import Combine
import Foundation

/// The settings. Everything except the Jellyfin API key lives in UserDefaults; the key lives
/// only in the Keychain (see `Keychain`).
@MainActor
final class AppSettings: ObservableObject {
    private enum Key {
        static let flacFolder = "flacFolder"
        static let alacFolder = "alacFolder"
        static let library = "library"
        static let jellyfinURL = "jellyfinURL"
        static let jellyfinUser = "jellyfinUser"
        static let lyricsEnabled = "lyricsEnabled"
        static let lyricsStyle = "lyricsStyle"
        static let jellyfinMusicPath = "jellyfinMusicPath"
        static let maxBitDepth = "maxBitDepth"
        static let maxSampleRate = "maxSampleRate"
        /// Not shown in Settings: passed as --state when set (`defaults write`).
        static let stateFolder = "stateFolder"
    }

    private let defaults: UserDefaults

    @Published var flacFolder: String {
        didSet { defaults.set(flacFolder, forKey: Key.flacFolder) }
    }

    @Published var alacFolder: String {
        didSet { defaults.set(alacFolder, forKey: Key.alacFolder) }
    }

    @Published var library: LibraryChoice {
        didSet { defaults.set(library.rawValue, forKey: Key.library) }
    }

    @Published var jellyfinURL: String {
        didSet { defaults.set(jellyfinURL, forKey: Key.jellyfinURL) }
    }

    @Published var jellyfinUser: String {
        didSet {
            defaults.set(jellyfinUser, forKey: Key.jellyfinUser)
            if keyAccount(jellyfinUser) != keyAccount(oldValue) {
                userChanged()
            }
        }
    }

    /// The FLAC folder as the Jellyfin server sees it (inside its container, for example).
    @Published var jellyfinMusicPath: String {
        didSet { defaults.set(jellyfinMusicPath, forKey: Key.jellyfinMusicPath) }
    }

    @Published var maxBitDepth: BitDepthLimit {
        didSet { defaults.set(maxBitDepth.rawValue, forKey: Key.maxBitDepth) }
    }

    @Published var maxSampleRate: SampleRateLimit {
        didSet { defaults.set(maxSampleRate.rawValue, forKey: Key.maxSampleRate) }
    }

    @Published var lyricsEnabled: Bool {
        didSet { defaults.set(lyricsEnabled, forKey: Key.lyricsEnabled) }
    }

    @Published var lyricsStyle: LyricsStyle {
        didSet { defaults.set(lyricsStyle.rawValue, forKey: Key.lyricsStyle) }
    }

    /// The API key as shown in Settings. Edits are saved to the Keychain shortly after
    /// typing stops, and at once when Settings closes or a sync or test starts.
    @Published private(set) var jellyfinKey = ""
    /// Why the key could not be read or saved.
    @Published private(set) var keyProblem: String?
    private var keyEdited = false
    private var keyTask: Task<Void, Never>?

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        flacFolder = defaults.string(forKey: Key.flacFolder) ?? ""
        alacFolder = defaults.string(forKey: Key.alacFolder) ?? ""
        library = defaults.string(forKey: Key.library).flatMap(LibraryChoice.init(rawValue:))
            ?? Self.defaultLibrary
        jellyfinURL = defaults.string(forKey: Key.jellyfinURL) ?? ""
        jellyfinUser = defaults.string(forKey: Key.jellyfinUser) ?? ""
        jellyfinMusicPath = defaults.string(forKey: Key.jellyfinMusicPath) ?? Self.defaultJellyfinMusicPath
        maxBitDepth = (defaults.object(forKey: Key.maxBitDepth) as? Int).flatMap(BitDepthLimit.init(rawValue:))
            ?? .sixteen
        maxSampleRate = (defaults.object(forKey: Key.maxSampleRate) as? Int).flatMap(SampleRateLimit.init(rawValue:))
            ?? .cd
        lyricsEnabled = defaults.object(forKey: Key.lyricsEnabled) as? Bool ?? true
        lyricsStyle = defaults.string(forKey: Key.lyricsStyle).flatMap(LyricsStyle.init(rawValue:))
            ?? .plain
    }

    /// iTunes when it is installed (Retroactive puts it back on newer macOS), else Music.
    static var defaultLibrary: LibraryChoice {
        FileManager.default.fileExists(atPath: "/Applications/iTunes.app") ? .itunes : .music
    }

    static let defaultJellyfinMusicPath = "/Media/Music/FLAC"

    var foldersChosen: Bool {
        !flacFolder.isEmpty && !alacFolder.isEmpty
    }

    /// The --state override, when set.
    var stateFolder: String? {
        let folder = defaults.string(forKey: Key.stateFolder) ?? ""
        return folder.isEmpty ? nil : folder
    }

    /// Where the engine keeps its state (and reads no-lyrics.txt): the --state override, else
    /// the engine's default, ".flalac" next to the ALAC folder.
    var stateFolderURL: URL? {
        if let stateFolder {
            return URL(fileURLWithPath: stateFolder)
        }
        guard !alacFolder.isEmpty else { return nil }
        return URL(fileURLWithPath: alacFolder).deletingLastPathComponent().appendingPathComponent(".flalac")
    }

    /// Address and user, when both are filled in, with the FLAC folder's path in Jellyfin.
    var jellyfinAccount: JellyfinAccount? {
        let url = jellyfinURL.trimmingCharacters(in: .whitespacesAndNewlines)
        let user = keyAccount(jellyfinUser)
        guard !url.isEmpty, !user.isEmpty else { return nil }
        let path = jellyfinMusicPath.trimmingCharacters(in: .whitespacesAndNewlines)
        return JellyfinAccount(url: url, user: user, musicPath: path)
    }

    /// What `sync` should do with these settings.
    func syncRequest(jellyfin: JellyfinAccount?, confirmDeletes: Bool) -> SyncRequest {
        SyncRequest(
            source: flacFolder,
            target: alacFolder,
            state: stateFolder,
            library: library,
            jellyfin: jellyfin,
            lyricsEnabled: lyricsEnabled,
            lyricsStyle: lyricsStyle,
            maxBitDepth: maxBitDepth,
            maxSampleRate: maxSampleRate,
            confirmDeletes: confirmDeletes
        )
    }

    // MARK: - The API key

    /// Shows the key saved for the current user (when Settings opens or the user changes).
    func loadKey() {
        guard !keyEdited else { return }
        keyTask?.cancel()
        let account = keyAccount(jellyfinUser)
        guard !account.isEmpty else {
            jellyfinKey = ""
            keyProblem = nil
            return
        }
        do {
            jellyfinKey = try Keychain.key(for: account) ?? ""
            keyProblem = nil
        } catch {
            keyProblem = Self.describe(error)
        }
    }

    func editKey(_ key: String) {
        guard key != jellyfinKey else { return }
        jellyfinKey = key
        keyEdited = true
        later { $0.saveKey() }
    }

    /// Saves an edited key now. An emptied field removes the saved key.
    func saveKey() {
        keyTask?.cancel()
        guard keyEdited else { return }
        let account = keyAccount(jellyfinUser)
        guard !account.isEmpty else { return }  // saved once there is a user to save it for
        do {
            if jellyfinKey.isEmpty {
                try Keychain.deleteKey(for: account)
            } else {
                try Keychain.setKey(jellyfinKey, for: account)
            }
            keyEdited = false
            keyProblem = nil
        } catch {
            keyProblem = Self.describe(error)
        }
    }

    /// The key to pass to the engine. Read off the main thread: the Keychain may first ask
    /// the user to allow it (after the app was updated, for example).
    func currentKey() async -> String? {
        saveKey()
        if keyEdited {
            return jellyfinKey.isEmpty ? nil : jellyfinKey
        }
        let account = keyAccount(jellyfinUser)
        guard !account.isEmpty else { return nil }
        let key = await Task.detached { (try? Keychain.key(for: account)) ?? nil }.value
        return key?.isEmpty == false ? key : nil
    }

    private func userChanged() {
        if keyEdited {
            later { $0.saveKey() }
        } else {
            later { $0.loadKey() }
        }
    }

    /// Runs `action` once typing has paused.
    private func later(_ action: @escaping @MainActor (AppSettings) -> Void) {
        keyTask?.cancel()
        keyTask = Task { [weak self] in
            try? await Task.sleep(nanoseconds: 800_000_000)
            guard !Task.isCancelled, let self else { return }
            action(self)
        }
    }

    private func keyAccount(_ user: String) -> String {
        user.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private static func describe(_ error: Error) -> String {
        (error as? Keychain.Failure)?.message ?? error.localizedDescription
    }
}
