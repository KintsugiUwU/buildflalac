import Foundation

/// Numbers, dates and durations in the user's locale.
@MainActor
enum Format {
    private static let numbers: NumberFormatter = {
        let formatter = NumberFormatter()
        formatter.numberStyle = .decimal
        return formatter
    }()

    private static let dates: DateFormatter = {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .short
        formatter.doesRelativeDateFormatting = true
        return formatter
    }()

    private static let durations: DateComponentsFormatter = {
        let formatter = DateComponentsFormatter()
        formatter.unitsStyle = .abbreviated
        formatter.allowedUnits = [.hour, .minute, .second]
        formatter.maximumUnitCount = 2
        return formatter
    }()

    static func count(_ value: Int) -> String {
        numbers.string(from: NSNumber(value: value)) ?? String(value)
    }

    /// "1 song", "2,214 songs".
    static func songs(_ value: Int) -> String {
        value == 1 ? "1 song" : "\(count(value)) songs"
    }

    static func date(_ date: Date) -> String {
        dates.string(from: date)
    }

    static func duration(_ seconds: Double) -> String {
        durations.string(from: max(1, seconds.rounded())) ?? ""
    }
}

/// "Settings" since macOS 13, "Preferences" before.
enum SettingsName {
    static var title: String {
        if #available(macOS 13, *) {
            return "Settings"
        }
        return "Preferences"
    }
}
