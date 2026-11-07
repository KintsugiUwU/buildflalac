import SwiftUI

/// The main window: the two folders, Sync, progress, the last result and the log.
struct MainView: View {
    @ObservedObject var settings: AppSettings
    @ObservedObject var controller: SyncController
    @ObservedObject var log: LogBuffer
    @AppStorage("showLog") private var showLog = false
    let openSettings: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            FoldersView(settings: settings)
            Divider()
            status
            buttons
            if !log.isEmpty {
                DisclosureGroup("Log", isExpanded: $showLog) {
                    LogView(log: log)
                        .frame(height: 180)
                        .padding(.top, 4)
                }
            }
        }
        .padding(20)
        .frame(width: 480)
        .fixedSize(horizontal: false, vertical: true)
        .alert(item: $controller.pendingDeletes) { pending in
            deletesAlert(pending)
        }
    }

    @ViewBuilder private var status: some View {
        if controller.isRunning {
            ProgressSection(controller: controller, libraryName: settings.library.appName)
        } else if let lastRun = controller.lastRun {
            SummaryView(run: lastRun)
        } else if settings.foldersChosen {
            Text("Not synced yet.")
                .foregroundColor(.secondary)
        } else {
            Text("Choose the FLAC folder and the ALAC folder in \(SettingsName.title) to start.")
                .fixedSize(horizontal: false, vertical: true)
        }
        if !controller.isRunning, let problem = controller.engineProblem {
            Warning(text: problem)
        }
    }

    private var buttons: some View {
        HStack {
            Spacer()
            if !settings.foldersChosen {
                Button("Open \(SettingsName.title)…", action: openSettings)
            } else {
                if controller.isRunning {
                    Button("Cancel") { controller.cancel() }
                        .keyboardShortcut(.cancelAction)
                        .disabled(controller.activity == .stopping)
                }
                Button("Sync") { controller.sync() }
                    .keyboardShortcut(.defaultAction)
                    .disabled(controller.isRunning)
            }
        }
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

    var body: some View {
        VStack(alignment: .leading, spacing: 3) {
            row("FLAC", settings.flacFolder)
            row("ALAC", settings.alacFolder)
        }
        .foregroundColor(.secondary)
    }

    private func row(_ label: String, _ path: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(label)
                .frame(width: 40, alignment: .leading)
            Text(path.isEmpty ? "Not chosen" : path)
                .lineLimit(1)
                .truncationMode(.middle)
                .help(path)
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
        }
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
