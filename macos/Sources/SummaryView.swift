import SwiftUI

/// What the last sync did, or why it did not finish.
struct SummaryView: View {
    let run: LastRun
    @AppStorage("showDetails") private var showDetails = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            switch run.outcome {
            case .completed:
                if let summary = run.summary {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(summary.errors > 0 || (summary.library?.failed ?? 0) > 0
                             ? "Synced, with problems" : "Up to date")
                            .font(.headline)
                        Text(headline)
                            .foregroundColor(.secondary)
                    }
                    if summary.changedNothing && summary.notes.isEmpty {
                        Text("Nothing new: everything was already in step.")
                            .foregroundColor(.secondary)
                    } else {
                        Changes(lines: changes(summary) + summary.notes.filter(Self.isDone))
                    }
                    notes(summary)
                    DisclosureGroup("Details", isExpanded: $showDetails) {
                        counts(summary)
                            .padding(.top, 6)
                    }
                } else {
                    Text(headline)
                }
            case .failed:
                Warning(text: "Last sync failed: \(Format.date(run.finished))")
                if let message = run.message {
                    Text(message)
                        .foregroundColor(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            case .cancelled:
                Text("Last sync was cancelled: \(Format.date(run.finished))")
                Text("Songs not reached yet are converted at the next sync.")
                    .foregroundColor(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private var headline: String {
        // "Today at 16:10" reads "today at 16:10" in the middle of a sentence
        var date = Format.date(run.finished)
        if date.hasPrefix("Today") || date.hasPrefix("Yesterday") {
            date = date.prefix(1).lowercased() + date.dropFirst()
        }
        guard let seconds = run.summary?.seconds, seconds > 0 else {
            return "Last synced \(date)"
        }
        return "Last synced \(date) · took \(Format.duration(seconds))"
    }

    /// What changed, one plain sentence per kind of change; nothing is said about zeros.
    private func changes(_ summary: SyncSummary) -> [String] {
        func songs(_ count: Int, _ what: String) -> String? {
            count == 0 ? nil : "\(count == 1 ? "1 song" : "\(Format.count(count)) songs") \(what)"
        }
        var lines = [
            songs(summary.converted, "converted"),
            songs(summary.retagged, "updated with new tags"),
            songs(summary.renamed, "renamed"),
            songs(summary.removed, "removed from the ALAC folder"),
        ].compactMap { $0 }
        if let library = summary.library {
            let app = library.app.isEmpty ? "the library" : library.app
            lines += [
                songs(library.added, "added to \(app)"),
                songs(library.removed, "removed from \(app)"),
                songs(library.moved, "re-linked in \(app)"),
                songs(library.refreshed, "refreshed in \(app)"),
                library.plays == 0 ? nil
                    : "\(Format.count(library.plays)) play \(library.plays == 1 ? "count" : "counts") updated in \(app)",
            ].compactMap { $0 }
        }
        return lines
    }

    private func counts(_ summary: SyncSummary) -> some View {
        HStack(alignment: .top, spacing: 40) {
            Counts(title: "ALAC folder", rows: [
                ("Converted", summary.converted),
                ("Retagged", summary.retagged),
                ("Renamed", summary.renamed),
                ("Removed", summary.removed),
                ("Errors", summary.errors),
            ])
            if let library = summary.library {
                Counts(title: library.app.isEmpty ? "Library" : "\(library.app) library", rows: [
                    ("Added", library.added),
                    ("Removed", library.removed),
                    ("Re-pointed", library.moved),
                    ("Refreshed", library.refreshed),
                    ("Play counts set", library.plays),
                ])
            } else {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Library")
                        .fontWeight(.semibold)
                    Text("Not updated")
                        .foregroundColor(.secondary)
                }
            }
        }
    }

    @ViewBuilder private func notes(_ summary: SyncSummary) -> some View {
        let warnings = problems(summary)
        let lines = remarks(summary) + summary.notes.filter { !Self.isDone($0) }
        if !warnings.isEmpty || !lines.isEmpty {
            VStack(alignment: .leading, spacing: 4) {
                ForEach(warnings, id: \.self) { Warning(text: $0) }
                ForEach(lines, id: \.self) { note in
                    Text(note)
                        .foregroundColor(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }

    /// Engine notes like "2 play counts updated in Jellyfin" read as done changes.
    static func isDone(_ note: String) -> Bool {
        note.contains(" updated in ")
    }

    private func problems(_ summary: SyncSummary) -> [String] {
        var lines: [String] = []
        if summary.errors > 0 {
            let songs = summary.errors == 1 ? "1 song could" : "\(Format.count(summary.errors)) songs could"
            lines.append("\(songs) not be converted. Details are in the log.")
        }
        if let library = summary.library, library.failed > 0 {
            let changes = library.failed == 1 ? "1 change" : "\(Format.count(library.failed)) changes"
            lines.append("\(changes) to the \(library.app) library failed. Details are in the log.")
        }
        return lines
    }

    private func remarks(_ summary: SyncSummary) -> [String] {
        var lines: [String] = []
        if summary.heldDeletes > 0 {
            let songs = summary.heldDeletes == 1
                ? "1 song that is gone from the FLAC folder is"
                : "\(Format.count(summary.heldDeletes)) songs that are gone from the FLAC folder are"
            lines.append("\(songs) still on the drive.")
        }
        if summary.unsettled > 0 {
            let songs = summary.unsettled == 1
                ? "1 song was still being written; it is"
                : "\(Format.count(summary.unsettled)) songs were still being written; they are"
            lines.append("\(songs) converted at the next sync.")
        }
        return lines
    }
}

/// A titled column of counts; zeros are dimmed so changes stand out.
private struct Counts: View {
    let title: String
    let rows: [(String, Int)]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title)
                .fontWeight(.semibold)
            HStack(alignment: .top, spacing: 16) {
                VStack(alignment: .leading, spacing: 3) {
                    ForEach(rows.indices, id: \.self) { index in
                        Text(rows[index].0)
                    }
                }
                VStack(alignment: .trailing, spacing: 3) {
                    ForEach(rows.indices, id: \.self) { index in
                        Text(Format.count(rows[index].1))
                            .font(.body.monospacedDigit())
                            .foregroundColor(rows[index].1 == 0 ? .secondary : .primary)
                    }
                }
            }
        }
    }
}

/// Done changes as a short checklist, the way installers and First Aid report what they did.
private struct Changes: View {
    let lines: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            ForEach(lines, id: \.self) { line in
                HStack(alignment: .firstTextBaseline, spacing: 6) {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundColor(.green)
                    Text(line)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
        }
    }
}

