import AppKit
import SwiftUI

/// The main window: the two folders, Sync, progress, the last result and the log. Before the
/// folders are chosen it shows the short setup instead, so a first launch is one window.
struct MainView: View {
    @ObservedObject var settings: AppSettings
    @ObservedObject var controller: SyncController
    @ObservedObject var log: LogBuffer
    @ObservedObject var updater: Updater
    @AppStorage("showLog") private var showLog = false
    @State private var volumesChanged = 0  // re-checks the folders when drives come and go
    let openSettings: () -> Void
    let chooseFolder: (FolderKind) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if let release = updater.available {
                UpdateNote(version: release.version, download: updater.openDownload)
            }
            if settings.foldersChosen {
                configured
            } else {
                SetupView(settings: settings, chooseFolder: chooseFolder)
            }
        }
        .padding(20)
        .frame(width: 480)
        .fixedSize(horizontal: false, vertical: true)
        .alert(item: $controller.pendingDeletes) { pending in
            deletesAlert(pending)
        }
        .onReceive(NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.didMountNotification)) { _ in
            volumesChanged += 1
        }
        .onReceive(NSWorkspace.shared.notificationCenter.publisher(for: NSWorkspace.didUnmountNotification)) { _ in
            volumesChanged += 1
        }
        .onReceive(NotificationCenter.default.publisher(for: NSApplication.didBecomeActiveNotification)) { _ in
            volumesChanged += 1
        }
    }

    private var missing: String? {
        _ = volumesChanged
        if !Self.isFolder(settings.flacFolder) { return "The FLAC folder is not reachable. Connect the share." }
        if !Self.isFolder(settings.alacFolder) { return "The ALAC folder is not reachable. Connect the drive." }
        return nil
    }

    private static func isFolder(_ path: String) -> Bool {
        var isDirectory: ObjCBool = false
        return FileManager.default.fileExists(atPath: path, isDirectory: &isDirectory) && isDirectory.boolValue
    }

    @ViewBuilder private var configured: some View {
        VStack(alignment: .leading, spacing: 16) {
            FoldersView(settings: settings, refresh: volumesChanged)
            Divider()
            status
            if !controller.isRunning, let missing {
                Warning(text: missing)
            }
            buttons
            if !log.isEmpty {
                DisclosureGroup("Log", isExpanded: $showLog) {
                    LogView(log: log)
                        .frame(height: 180)
                        .padding(.top, 4)
                }
            }
        }
    }

    @ViewBuilder private var status: some View {
        if controller.isRunning {
            ProgressSection(controller: controller, libraryName: settings.library.appName)
        } else if let lastRun = controller.lastRun {
            SummaryView(run: lastRun)
        } else {
            Text("Not synced yet.")
                .foregroundColor(.secondary)
        }
        if !controller.isRunning, let problem = controller.engineProblem {
            Warning(text: problem)
        }
    }

    private var buttons: some View {
        HStack {
            Spacer()
            if controller.isRunning {
                Button("Cancel") { controller.cancel() }
                    .keyboardShortcut(.cancelAction)
                    .disabled(controller.activity == .stopping)
            } else {
                Button(action: { controller.sync() }) {
                    Text("Sync").frame(minWidth: 90)
                }
                .keyboardShortcut(.defaultAction)
                .disabled(missing != nil)
            }
        }
        .controlSize(.large)
    }

    private func deletesAlert(_ pending: PendingDeletes) -> Alert {
        let gone = pending.count == 1
            ? "1 song is gone from the FLAC folder."
            : "\(Format.count(pending.count)) songs are gone from the FLAC folder."
        let question = pending.libraryName == nil
            ? "Remove them from the drive too?"
            : "Remove them from the drive and the library too?"
        return Alert(
            title: Text(gone),
            message: Text(question),
            primaryButton: .destructive(Text("Remove")) { controller.removeHeldDeletes() },
            secondaryButton: .cancel(Text("Keep")) { controller.keepHeldDeletes() }
        )
    }
}

/// The selected folders, as plain secondary text.
private struct FoldersView: View {
    @ObservedObject var settings: AppSettings
    let refresh: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            row("FLAC", settings.flacFolder)
            row("ALAC", settings.alacFolder)
        }
    }

    private func row(_ label: String, _ path: String) -> some View {
        _ = refresh
        let connected = FileManager.default.fileExists(atPath: path)
        return HStack(spacing: 8) {
            Image(nsImage: Self.icon(for: path))
                .resizable()
                .frame(width: 18, height: 18)
                .opacity(connected ? 1 : 0.4)
            Text(Self.readable(path))
                .foregroundColor(connected ? .primary : .secondary)
                .lineLimit(1)
                .truncationMode(.middle)
            if !connected {
                Text("Not connected")
                    .foregroundColor(.secondary)
            }
            Spacer(minLength: 8)
            Text(label)
                .font(.caption)
                .foregroundColor(.secondary)
        }
        .contentShape(Rectangle())
        .onTapGesture {
            if connected {
                NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
            }
        }
        .help(connected ? "\(path)\nClick to show in Finder" : path)
    }

    /// Finder's own icon for the drive or share the folder is on, else for the folder itself.
    static func icon(for path: String) -> NSImage {
        let parts = path.split(separator: "/")
        if parts.first == "Volumes", parts.count >= 2 {
            let volume = "/Volumes/\(parts[1])"
            if FileManager.default.fileExists(atPath: volume) {
                return NSWorkspace.shared.icon(forFile: volume)
            }
        }
        return NSWorkspace.shared.icon(forFile: FileManager.default.fileExists(atPath: path) ? path : "/")
    }

    /// "/Volumes/MusicSSD/ALAC" reads as "MusicSSD › ALAC"; home folders start with "~".
    static func readable(_ path: String) -> String {
        let home = NSHomeDirectory()
        var parts: [String] = []
        var rest = path
        if rest == home || rest.hasPrefix(home + "/") {
            parts = ["~"]
            rest = String(rest.dropFirst(home.count))
        } else if rest.hasPrefix("/Volumes/") {
            rest = String(rest.dropFirst("/Volumes/".count))
        }
        parts += rest.split(separator: "/").map(String.init)
        return parts.joined(separator: " › ")
    }
}

/// Before the folders are chosen: the two folders and the library, in the main window.
private struct SetupView: View {
    @ObservedObject var settings: AppSettings
    let chooseFolder: (FolderKind) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Choose where your FLAC library is and where the ALAC copy should go.")
                .fixedSize(horizontal: false, vertical: true)
            row("FLAC folder", settings.flacFolder) { chooseFolder(.flac) }
            row("ALAC folder", settings.alacFolder) { chooseFolder(.alac) }
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text("Library")
                    .frame(width: 90, alignment: .leading)
                Picker(selection: $settings.library, label: EmptyView()) {
                    ForEach(LibraryChoice.allCases, id: \.self) { choice in
                        Text(choice.title).tag(choice)
                    }
                }
                .fixedSize()
            }
            Text("Jellyfin play counts and lyrics can be set later in Settings.")
                .foregroundColor(.secondary)
        }
    }

    private func row(_ label: String, _ path: String, choose: @escaping () -> Void) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(label)
                .frame(width: 90, alignment: .leading)
            Text(path.isEmpty ? "Not chosen" : FoldersView.readable(path))
                .foregroundColor(.secondary)
                .lineLimit(1)
                .truncationMode(.middle)
                .help(path)
            Spacer()
            Button("Choose…", action: choose)
        }
    }
}

/// A newer Flalac on Codeberg: one quiet line, like a system notice.
private struct UpdateNote: View {
    let version: String
    let download: () -> Void

    var body: some View {
        HStack(alignment: .firstTextBaseline) {
            Text("Flalac \(version) is available.")
            Spacer()
            Button("Download…", action: download)
        }
    }
}

/// Stage, progress bar, "312 of 2,214" and the current song while a sync runs.
private struct ProgressSection: View {
    @ObservedObject var controller: SyncController
    let libraryName: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .firstTextBaseline) {
                Text(title)
                Spacer()
                if let conversion = shownConversion {
                    Text("\(Format.count(conversion.done)) of \(Format.count(conversion.total))")
                        .font(.body.monospacedDigit())
                        .foregroundColor(.secondary)
                }
            }
            if let fraction {
                ProgressView(value: fraction)
                    .progressViewStyle(LinearProgressViewStyle())
            } else {
                ProgressView()
                    .progressViewStyle(LinearProgressViewStyle())
            }
            Text(detail.isEmpty ? " " : detail)
                .font(.callout)
                .foregroundColor(.secondary)
                .lineLimit(1)
                .truncationMode(.middle)
            VStack(alignment: .leading, spacing: 4) {
                ForEach(steps.indices, id: \.self) { index in
                    StepRow(title: steps[index], state: state(of: index))
                }
            }
            .padding(.top, 6)
        }
    }

    private var steps: [String] {
        var names = ["Looking for changes", "Converting"]
        if let libraryName {
            names.append("Updating \(libraryName) and play counts")
        }
        return names
    }

    /// Which step the engine is on: checking 0, converting 1, library 2, done after the last.
    private var current: Int {
        switch controller.stage {
        case "converting": return 1
        case "library": return 2
        case "done": return steps.count
        default: return 0
        }
    }

    private func state(of index: Int) -> StepRow.State {
        index < current ? .done : index == current ? .running : .waiting
    }

    private var shownConversion: ConversionProgress? {
        guard controller.activity == .running, let conversion = controller.conversion,
              conversion.total > 0 else { return nil }
        return conversion
    }

    /// nil shows an indeterminate bar.
    private var fraction: Double? {
        guard let conversion = shownConversion else { return nil }
        return min(1, Double(conversion.done) / Double(conversion.total))
    }

    private var detail: String {
        if controller.activity == .stopping {
            return ""
        }
        if let conversion = shownConversion, !conversion.current.isEmpty {
            return conversion.current
        }
        return controller.stageMessage ?? ""
    }

    private var title: String {
        if controller.activity == .stopping {
            return "Stopping…"
        }
        switch controller.stage {
        case nil:
            return "Starting…"
        case "checking":
            return "Looking for changes…"
        case "converting":
            return "Converting…"
        case "library":
            return libraryName.map { "Updating the \($0) library…" } ?? "Updating the library…"
        case "done":
            return "Finishing…"
        case let other?:
            return other.prefix(1).uppercased() + other.dropFirst() + "…"
        }
    }
}

/// A problem, with the caution sign macOS uses for one.
struct Warning: View {
    let text: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
            Image(systemName: "exclamationmark.triangle.fill")
                .renderingMode(.original)
            Text(text)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

/// One step of a sync: done, running now, or still to come.
private struct StepRow: View {
    enum State { case done, running, waiting }
    let title: String
    let state: State

    var body: some View {
        HStack(spacing: 8) {
            Group {
                switch state {
                case .done:
                    Image(systemName: "checkmark")
                        .font(.callout.weight(.semibold))
                case .running:
                    ProgressView()
                        .scaleEffect(0.5)
                case .waiting:
                    Image(systemName: "circle")
                        .font(.caption2)
                }
            }
            .frame(width: 16, height: 16)
            .foregroundColor(.secondary)
            Text(title)
                .foregroundColor(state == .waiting ? .secondary : .primary)
        }
    }
}

