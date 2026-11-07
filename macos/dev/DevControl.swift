#if FLALAC_DEV
import AppKit

/// Development builds only (DEV=1 ./build.sh): lets dev/ctl.sh drive the app and capture its
/// windows, for checking the flows without clicking. Commands arrive as distributed
/// notifications "com.davidepetris.flalac.dev" whose object is "<id> <command> [args]"; the id
/// is written to $FLALAC_DEV_OUT/ack when the command has run.
@MainActor
final class DevControl: NSObject {
    private static var shared: DevControl?
    private let app: AppDelegate
    private let out: URL

    private init(_ app: AppDelegate, out: URL) {
        self.app = app
        self.out = out
    }

    static func install(_ app: AppDelegate) {
        guard let path = ProcessInfo.processInfo.environment["FLALAC_DEV_OUT"] else { return }
        let control = DevControl(app, out: URL(fileURLWithPath: path))
        DistributedNotificationCenter.default().addObserver(
            control,
            selector: #selector(received(_:)),
            name: Notification.Name("com.davidepetris.flalac.dev"),
            object: nil,
            suspensionBehavior: .deliverImmediately
        )
        shared = control
    }

    @objc private func received(_ notification: Notification) {
        guard let text = notification.object as? String else { return }
        var words = text.components(separatedBy: " ")
        let id = words.removeFirst()
        let command = words.isEmpty ? "" : words.removeFirst()
        let rest = words.joined(separator: " ")
        run(command, rest)
        try? id.write(to: out.appendingPathComponent("ack"), atomically: true, encoding: .utf8)
    }

    private func run(_ command: String, _ rest: String) {
        let settings = app.settings
        let controller = app.controller
        switch command {
        case "sync": controller.sync()
        case "cancel": controller.cancel()
        case "remove": clickAlertButton("Remove") ?? controller.removeHeldDeletes()
        case "keep": clickAlertButton("Keep") ?? controller.keepHeldDeletes()
        case "settings": app.showSettings(nil)
        case "close-settings": app.settingsWindow?.performClose(nil)
        case "tab": UserDefaults.standard.set(rest, forKey: "settingsTab")
        case "log": UserDefaults.standard.set(rest == "open", forKey: "showLog")
        case "test-jellyfin": app.tester.test(settings)
        case "nolyrics-add": app.noLyrics.add([URL(fileURLWithPath: rest)], flacFolder: settings.flacFolder)
        case "appearance": NSApp.appearance = NSAppearance(named: rest == "dark" ? .darkAqua : .aqua)
        case "quit": NSApp.terminate(nil)
        case "snapshot":
            let parts = rest.components(separatedBy: " ")
            let window = parts[0] == "settings" ? app.settingsWindow : app.mainWindow
            if let window { snapshot(window, to: out.appendingPathComponent(parts[1])) }
        case "state": writeState(to: out.appendingPathComponent(rest))
        case "set":
            var parts = rest.components(separatedBy: " ")
            let key = parts.removeFirst()
            let value = parts.joined(separator: " ")
            switch key {
            case "flac": settings.flacFolder = value
            case "alac": settings.alacFolder = value
            case "library": settings.library = LibraryChoice(rawValue: value) ?? .itunes
            case "url": settings.jellyfinURL = value
            case "user": settings.jellyfinUser = value
            case "path": settings.jellyfinMusicPath = value
            case "apikey": settings.editKey(value)
            case "depth": settings.maxBitDepth = BitDepthLimit(rawValue: Int(value) ?? 16) ?? .sixteen
            case "rate": settings.maxSampleRate = SampleRateLimit(rawValue: Int(value) ?? 44100) ?? .cd
            case "lyrics": settings.lyricsEnabled = value == "on"
            case "style": settings.lyricsStyle = LyricsStyle(rawValue: value) ?? .plain
            default: break
            }
        default: break
        }
    }

    /// Presses a button of the alert sheet on the main window, as a click would.
    private func clickAlertButton(_ title: String) -> Void? {
        guard let sheet = app.mainWindow?.attachedSheet,
              let button = Self.buttons(in: sheet.contentView).first(where: { $0.title == title }) else {
            return nil
        }
        button.performClick(nil)
        return ()
    }

    private static func buttons(in view: NSView?) -> [NSButton] {
        guard let view else { return [] }
        return ((view as? NSButton).map { [$0] } ?? []) + view.subviews.flatMap { buttons(in: $0) }
    }

    /// The window and any sheet on it, as on screen (own windows need no permission).
    private func snapshot(_ window: NSWindow, to url: URL) {
        var ids = [CGWindowID(window.windowNumber)]
        if let sheet = window.attachedSheet {
            ids.insert(CGWindowID(sheet.windowNumber), at: 0)
        }
        let pointers = ids.map { UnsafeRawPointer(bitPattern: UInt($0)) }
        let array = pointers.withUnsafeBufferPointer { buffer in
            CFArrayCreate(nil, UnsafeMutablePointer(mutating: buffer.baseAddress), buffer.count, nil)
        }
        guard let array,
              let image = CGImage(windowListFromArrayScreenBounds: .null, windowArray: array,
                                  imageOption: [.boundsIgnoreFraming, .bestResolution]),
              let png = NSBitmapImageRep(cgImage: image).representation(using: .png, properties: [:]) else {
            return
        }
        try? png.write(to: url)
    }

    private func writeState(to url: URL) {
        let controller = app.controller
        let settings = app.settings
        var state: [String: Any] = [
            "activity": "\(controller.activity)",
            "stage": controller.stage ?? "",
            "pendingDeletes": controller.pendingDeletes?.count ?? 0,
            "engineVersion": controller.engineVersion ?? "",
            "engineProblem": controller.engineProblem ?? "",
            "flac": settings.flacFolder,
            "alac": settings.alacFolder,
            "library": settings.library.rawValue,
            "url": settings.jellyfinURL,
            "user": settings.jellyfinUser,
            "path": settings.jellyfinMusicPath,
            "keyLoaded": !settings.jellyfinKey.isEmpty,
            "keyProblem": settings.keyProblem ?? "",
            "depth": settings.maxBitDepth.rawValue,
            "rate": settings.maxSampleRate.rawValue,
            "lyrics": settings.lyricsEnabled,
            "style": settings.lyricsStyle.rawValue,
            "noLyrics": app.noLyrics.entries,
            "noLyricsProblem": app.noLyrics.problem ?? "",
            "tester": "\(app.tester.state)",
            "log": controller.log.text,
        ]
        if let run = controller.lastRun, let data = try? JSONEncoder().encode(run) {
            state["lastRun"] = (try? JSONSerialization.jsonObject(with: data)) ?? [:]
        }
        if let data = try? JSONSerialization.data(withJSONObject: state, options: [.prettyPrinted, .sortedKeys]) {
            try? data.write(to: url)
        }
    }
}
#endif
