import AppKit
import Combine
import SwiftUI

// MARK: - The calendar

/// A day or period the main window is decorated for.
enum Festivity: String, CaseIterable, Sendable {
    case christmas
    case newYear
    case easter
    case halloween
    case spring
    case summer
    case autumn
    case winter
    case carnival
    case valentine
    case lunarNewYear
    case eid
    case earthDay
    case deadDay

    var title: String {
        switch self {
        case .christmas: return "Christmas"
        case .newYear: return "New Year"
        case .easter: return "Easter"
        case .halloween: return "Halloween"
        case .spring: return "First day of spring"
        case .summer: return "First day of summer"
        case .autumn: return "First day of autumn"
        case .winter: return "First day of winter"
        case .carnival: return "Carnival"
        case .valentine: return "Valentine's Day"
        case .lunarNewYear: return "Lunar New Year"
        case .eid: return "Eid al-Fitr"
        case .earthDay: return "Earth Day"
        case .deadDay: return "Día de los Muertos"
        }
    }

    /// The decoration for a day, if any. A season's first day wins over the period around it
    /// (the first day of winter falls in the Christmas weeks), New Year over Christmas.
    static func on(_ date: Date, calendar: Calendar = .current) -> Festivity? {
        let parts = calendar.dateComponents([.year, .month, .day], from: date)
        guard let year = parts.year, let month = parts.month, let day = parts.day else {
            return nil
        }
        let today = calendar.startOfDay(for: date)
        for season in [Festivity.spring, .summer, .autumn, .winter] {
            if let first = season.firstDay(of: year, calendar: calendar), first == today {
                return season
            }
        }
        // Short holidays first: they win over the longer periods they can fall in
        if (month == 12 && day == 31) || (month == 1 && day == 1) {
            return .newYear
        }
        if month == 2 && day == 14 {
            return .valentine
        }
        if month == 4 && day == 22 {
            return .earthDay
        }
        if isEid(date) {
            return .eid
        }
        if isLunarNewYear(date) {
            return .lunarNewYear
        }
        if let sunday = easterSunday(year, calendar: calendar) {
            func around(_ from: Int, _ to: Int) -> Bool {
                guard let first = calendar.date(byAdding: .day, value: from, to: sunday),
                      let last = calendar.date(byAdding: .day, value: to, to: sunday) else { return false }
                return today >= first && today <= last
            }
            if around(-52, -47) {  // Giovedì grasso to Martedì grasso
                return .carnival
            }
            if around(-2, 1) {  // Good Friday to Easter Monday
                return .easter
            }
        }
        if month == 11 && day <= 2 {
            return .deadDay
        }
        if month == 12 || (month == 1 && day <= 6) {
            return .christmas
        }
        if month == 10 && day >= 25 {
            return .halloween
        }
        return nil
    }

    /// The first three days of Shawwal, in the Umm al-Qura calendar.
    static func isEid(_ date: Date) -> Bool {
        let islamic = Calendar(identifier: .islamicUmmAlQura)
        let parts = islamic.dateComponents([.month, .day], from: date)
        return parts.month == 10 && (parts.day ?? 0) <= 3
    }

    /// The first three days of the first month of the Chinese year.
    static func isLunarNewYear(_ date: Date) -> Bool {
        let chinese = Calendar(identifier: .chinese)
        let parts = chinese.dateComponents([.month, .day], from: date)
        return parts.month == 1 && parts.isLeapMonth != true && (parts.day ?? 0) <= 3
    }

    /// When the decoration shows in a year, for the preview menu.
    func dates(in year: Int, calendar: Calendar = .current) -> String {
        let format = DateFormatter()
        format.calendar = calendar
        format.setLocalizedDateFormatFromTemplate("d MMM")
        switch self {
        case .christmas: return "1 Dec – 6 Jan"
        case .newYear: return "31 Dec – 1 Jan"
        case .halloween: return "25 – 31 Oct"
        case .easter:
            guard let sunday = Self.easterSunday(year, calendar: calendar),
                  let friday = calendar.date(byAdding: .day, value: -2, to: sunday),
                  let monday = calendar.date(byAdding: .day, value: 1, to: sunday) else { return "?" }
            return "\(format.string(from: friday)) – \(format.string(from: monday))"
        case .spring, .summer, .autumn, .winter:
            guard let day = firstDay(of: year, calendar: calendar) else { return "?" }
            return format.string(from: day)
        case .valentine: return "14 Feb"
        case .earthDay: return "22 Apr"
        case .deadDay: return "1 – 2 Nov"
        case .carnival:
            guard let sunday = Self.easterSunday(year, calendar: calendar),
                  let thursday = calendar.date(byAdding: .day, value: -52, to: sunday),
                  let tuesday = calendar.date(byAdding: .day, value: -47, to: sunday) else { return "?" }
            return "\(format.string(from: thursday)) – \(format.string(from: tuesday))"
        case .eid, .lunarNewYear:
            // Search the year for the first day; only the preview menu asks
            guard var day = calendar.date(from: DateComponents(year: year, month: 1, day: 1)) else {
                return "?"
            }
            var found: [Date] = []
            while calendar.component(.year, from: day) == year {
                let match = self == .eid ? Self.isEid(day) : Self.isLunarNewYear(day)
                if match { found.append(day) }
                guard let next = calendar.date(byAdding: .day, value: 1, to: day) else { break }
                day = next
            }
            guard let first = found.first, let last = found.last else { return "not this year" }
            return "\(format.string(from: first)) – \(format.string(from: last))"
        }
    }

    /// The local day of the equinox or solstice that starts this season (astronomical seasons,
    /// northern hemisphere).
    func firstDay(of year: Int, calendar: Calendar = .current) -> Date? {
        let index: Int
        switch self {
        case .spring: index = 0
        case .summer: index = 1
        case .autumn: index = 2
        case .winter: index = 3
        default: return nil
        }
        return calendar.startOfDay(for: Self.equinoxOrSolstice(year: year, index: index))
    }

    /// Easter Sunday in the Gregorian calendar (the anonymous Gregorian algorithm).
    static func easterSunday(_ year: Int, calendar: Calendar = .current) -> Date? {
        let a = year % 19
        let b = year / 100
        let c = year % 100
        let d = b / 4
        let e = b % 4
        let f = (b + 8) / 25
        let g = (b - f + 1) / 3
        let h = (19 * a + b - d - g + 15) % 30
        let i = c / 4
        let k = c % 4
        let l = (32 + 2 * e + 2 * i - h - k) % 7
        let m = (a + 11 * h + 22 * l) / 451
        let month = (h + l - 7 * m + 114) / 31
        let day = (h + l - 7 * m + 114) % 31 + 1
        return calendar.date(from: DateComponents(year: year, month: month, day: day))
    }

    /// The moment of the March equinox (0), June solstice (1), September equinox (2) or
    /// December solstice (3): Meeus, Astronomical Algorithms, chapter 27. Within a minute or
    /// two for the years 2000–3000, plenty to name the day.
    static func equinoxOrSolstice(year: Int, index: Int) -> Date {
        let mean: [[Double]] = [
            [2451623.80984, 365242.37404, 0.05169, -0.00411, -0.00057],
            [2451716.56767, 365241.62603, 0.00325, 0.00888, -0.00030],
            [2451810.21715, 365242.01767, -0.11575, 0.00337, 0.00078],
            [2451900.05952, 365242.74049, -0.06223, -0.00823, 0.00032],
        ]
        let terms: [(Double, Double, Double)] = [
            (485, 324.96, 1934.136), (203, 337.23, 32964.467), (199, 342.08, 20.186),
            (182, 27.85, 445267.112), (156, 73.14, 45036.886), (136, 171.52, 22518.443),
            (77, 222.54, 65928.934), (74, 296.72, 3034.906), (70, 243.58, 9037.513),
            (58, 119.81, 33718.147), (52, 297.17, 150.678), (50, 21.02, 2281.226),
            (45, 247.54, 29929.562), (44, 325.15, 31555.956), (29, 60.93, 4443.417),
            (18, 155.12, 67555.328), (17, 288.79, 4562.452), (16, 198.04, 62894.029),
            (14, 199.76, 31436.921), (12, 95.39, 14577.848), (12, 287.11, 31931.756),
            (12, 320.81, 34777.259), (9, 227.73, 1222.114), (8, 15.45, 16859.074),
        ]
        let y = Double(year - 2000) / 1000
        let c = mean[index]
        let jde0 = c[0] + c[1] * y + c[2] * y * y + c[3] * pow(y, 3) + c[4] * pow(y, 4)
        let t = (jde0 - 2451545.0) / 36525
        let w = (35999.373 * t - 2.47) * .pi / 180
        let dl = 1 + 0.0334 * cos(w) + 0.0007 * cos(2 * w)
        var s = 0.0
        for (a, b, cc) in terms {
            s += a * cos((b + cc * t) * .pi / 180)
        }
        let jde = jde0 + 0.00001 * s / dl - 69.0 / 86400  // TT to UTC, near enough
        return Date(timeIntervalSince1970: (jde - 2440587.5) * 86400)
    }
}

/// Which decoration the window shows: the setting, the preview menu of test builds, the date.
enum Decorations {
    static let enabledKey = "decorations"
    static let previewKey = "decorationPreview"  // "" automatic, "none", or a Festivity
    static let automatic = ""
    static let none = "none"

    static func current(enabled: Bool, preview: String, date: Date = Date()) -> Festivity? {
        #if FLALAC_PREVIEW
        if preview == none { return nil }
        if let chosen = Festivity(rawValue: preview) { return chosen }
        #endif
        return enabled ? Festivity.on(date) : nil
    }
}

// MARK: - The window's decoration

/// Drawn behind (falling things) and on top of (edges) the main window's content. It never
/// takes clicks, and with "Reduce motion" on everything stands still.
struct FestiveBackground: View {
    let festivity: Festivity
    private var still: Bool { NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }

    var body: some View {
        GeometryReader { space in
            ZStack {
                switch festivity {
                case .christmas, .winter:
                    Falling(kind: .snow, count: 18, size: space.size, still: still)
                case .newYear:
                    Falling(kind: .confetti, count: 26, size: space.size, still: still)
                case .spring:
                    Falling(kind: .petal, count: 14, size: space.size, still: still)
                case .autumn:
                    Falling(kind: .leaf, count: 14, size: space.size, still: still)
                case .halloween:
                    Bats(size: space.size, still: still)
                case .summer:
                    SunRays(still: still)
                        .frame(width: 220, height: 220)
                        .position(x: space.size.width - 10, y: 10)
                case .easter:
                    Bunny(size: space.size, still: still)
                case .carnival:
                    Falling(kind: .confetti, count: 30, size: space.size, still: still)
                case .valentine:
                    Falling(kind: .heart, count: 12, size: space.size, still: still, rising: true)
                case .lunarNewYear:
                    Falling(kind: .envelope, count: 7, size: space.size, still: still)
                case .eid:
                    Stars(size: space.size, still: still)
                case .earthDay:
                    Falling(kind: .greenLeaf, count: 14, size: space.size, still: still)
                case .deadDay:
                    Falling(kind: .marigold, count: 16, size: space.size, still: still)
                }
            }
        }
        .clipped()
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

struct FestiveForeground: View {
    let festivity: Festivity
    private var still: Bool { NSWorkspace.shared.accessibilityDisplayShouldReduceMotion }

    var body: some View {
        GeometryReader { space in
            switch festivity {
            case .christmas:
                FairyLights(width: space.size.width, still: still)
            case .easter:
                EasterEdges(size: space.size, still: still)
            case .halloween:
                HalloweenEdges(size: space.size, still: still)
            case .carnival:
                CarnivalEdges(size: space.size, still: still)
            case .lunarNewYear:
                Lanterns(size: space.size, still: still)
            case .eid:
                Drawing(name: "crescent")
                    .frame(width: 34, height: 34)
                    .position(x: space.size.width - 30, y: 24)
            case .earthDay:
                EarthEdges(size: space.size, still: still)
            case .deadDay:
                DeadEdges(size: space.size, still: still)
            default:
                EmptyView()
            }
        }
        .allowsHitTesting(false)
        .accessibilityHidden(true)
    }
}

// MARK: - Christmas lights

/// A string of bulbs along the top edge that glow in turn, slowly.
private struct FairyLights: View {
    let width: CGFloat
    let still: Bool
    @State private var tick = 0
    private let timer = Timer.publish(every: 0.9, on: .main, in: .common).autoconnect()
    private static let colors: [Color] = [
        Color(red: 0.95, green: 0.25, blue: 0.25),
        Color(red: 1.0, green: 0.78, blue: 0.2),
        Color(red: 0.25, green: 0.75, blue: 0.35),
        Color(red: 0.3, green: 0.55, blue: 1.0),
    ]

    var body: some View {
        let count = max(4, Int(width / 34))
        let step = width / CGFloat(count)
        ZStack(alignment: .topLeading) {
            Wire(count: count, sag: 5)
                .stroke(Color.primary.opacity(0.35), lineWidth: 1)
                .frame(width: width, height: 14)
            ForEach(0..<count, id: \.self) { index in
                let color = Self.colors[index % Self.colors.count]
                let lit = still || (index + tick) % 3 != 0
                Capsule()
                    .fill(color.opacity(lit ? 1 : 0.35))
                    .frame(width: 6, height: 10)
                    .shadow(color: color.opacity(lit ? 0.8 : 0), radius: lit ? 4 : 0)
                    .position(x: step * (CGFloat(index) + 0.5), y: 5 + Wire.drop(at: CGFloat(index) + 0.5, sag: 5) + 5)
            }
        }
        .frame(width: width, height: 22, alignment: .topLeading)
        .onReceive(timer) { _ in
            guard !still else { return }
            withAnimation(.easeInOut(duration: 0.6)) { tick += 1 }
        }
    }
}

/// The wire, dipping a little between hooks.
private struct Wire: Shape {
    let count: Int
    let sag: CGFloat

    /// How far the wire hangs at a position measured in bulbs (hooks fall on whole numbers).
    static func drop(at position: CGFloat, sag: CGFloat) -> CGFloat {
        let fraction = position - floor(position)
        return sag * 4 * fraction * (1 - fraction)
    }

    func path(in rect: CGRect) -> Path {
        var path = Path()
        let step = rect.width / CGFloat(count)
        path.move(to: CGPoint(x: 0, y: 4))
        for index in 0..<count {
            let start = step * CGFloat(index)
            path.addQuadCurve(
                to: CGPoint(x: start + step, y: 4),
                control: CGPoint(x: start + step / 2, y: 4 + sag * 2)
            )
        }
        return path
    }
}

// MARK: - Motion

/// Redraws its content 30 times a second with the seconds since it appeared. Positions are
/// worked out from that time, so things loop cleanly (a flake that reaches the bottom starts
/// again at the top) instead of relying on repeating animations. Still with Reduce motion.
private struct Ticking<Content: View>: View {
    let still: Bool
    let content: (Double) -> Content
    @State private var start = Date()
    @State private var now = Date()
    private let timer = Timer.publish(every: 1.0 / 30, on: .main, in: .common).autoconnect()

    init(still: Bool, @ViewBuilder content: @escaping (Double) -> Content) {
        self.still = still
        self.content = content
    }

    var body: some View {
        content(still ? 0 : now.timeIntervalSince(start))
            .onReceive(timer) { date in
                if !still { now = date }
            }
    }
}

/// The fraction of a loop of `duration` seconds reached at `time`, starting at `phase`.
private func loop(_ time: Double, every duration: Double, phase: Double = 0) -> Double {
    let value = (time / duration + phase).truncatingRemainder(dividingBy: 1)
    return value < 0 ? value + 1 : value
}

// MARK: - Falling things

private enum FallingKind {
    case snow, confetti, petal, leaf, greenLeaf, marigold, heart, envelope
}

/// Flakes, confetti, petals or leaves drifting down behind the content, top to bottom.
private struct Falling: View {
    let kind: FallingKind
    let count: Int
    let size: CGSize
    let still: Bool
    var rising = false  // bottom to top (hearts)
    @State private var seeds: [FallSeed] = []

    var body: some View {
        Ticking(still: still) { time in
            ZStack {
                ForEach(seeds) { seed in
                    FallingPiece(kind: kind, seed: seed)
                        .rotationEffect(.degrees(spins ? (still ? seed.spin / 4 : time * seed.spin / seed.duration) : 0))
                        .position(position(of: seed, at: time))
                }
            }
        }
        .onAppear {
            if seeds.isEmpty {
                seeds = (0..<count).map { FallSeed(id: $0) }
            }
        }
    }

    /// Hearts and envelopes stay upright; flakes, petals and leaves turn as they fall.
    private var spins: Bool { kind != .heart && kind != .envelope }

    private func position(of seed: FallSeed, at time: Double) -> CGPoint {
        let height = Double(size.height) + 40
        var fall = still ? seed.phase : loop(time, every: seed.duration, phase: seed.phase)
        if rising { fall = 1 - fall }
        let sway = still ? 0 : sin(time * 2 * .pi / seed.swayPeriod + seed.phase * 6) * Double(seed.sway)
        return CGPoint(x: seed.x * size.width + CGFloat(sway), y: CGFloat(fall * height - 20))
    }
}

private struct FallSeed: Identifiable {
    let id: Int
    let x = CGFloat.random(in: 0...1)
    let scale = CGFloat.random(in: 0.6...1.2)
    let duration = Double.random(in: 8...15)  // seconds from the top to the bottom
    let phase = Double.random(in: 0..<1)  // where in its fall it starts: the window is full at once
    let sway = CGFloat.random(in: 8...22)
    let swayPeriod = Double.random(in: 3...6)
    let spin = Double.random(in: 90...360) * (Bool.random() ? 1 : -1)  // degrees per fall
    let hue = Int.random(in: 0..<5)
}

private struct FallingPiece: View {
    let kind: FallingKind
    let seed: FallSeed

    var body: some View {
        piece.scaleEffect(seed.scale)
    }

    @ViewBuilder private var piece: some View {
        switch kind {
        case .snow:
            Circle()
                .fill(Color(red: 0.75, green: 0.85, blue: 1.0).opacity(0.75))
                .frame(width: 6, height: 6)
        case .confetti:
            let colors: [Color] = [.red, .orange, .yellow, .green, .blue]
            Rectangle()
                .fill(colors[seed.hue].opacity(0.8))
                .frame(width: 4, height: 8)
        case .petal:
            let colors: [Color] = [
                Color(red: 1.0, green: 0.75, blue: 0.82), Color(red: 1.0, green: 0.85, blue: 0.9),
                Color(red: 0.98, green: 0.68, blue: 0.78), .white, Color(red: 1.0, green: 0.8, blue: 0.86),
            ]
            Ellipse()
                .fill(colors[seed.hue].opacity(0.85))
                .frame(width: 7, height: 10)
        case .leaf:
            let colors: [Color] = [
                Color(red: 0.85, green: 0.35, blue: 0.1), Color(red: 0.9, green: 0.6, blue: 0.1),
                Color(red: 0.7, green: 0.25, blue: 0.1), Color(red: 0.8, green: 0.5, blue: 0.15),
                Color(red: 0.6, green: 0.4, blue: 0.1),
            ]
            Leaf()
                .fill(colors[seed.hue].opacity(0.85))
                .frame(width: 10, height: 14)
        case .greenLeaf:
            let colors: [Color] = [
                Color(red: 0.3, green: 0.65, blue: 0.25), Color(red: 0.45, green: 0.75, blue: 0.3),
                Color(red: 0.2, green: 0.55, blue: 0.3), Color(red: 0.55, green: 0.8, blue: 0.35),
                Color(red: 0.35, green: 0.6, blue: 0.2),
            ]
            Leaf()
                .fill(colors[seed.hue].opacity(0.8))
                .frame(width: 10, height: 14)
        case .marigold:
            let colors: [Color] = [
                Color(red: 1.0, green: 0.55, blue: 0.0), Color(red: 1.0, green: 0.7, blue: 0.1),
                Color(red: 0.95, green: 0.45, blue: 0.05), Color(red: 1.0, green: 0.62, blue: 0.05),
                Color(red: 0.98, green: 0.78, blue: 0.2),
            ]
            Ellipse()
                .fill(colors[seed.hue].opacity(0.85))
                .frame(width: 7, height: 10)
        case .heart:
            Drawing(name: "heart")
                .frame(width: 14, height: 14)
                .opacity(0.7)
        case .envelope:
            Drawing(name: "envelope")
                .frame(width: 16, height: 16)
                .opacity(0.85)
        }
    }
}

private struct Leaf: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.midX, y: rect.minY))
        path.addQuadCurve(to: CGPoint(x: rect.midX, y: rect.maxY), control: CGPoint(x: rect.maxX + 2, y: rect.midY))
        path.addQuadCurve(to: CGPoint(x: rect.midX, y: rect.minY), control: CGPoint(x: rect.minX - 2, y: rect.midY))
        return path
    }
}

// MARK: - Summer sun

private struct SunRays: View {
    let still: Bool
    @State private var turned = false

    var body: some View {
        ZStack {
            ForEach(0..<12, id: \.self) { index in
                Capsule()
                    .fill(Color(red: 1.0, green: 0.8, blue: 0.2).opacity(0.28))
                    .frame(width: 6, height: 70)
                    .offset(y: -78)
                    .rotationEffect(.degrees(Double(index) * 30))
            }
            Circle()
                .fill(Color(red: 1.0, green: 0.82, blue: 0.25).opacity(0.5))
                .frame(width: 80, height: 80)
        }
        .rotationEffect(.degrees(turned ? 30 : 0))
        .onAppear {
            guard !still else { return }
            withAnimation(.linear(duration: 20).repeatForever(autoreverses: false)) { turned = true }
        }
    }
}

// MARK: - Easter eggs

private struct Eggs: View {
    let still: Bool
    @State private var wobble = false
    private static let colors: [(Color, Color)] = [
        (Color(red: 0.98, green: 0.7, blue: 0.75), Color(red: 0.85, green: 0.35, blue: 0.5)),
        (Color(red: 0.7, green: 0.85, blue: 0.98), Color(red: 0.3, green: 0.5, blue: 0.85)),
        (Color(red: 0.99, green: 0.9, blue: 0.55), Color(red: 0.9, green: 0.6, blue: 0.15)),
    ]

    var body: some View {
        HStack(alignment: .bottom, spacing: 6) {
            ForEach(0..<3, id: \.self) { index in
                let colors = Self.colors[index]
                ZStack {
                    Ellipse().fill(colors.0)
                    Rectangle().fill(colors.1).frame(height: 3).offset(y: -3)
                    Rectangle().fill(colors.1.opacity(0.6)).frame(height: 2).offset(y: 4)
                }
                .clipShape(Ellipse())
                .frame(width: 18, height: 24)
                .rotationEffect(.degrees(wobble ? (index.isMultiple(of: 2) ? 8 : -8) : 0), anchor: .bottom)
            }
        }
        .onAppear {
            guard !still else { return }
            withAnimation(.easeInOut(duration: 1.4).repeatForever(autoreverses: true)) { wobble = true }
        }
    }
}

// MARK: - Halloween

/// Drawings from Noto Emoji (Google, Apache License 2.0), kept as PDFs in the app's
/// Resources/Festive folder; see Resources/Festive/LICENSE.
@MainActor
private enum Artwork {
    private static var loaded: [String: NSImage] = [:]

    static func image(_ name: String) -> NSImage? {
        if let image = loaded[name] { return image }
        guard let url = Bundle.main.url(forResource: name, withExtension: "pdf"),
              let image = NSImage(contentsOf: url) else { return nil }
        loaded[name] = image
        return image
    }
}

private struct Drawing: View {
    let name: String

    var body: some View {
        if let image = Artwork.image(name) {
            Image(nsImage: image)
                .resizable()
                .aspectRatio(contentMode: .fit)
        }
    }
}

/// Pumpkins in the corner, a ghost floating, a spider on its thread.
private struct HalloweenEdges: View {
    let size: CGSize
    let still: Bool

    var body: some View {
        Ticking(still: still) { time in
            ZStack {
                HStack(alignment: .bottom, spacing: 2) {
                    Drawing(name: "pumpkin").frame(width: 34, height: 34)
                    Drawing(name: "pumpkin").frame(width: 24, height: 24)
                }
                .position(x: size.width - 40, y: size.height - 20)
                Drawing(name: "ghost")
                    .frame(width: 30, height: 30)
                    .opacity(0.9)
                    .position(x: 30, y: size.height - 26 + CGFloat(sin(time * 1.3) * 5))
                let thread = 26 + CGFloat((1 - cos(time * 0.6)) * 14)
                Path { path in
                    path.move(to: CGPoint(x: size.width - 70, y: 0))
                    path.addLine(to: CGPoint(x: size.width - 70, y: thread))
                }
                .stroke(Color.secondary.opacity(0.6), lineWidth: 0.7)
                Drawing(name: "spider")
                    .frame(width: 20, height: 20)
                    .position(x: size.width - 70, y: thread + 8)
            }
        }
    }
}

/// Bats crossing the window behind the content, left to right, flapping.
private struct Bats: View {
    let size: CGSize
    let still: Bool

    var body: some View {
        Ticking(still: still) { time in
            ZStack {
                ForEach(0..<3, id: \.self) { index in
                    let duration = 10 + Double(index) * 3
                    let across = still ? 0.25 + 0.25 * Double(index) : loop(time, every: duration, phase: Double(index) * 0.37)
                    let flap = still ? 1 : 0.55 + 0.45 * abs(sin(time * 7 + Double(index)))
                    Drawing(name: "bat")
                        .frame(width: 26, height: 26)
                        .scaleEffect(x: 1, y: CGFloat(flap))
                        .opacity(0.8)
                        .position(
                            x: CGFloat(across) * (size.width + 60) - 30,
                            y: size.height * (0.2 + 0.25 * CGFloat(index)) + CGFloat(sin(time * 1.5 + Double(index)) * 6)
                        )
                }
            }
        }
    }
}

// MARK: - Easter

/// Painted eggs with a chick bottom right, tulips bottom left.
private struct EasterEdges: View {
    let size: CGSize
    let still: Bool

    var body: some View {
        ZStack {
            HStack(alignment: .bottom, spacing: 4) {
                Drawing(name: "chick").frame(width: 26, height: 26)
                Eggs(still: still)
            }
            .position(x: size.width - 70, y: size.height - 16)
            Ticking(still: still) { time in
                HStack(alignment: .bottom, spacing: -4) {
                    ForEach(0..<3, id: \.self) { index in
                        Drawing(name: "tulip")
                            .frame(width: 22, height: 22)
                            .rotationEffect(
                                .degrees(sin(time * 1.1 + Double(index)) * 5),
                                anchor: .bottom
                            )
                    }
                }
            }
            .position(x: 40, y: size.height - 14)
        }
    }
}

/// A bunny hopping along the bottom, right to left (the way it faces), behind the content.
private struct Bunny: View {
    let size: CGSize
    let still: Bool

    var body: some View {
        Ticking(still: still) { time in
            let across = still ? 0.5 : loop(time, every: 16, phase: 0.3)
            let hop = still ? 0 : abs(sin(time * .pi * 1.6)) * 16
            Drawing(name: "rabbit")
                .frame(width: 28, height: 28)
                .opacity(0.85)
                .position(
                    x: size.width + 30 - CGFloat(across) * (size.width + 60),
                    y: size.height - 50 - CGFloat(hop)
                )
        }
    }
}

// MARK: - Carnival

/// Masks top left and a party popper top right, rocking a little.
private struct CarnivalEdges: View {
    let size: CGSize
    let still: Bool

    var body: some View {
        Ticking(still: still) { time in
            ZStack {
                Drawing(name: "masks")
                    .frame(width: 30, height: 30)
                    .rotationEffect(.degrees(-12 + sin(time * 1.2) * 6))
                    .position(x: 22, y: 20)
                Drawing(name: "popper")
                    .frame(width: 28, height: 28)
                    .rotationEffect(.degrees(sin(time * 1.5 + 1) * 6))
                    .position(x: size.width - 22, y: 20)
            }
        }
    }
}

// MARK: - Lunar New Year

/// Red lanterns hanging from the top corners, swinging gently.
private struct Lanterns: View {
    let size: CGSize
    let still: Bool

    var body: some View {
        Ticking(still: still) { time in
            ZStack {
                lantern(at: 18, thread: 4, time: time, phase: 0)
                lantern(at: 46, thread: 14, time: time, phase: 1.3)
                lantern(at: size.width - 22, thread: 8, time: time, phase: 2.1)
            }
        }
    }

    private func lantern(at x: CGFloat, thread: CGFloat, time: Double, phase: Double) -> some View {
        VStack(spacing: 0) {
            Rectangle()
                .fill(Color.secondary.opacity(0.6))
                .frame(width: 1, height: thread)
            Drawing(name: "lantern")
                .frame(width: 24, height: 24)
        }
        .rotationEffect(.degrees(sin(time * 1.4 + phase) * 7), anchor: .top)
        .position(x: x, y: (thread + 24) / 2)
    }
}

// MARK: - Eid al-Fitr

/// Small stars twinkling in the upper part of the window, behind the content.
private struct Stars: View {
    let size: CGSize
    let still: Bool
    @State private var places: [CGPoint] = []

    var body: some View {
        Ticking(still: still) { time in
            ZStack {
                ForEach(places.indices, id: \.self) { index in
                    let glow = still ? 0.8 : 0.35 + 0.65 * abs(sin(time * 0.9 + Double(index) * 1.7))
                    Star()
                        .fill(Color(red: 1.0, green: 0.82, blue: 0.3).opacity(glow))
                        .frame(width: 9, height: 9)
                        .position(x: places[index].x * size.width, y: places[index].y * size.height)
                }
            }
        }
        .onAppear {
            if places.isEmpty {
                places = (0..<12).map { _ in
                    CGPoint(x: CGFloat.random(in: 0.05...0.85), y: CGFloat.random(in: 0.04...0.6))
                }
            }
        }
    }
}

/// A four-pointed star.
private struct Star: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        let c = CGPoint(x: rect.midX, y: rect.midY)
        let inner = min(rect.width, rect.height) * 0.14
        path.move(to: CGPoint(x: c.x, y: rect.minY))
        path.addLine(to: CGPoint(x: c.x + inner, y: c.y - inner))
        path.addLine(to: CGPoint(x: rect.maxX, y: c.y))
        path.addLine(to: CGPoint(x: c.x + inner, y: c.y + inner))
        path.addLine(to: CGPoint(x: c.x, y: rect.maxY))
        path.addLine(to: CGPoint(x: c.x - inner, y: c.y + inner))
        path.addLine(to: CGPoint(x: rect.minX, y: c.y))
        path.addLine(to: CGPoint(x: c.x - inner, y: c.y - inner))
        path.closeSubpath()
        return path
    }
}

// MARK: - Earth Day

/// The globe bottom right, with a sprout swaying beside it.
private struct EarthEdges: View {
    let size: CGSize
    let still: Bool

    var body: some View {
        Ticking(still: still) { time in
            HStack(alignment: .bottom, spacing: 2) {
                Drawing(name: "sprout")
                    .frame(width: 22, height: 22)
                    .rotationEffect(.degrees(sin(time * 1.2) * 6), anchor: .bottom)
                Drawing(name: "globe")
                    .frame(width: 32, height: 32)
                    .offset(y: CGFloat(sin(time * 1.0) * 2))
            }
            .position(x: size.width - 40, y: size.height - 20)
        }
    }
}

// MARK: - Día de los Muertos

/// Candles flickering in the bottom corners, with marigolds.
private struct DeadEdges: View {
    let size: CGSize
    let still: Bool

    var body: some View {
        Ticking(still: still) { time in
            ZStack {
                HStack(alignment: .bottom, spacing: 0) {
                    candle(time: time, phase: 0, height: 28)
                    Drawing(name: "blossom").frame(width: 20, height: 20)
                    candle(time: time, phase: 2.2, height: 22)
                }
                .position(x: 40, y: size.height - 18)
                HStack(alignment: .bottom, spacing: 0) {
                    Drawing(name: "blossom").frame(width: 18, height: 18)
                    candle(time: time, phase: 4.1, height: 26)
                    Drawing(name: "blossom").frame(width: 22, height: 22)
                }
                .position(x: size.width - 40, y: size.height - 18)
            }
        }
    }

    private func candle(time: Double, phase: Double, height: CGFloat) -> some View {
        let flicker = still ? 1 : 0.85 + 0.15 * sin(time * 9 + phase) * sin(time * 5.3 + phase * 2)
        return Drawing(name: "candle")
            .frame(width: height * 0.8, height: height)
            .opacity(flicker)
            .scaleEffect(x: 1, y: CGFloat(0.98 + 0.02 * flicker), anchor: .bottom)
    }
}
