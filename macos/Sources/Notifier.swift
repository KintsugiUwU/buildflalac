import AppKit
@preconcurrency import UserNotifications

/// Tells the user about a sync that ended while flalac was in the background.
@MainActor
enum Notifier {
    static func syncFinished(_ run: LastRun) {
        guard !NSApp.isActive else { return }
        let body: String
        switch run.outcome {
        case .completed:
            if let summary = run.summary, !summary.changedNothing {
                var parts = ["\(Format.songs(summary.converted)) converted"]
                if let library = summary.library {
                    parts.append("\(Format.count(library.added)) added to \(library.app)")
                    parts.append("\(Format.count(library.plays)) play counts set")
                }
                body = parts.joined(separator: ", ") + "."
            } else {
                body = "Everything was already in step."
            }
        case .failed:
            body = run.message ?? "The sync failed."
        case .cancelled:
            body = "The sync was cancelled."
        }
        post(title: run.outcome == .failed ? "Sync failed" : "Sync finished", body: body)
    }

    static func needsConfirmation(_ pending: PendingDeletes) {
        guard !NSApp.isActive else { return }
        NSApp.requestUserAttention(.informationalRequest)
        post(
            title: "Flalac is waiting for you",
            body: (pending.count == 1 ? "1 song is gone" : "\(Format.count(pending.count)) songs are gone")
                + " from the FLAC folder. Remove them from the drive?"
        )
    }

    private static func post(title: String, body: String) {
        // Notifications need a real app bundle (not a bare binary run from Terminal).
        guard Bundle.main.bundleURL.pathExtension == "app", Bundle.main.bundleIdentifier != nil else {
            return
        }
        // The async calls, not the completion-handler ones: macOS calls those handlers on its own
        // queue, and a closure written here is main-actor code, so Swift 6 stops the app there.
        let center = UNUserNotificationCenter.current()
        Task {
            guard (try? await center.requestAuthorization(options: [.alert])) == true else { return }
            let content = UNMutableNotificationContent()
            content.title = title
            content.body = body
            try? await center.add(
                UNNotificationRequest(identifier: UUID().uuidString, content: content, trigger: nil)
            )
        }
    }
}
