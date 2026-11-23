import AppKit
import SwiftUI
import UniformTypeIdentifiers

@main
enum FlalacMain {
    @MainActor
    static func main() {
        let app = NSApplication.shared
        let delegate = AppDelegate()
        app.delegate = delegate
        app.setActivationPolicy(.regular)
        withExtendedLifetime(delegate) {
            app.run()
        }
    }
}

/// Owns the settings, the sync, the two windows and the menu bar.
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, NSWindowDelegate {
    let settings = AppSettings()
    let tester = JellyfinTester()
    let noLyrics = NoLyricsList()
    let updater = Updater()
    lazy var controller = SyncController(settings: settings)
    private(set) var mainWindow: NSWindow?
    private(set) var settingsWindow: NSWindow?
    private(set) var aboutWindow: NSWindow?

    func applicationWillFinishLaunching(_ notification: Notification) {
        NSApp.mainMenu = MainMenu.make()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        controller.onFinish = { run in Notifier.syncFinished(run) }
        controller.onNeedsConfirmation = { pending in Notifier.needsConfirmation(pending) }
        showMainWindow(nil)  // a first launch sets up the folders right in the main window
        NSApp.activate(ignoringOtherApps: true)
        updater.check()
        Task {
            await controller.checkEngine()
        }
        #if FLALAC_DEV
        DevControl.install(self)
        #endif
    }

    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if mainWindow?.isVisible != true {
            showMainWindow(nil)
        }
        return true
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        true
    }

    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard controller.isRunning else { return .terminateNow }
        let alert = NSAlert()
        alert.messageText = "A sync is running."
        alert.informativeText = "Stop it and quit? Songs not converted yet are converted at the next sync."
        alert.addButton(withTitle: "Stop and Quit")
        alert.addButton(withTitle: "Continue")
        guard alert.runModal() == .alertFirstButtonReturn else {
            if mainWindow?.isVisible != true {
                showMainWindow(nil)
            }
            return .terminateCancel
        }
        controller.stop {
            NSApp.reply(toApplicationShouldTerminate: true)
        }
        return .terminateLater
    }

    func applicationWillTerminate(_ notification: Notification) {
        settings.saveKey()
    }

    // MARK: - Windows

    @objc func showMainWindow(_ sender: Any?) {
        if mainWindow == nil {
            let view = MainView(
                settings: settings,
                controller: controller,
                log: controller.log,
                updater: updater,
                openSettings: { [weak self] in self?.showSettings(nil) },
                chooseFolder: { [weak self] kind in self?.chooseFolder(kind) }
            )
            let window = NSWindow(contentViewController: NSHostingController(rootView: view))
            window.title = "Flalac"
            window.styleMask = [.titled, .closable, .miniaturizable]
            window.isReleasedWhenClosed = false
            window.center()
            window.setFrameAutosaveName("Main")
            mainWindow = window
        }
        mainWindow?.makeKeyAndOrderFront(sender)
    }

    @objc func showSettings(_ sender: Any?) {
        if settingsWindow == nil {
            let view = SettingsView(
                settings: settings,
                tester: tester,
                noLyrics: noLyrics,
                chooseFolder: { [weak self] kind in self?.chooseFolder(kind) },
                addSongsWithoutLyrics: { [weak self] in self?.addSongsWithoutLyrics() }
            )
            let window = NSWindow(contentViewController: NSHostingController(rootView: view))
            window.title = SettingsName.title
            window.styleMask = [.titled, .closable]
            window.isReleasedWhenClosed = false
            window.delegate = self
            window.center()
            window.setFrameAutosaveName("Settings")
            settingsWindow = window
        }
        settings.loadKey()
        noLyrics.load(stateFolder: settings.stateFolderURL)
        settingsWindow?.makeKeyAndOrderFront(sender)
        NSApp.activate(ignoringOtherApps: true)
    }

    func windowWillClose(_ notification: Notification) {
        if (notification.object as? NSWindow) === settingsWindow {
            settings.saveKey()
        }
    }

    /// The + under "Songs without lyrics": FLAC files from the FLAC folder.
    func addSongsWithoutLyrics() {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = true
        if let flac = UTType(filenameExtension: "flac") {
            panel.allowedContentTypes = [flac]
        }
        panel.directoryURL = URL(fileURLWithPath: settings.flacFolder)
        panel.prompt = "Add"
        panel.message = "Choose songs in the FLAC folder that should never get lyrics."
        let apply: (NSApplication.ModalResponse) -> Void = { [weak self] response in
            guard response == .OK, let self else { return }
            self.noLyrics.add(panel.urls, flacFolder: self.settings.flacFolder)
        }
        if let window = settingsWindow, window.isVisible {
            panel.beginSheetModal(for: window, completionHandler: apply)
        } else {
            apply(panel.runModal())
        }
    }

    func chooseFolder(_ kind: FolderKind) {
        let panel = NSOpenPanel()
        panel.canChooseDirectories = true
        panel.canChooseFiles = false
        panel.allowsMultipleSelection = false
        panel.canCreateDirectories = kind == .alac
        panel.prompt = "Choose"
        switch kind {
        case .flac:
            panel.message = "Choose the FLAC folder to copy from."
        case .alac:
            panel.message = "Choose the folder for the ALAC copy, on the music drive."
        }
        let current = kind == .flac ? settings.flacFolder : settings.alacFolder
        if !current.isEmpty {
            panel.directoryURL = URL(fileURLWithPath: current)
        }
        let apply: (NSApplication.ModalResponse) -> Void = { [weak self] response in
            guard response == .OK, let self, let url = panel.url else { return }
            switch kind {
            case .flac: self.settings.flacFolder = url.path
            case .alac: self.settings.alacFolder = url.path
            }
        }
        if let window = settingsWindow, window.isVisible {
            panel.beginSheetModal(for: window, completionHandler: apply)
        } else if let window = mainWindow, window.isVisible {
            panel.beginSheetModal(for: window, completionHandler: apply)
        } else {
            apply(panel.runModal())
        }
    }

    // MARK: - Menu actions

    @objc func checkForUpdates(_ sender: Any?) {
        updater.check(answerAlways: true)
    }

    @objc func showAbout(_ sender: Any?) {
        if aboutWindow == nil {
            let view = AboutView(version: updater.current, engineVersion: controller.engineVersion)
            let window = NSWindow(contentViewController: NSHostingController(rootView: view))
            window.title = ""
            window.styleMask = [.titled, .closable]
            window.titlebarAppearsTransparent = true
            window.isReleasedWhenClosed = false
            window.center()
            aboutWindow = window
        }
        aboutWindow?.makeKeyAndOrderFront(sender)
        NSApp.activate(ignoringOtherApps: true)
    }

    @objc func sync(_ sender: Any?) {
        controller.sync()
    }

    #if FLALAC_PREVIEW
    /// Test builds: show a decoration whatever the date (the window follows the setting).
    @objc func previewDecoration(_ sender: NSMenuItem) {
        UserDefaults.standard.set(sender.representedObject as? String ?? "", forKey: Decorations.previewKey)
    }
    #endif
}

extension AppDelegate: NSMenuItemValidation {
    func validateMenuItem(_ menuItem: NSMenuItem) -> Bool {
        if menuItem.action == #selector(sync(_:)) {
            return settings.foldersChosen && settings.foldersMissing == nil && !controller.isRunning
        }
        #if FLALAC_PREVIEW
        if menuItem.action == #selector(previewDecoration(_:)) {
            let chosen = UserDefaults.standard.string(forKey: Decorations.previewKey) ?? ""
            menuItem.state = (menuItem.representedObject as? String ?? "") == chosen ? .on : .off
        }
        #endif
        return true
    }
}

/// The standard menu bar of a small single-window app.
@MainActor
enum MainMenu {
    static func make() -> NSMenu {
        let menu = NSMenu()

        let app = submenu(of: menu, title: "Flalac")
        app.addItem(withTitle: "About Flalac", action: #selector(AppDelegate.showAbout(_:)), keyEquivalent: "")
        app.addItem(withTitle: "Check for Updates…", action: #selector(AppDelegate.checkForUpdates(_:)), keyEquivalent: "")
        app.addItem(.separator())
        app.addItem(withTitle: "\(SettingsName.title)…", action: #selector(AppDelegate.showSettings(_:)), keyEquivalent: ",")
        app.addItem(.separator())
        let services = app.addItem(withTitle: "Services", action: nil, keyEquivalent: "")
        services.submenu = NSMenu(title: "Services")
        NSApp.servicesMenu = services.submenu
        app.addItem(.separator())
        app.addItem(withTitle: "Hide Flalac", action: #selector(NSApplication.hide(_:)), keyEquivalent: "h")
        let others = app.addItem(
            withTitle: "Hide Others",
            action: #selector(NSApplication.hideOtherApplications(_:)),
            keyEquivalent: "h"
        )
        others.keyEquivalentModifierMask = [.command, .option]
        app.addItem(withTitle: "Show All", action: #selector(NSApplication.unhideAllApplications(_:)), keyEquivalent: "")
        app.addItem(.separator())
        app.addItem(withTitle: "Quit Flalac", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")

        let file = submenu(of: menu, title: "File")
        file.addItem(withTitle: "Sync", action: #selector(AppDelegate.sync(_:)), keyEquivalent: "r")
        file.addItem(.separator())
        file.addItem(withTitle: "Close", action: #selector(NSWindow.performClose(_:)), keyEquivalent: "w")

        let edit = submenu(of: menu, title: "Edit")
        edit.addItem(withTitle: "Undo", action: Selector(("undo:")), keyEquivalent: "z")
        let redo = edit.addItem(withTitle: "Redo", action: Selector(("redo:")), keyEquivalent: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        edit.addItem(.separator())
        edit.addItem(withTitle: "Cut", action: #selector(NSText.cut(_:)), keyEquivalent: "x")
        edit.addItem(withTitle: "Copy", action: #selector(NSText.copy(_:)), keyEquivalent: "c")
        edit.addItem(withTitle: "Paste", action: #selector(NSText.paste(_:)), keyEquivalent: "v")
        edit.addItem(withTitle: "Select All", action: #selector(NSText.selectAll(_:)), keyEquivalent: "a")
        edit.addItem(.separator())
        let find = edit.addItem(
            withTitle: "Find…",
            action: #selector(NSTextView.performFindPanelAction(_:)),
            keyEquivalent: "f"
        )
        find.tag = Int(NSFindPanelAction.showFindPanel.rawValue)

        #if FLALAC_PREVIEW
        let decorations = submenu(of: menu, title: "Decorations")
        let choices: [(String, String)] = [("By date", Decorations.automatic), ("None", Decorations.none)]
            + Festivity.allCases.map { ($0.title, $0.rawValue) }
        for (index, (title, value)) in choices.enumerated() {
            if index == 2 { decorations.addItem(.separator()) }
            let item = decorations.addItem(
                withTitle: title,
                action: #selector(AppDelegate.previewDecoration(_:)),
                keyEquivalent: ""
            )
            item.representedObject = value
        }
        decorations.addItem(.separator())
        let year = Calendar.current.component(.year, from: Date())
        let today = Festivity.on(Date()).map { $0.title } ?? "nothing"
        decorations.addItem(withTitle: "Today by date: \(today)", action: nil, keyEquivalent: "")
        for festivity in Festivity.allCases {
            decorations.addItem(
                withTitle: "\(festivity.title), \(year): \(festivity.dates(in: year))",
                action: nil,
                keyEquivalent: ""
            )
        }
        #endif

        let window = submenu(of: menu, title: "Window")
        window.addItem(withTitle: "Minimize", action: #selector(NSWindow.performMiniaturize(_:)), keyEquivalent: "m")
        window.addItem(withTitle: "Zoom", action: #selector(NSWindow.performZoom(_:)), keyEquivalent: "")
        window.addItem(.separator())
        window.addItem(withTitle: "Bring All to Front", action: #selector(NSApplication.arrangeInFront(_:)), keyEquivalent: "")
        NSApp.windowsMenu = window

        return menu
    }

    private static func submenu(of menu: NSMenu, title: String) -> NSMenu {
        let item = menu.addItem(withTitle: title, action: nil, keyEquivalent: "")
        let submenu = NSMenu(title: title)
        item.submenu = submenu
        return submenu
    }
}
