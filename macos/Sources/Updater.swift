import AppKit
import Foundation

/// Looks for a newer Flalac release on Codeberg: once at launch, silently unless there is one,
/// and from "Check for Updates…" in the Flalac menu, which always answers.
@MainActor
final class Updater: ObservableObject {
    struct Release: Equatable {
        let version: String
        let page: URL
    }

    nonisolated static let latestRelease = URL(
        string: "https://codeberg.org/api/v1/repos/KintsugiUwU/flalac/releases/latest")!
    nonisolated static let releases = URL(string: "https://codeberg.org/KintsugiUwU/flalac/releases")!

    /// A release newer than this app, if the last check found one.
    @Published private(set) var available: Release?

    var current: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0"
    }

    func check(answerAlways: Bool = false) {
        var request = URLRequest(url: Self.latestRelease, timeoutInterval: 15)
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        let current = current
        URLSession.shared.dataTask(with: request) { data, response, _ in
            let ok = (response as? HTTPURLResponse)?.statusCode == 200
            let release = ok ? Self.newer(than: current, in: data) : nil
            Task { @MainActor in
                self.available = release
                if answerAlways {
                    self.tell(release, reached: ok)
                }
            }
        }.resume()
    }

    func openDownload() {
        NSWorkspace.shared.open(available?.page ?? Self.releases)
    }

    private func tell(_ release: Release?, reached: Bool) {
        let alert = NSAlert()
        if let release {
            alert.messageText = "Flalac \(release.version) is available."
            alert.informativeText = "You have \(current)."
            alert.addButton(withTitle: "Download…")
            alert.addButton(withTitle: "Later")
            if alert.runModal() == .alertFirstButtonReturn {
                NSWorkspace.shared.open(release.page)
            }
            return
        }
        alert.messageText = reached
            ? "Flalac \(current) is the newest version."
            : "Codeberg could not be reached."
        alert.informativeText = reached ? "" : "Check the connection and try again."
        alert.runModal()
    }

    /// The release in Codeberg's JSON answer, when it is newer than `current`.
    nonisolated static func newer(than current: String, in data: Data?) -> Release? {
        guard
            let data,
            let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
            let tag = json["tag_name"] as? String,
            json["draft"] as? Bool != true,
            json["prerelease"] as? Bool != true
        else { return nil }
        let version = tag.hasPrefix("v") ? String(tag.dropFirst()) : tag
        let page = (json["html_url"] as? String).flatMap(URL.init(string:)) ?? releases
        return isNewer(version, than: current) ? Release(version: version, page: page) : nil
    }

    /// "0.10.1" is newer than "0.9.3": numbers compared part by part.
    nonisolated static func isNewer(_ candidate: String, than current: String) -> Bool {
        let parts = { (text: String) in text.split(separator: ".").map { Int($0) ?? 0 } }
        let a = parts(candidate)
        let b = parts(current)
        for index in 0..<max(a.count, b.count) {
            let x = index < a.count ? a[index] : 0
            let y = index < b.count ? b[index] : 0
            if x != y { return x > y }
        }
        return false
    }
}
