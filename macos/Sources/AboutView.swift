import AppKit
import SwiftUI

/// The About window: icon, name, version, author and a button to the source code.
struct AboutView: View {
    let version: String
    let engineVersion: String?

    static let source = URL(string: "https://codeberg.org/KintsugiUwU/flalac")!

    var body: some View {
        VStack(spacing: 10) {
            Image(nsImage: NSApp.applicationIconImage)
                .resizable()
                .frame(width: 96, height: 96)
            Text("Flalac")
                .font(.title2.weight(.semibold))
            Text(versionLine)
                .foregroundColor(.secondary)
            Text("© 2026 Davide Petris")
                .padding(.top, 4)
            Text("GPL-3.0-or-later. Includes FFmpeg (LGPL).")
                .font(.caption)
                .foregroundColor(.secondary)
            Button("Source") {
                NSWorkspace.shared.open(Self.source)
            }
            .padding(.top, 6)
        }
        .padding(24)
        .frame(width: 300)
    }

    private var versionLine: String {
        guard let engineVersion, engineVersion != version else { return "Version \(version)" }
        return "Version \(version) (engine \(engineVersion))"
    }
}
