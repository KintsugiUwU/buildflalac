import AppKit
import SwiftUI

enum FolderKind {
    case flac
    case alac
}

/// Settings in three tabs, each a form in the classic two-column layout.
struct SettingsView: View {
    @ObservedObject var settings: AppSettings
    @ObservedObject var tester: JellyfinTester
    @ObservedObject var noLyrics: NoLyricsList
    let chooseFolder: (FolderKind) -> Void
    let addSongsWithoutLyrics: () -> Void

    @AppStorage("settingsTab") private var tab = "general"
    @State private var selectedSong: String?

    var body: some View {
        TabView(selection: $tab) {
            general
                .tabItem { Text("General") }
                .tag("general")
            jellyfin
                .tabItem { Text("Jellyfin") }
                .tag("jellyfin")
            lyrics
                .tabItem { Text("Lyrics") }
                .tag("lyrics")
        }
        .padding(20)
        .frame(width: 620)
        .fixedSize(horizontal: false, vertical: true)
        .onChange(of: settings.jellyfinURL) { _ in tester.reset() }
        .onChange(of: settings.jellyfinUser) { _ in tester.reset() }
        .onChange(of: settings.jellyfinKey) { _ in tester.reset() }
        .onChange(of: settings.jellyfinMusicPath) { _ in tester.reset() }
        .onChange(of: settings.alacFolder) { _ in noLyrics.load(stateFolder: settings.stateFolderURL) }
    }

    // MARK: - General

    private var general: some View {
        Form {
            Row("FLAC folder:") {
                path(settings.flacFolder)
                Button("Choose…") { chooseFolder(.flac) }
            }
            Row("ALAC folder:") {
                path(settings.alacFolder)
                Button("Choose…") { chooseFolder(.alac) }
            }

            Gap()
            Row("Library:") {
                Picker("Library", selection: $settings.library) {
                    ForEach(LibraryChoice.allCases, id: \.self) { choice in
                        Text(choice.title).tag(choice)
                    }
                }
                .labelsHidden()
                .fixedSize()
            }
            Row("") {
                Note(settings.library == .none
                    ? "Only the ALAC folder is updated."
                    : "New, moved and removed songs in the ALAC folder are mirrored in this library.")
            }

            Gap()
            Row("ALAC bit depth:") {
                Picker("ALAC bit depth", selection: $settings.maxBitDepth) {
                    ForEach(BitDepthLimit.allCases, id: \.self) { limit in
                        Text(limit.title).tag(limit)
                    }
                }
                .labelsHidden()
                .fixedSize()
            }
            Row("ALAC sample rate:") {
                Picker("ALAC sample rate", selection: $settings.maxSampleRate) {
                    ForEach(SampleRateLimit.allCases, id: \.self) { limit in
                        Text(limit.title).tag(limit)
                    }
                }
                .labelsHidden()
                .fixedSize()
            }
            Row("") {
                Note("Changing this converts every song again.")
            }
        }
        .padding(20)
    }

    // MARK: - Jellyfin

    private var jellyfin: some View {
        Form {
            Row("Address:") {
                TextField("Address", text: $settings.jellyfinURL)
                    .labelsHidden()
                    .disableAutocorrection(true)
            }
            Row("User:") {
                TextField("User", text: $settings.jellyfinUser)
                    .labelsHidden()
                    .disableAutocorrection(true)
            }
            Row("API key:") {
                SecureField("API key", text: Binding(
                    get: { settings.jellyfinKey },
                    set: { settings.editKey($0) }
                ))
                .labelsHidden()
            }
            if let problem = settings.keyProblem {
                Row("") {
                    Warning(text: problem)
                }
            }

            Gap()
            Row("FLAC folder path:") {
                TextField("FLAC folder path", text: $settings.jellyfinMusicPath)
                    .labelsHidden()
                    .disableAutocorrection(true)
            }
            Row("") {
                Note("As Jellyfin sees it, for example inside its container. "
                    + "Used to match songs for play counts.")
            }

            Gap()
            Row("") {
                Button("Test") { tester.test(settings) }
                    .disabled(settings.jellyfinAccount == nil || settings.jellyfinKey.isEmpty
                        || tester.state == .testing)
                testResult
                Spacer(minLength: 0)
            }
            Row("") {
                Note("Play counts are synced with Jellyfin when the address, user and key are set. "
                    + "The key is kept in this Mac’s Keychain.")
            }
        }
        .padding(20)
    }

    @ViewBuilder private var testResult: some View {
        switch tester.state {
        case .idle:
            EmptyView()
        case .testing:
            ProgressView()
                .controlSize(.small)
        case .passed(let songs, let plays):
            Text(Self.passedText(songs: songs, plays: plays))
                .fixedSize(horizontal: false, vertical: true)
        case .failed(let message):
            Warning(text: message)
        }
    }

    private static func passedText(songs: Int?, plays: Int?) -> String {
        var parts: [String] = []
        if let songs {
            parts.append(Format.songs(songs))
        }
        if let plays {
            parts.append(plays == 1 ? "1 play" : "\(Format.count(plays)) plays")
        }
        return parts.isEmpty ? "Connected." : "Connected: \(parts.joined(separator: ", "))."
    }

    // MARK: - Lyrics

    private var lyrics: some View {
        Form {
            Row("Lyrics:") {
                Toggle("Get lyrics from LRCLIB", isOn: $settings.lyricsEnabled)
            }
            Row("Style:") {
                Picker("Style", selection: $settings.lyricsStyle) {
                    ForEach(LyricsStyle.allCases, id: \.self) { style in
                        Text(style.title).tag(style)
                    }
                }
                .pickerStyle(RadioGroupPickerStyle())
                .horizontalRadioGroupLayout()
                .labelsHidden()
                .fixedSize()
            }
            .disabled(!settings.lyricsEnabled)

            Gap()
            Row("Songs without lyrics:") {
                VStack(alignment: .leading, spacing: 0) {
                    List(selection: $selectedSong) {
                        ForEach(noLyrics.entries, id: \.self) { entry in
                            Text(entry)
                                .lineLimit(1)
                                .truncationMode(.middle)
                                .help(entry)
                                .tag(entry)
                        }
                    }
                    .frame(height: 120)
                    .border(Color(NSColor.separatorColor))
                    .onDeleteCommand(perform: removeSelectedSong)
                    AddRemoveButtons(
                        canAdd: !settings.flacFolder.isEmpty && noLyrics.fileURL != nil,
                        canRemove: selectedSong != nil,
                        add: addSongsWithoutLyrics,
                        remove: removeSelectedSong
                    )
                    .fixedSize()
                }
            }
            .disabled(noLyrics.fileURL == nil)
            if let problem = noLyrics.problem {
                Row("") {
                    Warning(text: problem)
                }
            }
            Row("") {
                Note(noLyrics.fileURL == nil
                    ? "Choose the ALAC folder first."
                    : "Instrumental versions that LRCLIB has words for. "
                        + "Saved with Flalac's state on the drive, next to the ALAC folder.")
                    .help(noLyrics.fileURL?.path ?? "")
            }
        }
        .padding(20)
    }

    private func removeSelectedSong() {
        guard let selectedSong else { return }
        noLyrics.remove(selectedSong)
        self.selectedSong = nil
    }

    // MARK: -

    private func path(_ path: String) -> some View {
        HStack(spacing: 8) {
            Text(path.isEmpty ? "Not chosen" : path)
                .foregroundColor(path.isEmpty ? .secondary : .primary)
                .lineLimit(1)
                .truncationMode(.middle)
                .help(path)
            Spacer(minLength: 0)
        }
    }
}

/// A label in the right-aligned left column and its controls on the right.
private struct Row<Content: View>: View {
    let label: String
    let content: Content

    init(_ label: String, @ViewBuilder content: () -> Content) {
        self.label = label
        self.content = content()
    }

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Text(label)
                .frame(width: 150, alignment: .trailing)
            content
        }
    }
}

private struct Note: View {
    let text: String

    init(_ text: String) {
        self.text = text
    }

    var body: some View {
        Text(text)
            .font(.callout)
            .foregroundColor(.secondary)
            .fixedSize(horizontal: false, vertical: true)
    }
}

private struct Gap: View {
    var body: some View {
        Spacer().frame(height: 6)
    }
}

/// The standard + and − buttons under a list.
private struct AddRemoveButtons: NSViewRepresentable {
    var canAdd: Bool
    var canRemove: Bool
    var add: () -> Void
    var remove: () -> Void

    @MainActor
    final class Coordinator: NSObject {
        var parent: AddRemoveButtons

        init(_ parent: AddRemoveButtons) {
            self.parent = parent
        }

        @objc func clicked(_ sender: NSSegmentedControl) {
            if sender.selectedSegment == 0 {
                parent.add()
            } else {
                parent.remove()
            }
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    func makeNSView(context: Context) -> NSSegmentedControl {
        let images = [NSImage.addTemplateName, NSImage.removeTemplateName].compactMap { NSImage(named: $0) }
        let control = NSSegmentedControl(
            images: images,
            trackingMode: .momentary,
            target: context.coordinator,
            action: #selector(Coordinator.clicked(_:))
        )
        control.segmentStyle = .smallSquare
        control.setToolTip("Add songs", forSegment: 0)
        control.setToolTip("Remove the selected song", forSegment: 1)
        return control
    }

    func updateNSView(_ control: NSSegmentedControl, context: Context) {
        context.coordinator.parent = self
        control.setEnabled(canAdd, forSegment: 0)
        control.setEnabled(canRemove, forSegment: 1)
    }
}
