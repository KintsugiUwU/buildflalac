import SwiftUI

/// What the last sync did, or why it did not finish.
struct SummaryView: View {
    let run: LastRun

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            switch run.outcome {
            case .completed:
                Text(headline)
                if let summary = run.summary {
                    if summary.changedNothing {
                        Text("Everything was already in step.")
                            .foregroundColor(.secondary)
                    } else {
                        counts(summary)
                    }
                    notes(summary)
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
        let date = Format.date(run.finished)
        guard let seconds = run.summary?.seconds, seconds > 0 else {
            return "Last sync: \(date)"
        }
        return "Last sync: \(date), took \(Format.duration(seconds))"
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
        let lines = remarks(summary) + summary.notes
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
