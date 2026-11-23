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
        if (month == 12 && day == 31) || (month == 1 && day == 1) {
            return .newYear
        }
        if month == 12 || (month == 1 && day <= 6) {
            return .christmas
        }
        if let sunday = easterSunday(year, calendar: calendar),
           let friday = calendar.date(byAdding: .day, value: -2, to: sunday),
           let monday = calendar.date(byAdding: .day, value: 1, to: sunday),
           today >= friday, today <= monday {
            return .easter
        }
        if month == 10 && day >= 25 {
            return .halloween
        }
        return nil
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
                    EmptyView()
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
                Eggs(still: still)
                    .position(x: space.size.width - 58, y: space.size.height - 16)
            case .halloween:
                Pumpkins()
                    .position(x: space.size.width - 50, y: space.size.height - 16)
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

// MARK: - Falling things

private enum FallingKind {
    case snow, confetti, petal, leaf
}

/// Flakes, confetti, petals or leaves drifting down behind the content.
private struct Falling: View {
    let kind: FallingKind
    let count: Int
    let size: CGSize
    let still: Bool
    @State private var seeds: [FallSeed] = []

    var body: some View {
        ZStack {
            ForEach(seeds) { seed in
                Faller(kind: kind, seed: seed, size: size, still: still)
            }
        }
        .onAppear {
            if seeds.isEmpty {
                seeds = (0..<count).map { FallSeed(id: $0) }
            }
        }
    }
}

private struct FallSeed: Identifiable {
    let id: Int
    let x = CGFloat.random(in: 0...1)
    let scale = CGFloat.random(in: 0.6...1.2)
    let duration = Double.random(in: 7...14)
    let delay = Double.random(in: 0...8)
    let sway = CGFloat.random(in: 10...28)
    let spin = Double.random(in: 120...420) * (Bool.random() ? 1 : -1)
    let hue = Int.random(in: 0..<5)
    let rest = CGFloat.random(in: 0.05...0.95)  // where it hangs with Reduce motion on
}

private struct Faller: View {
    let kind: FallingKind
    let seed: FallSeed
    let size: CGSize
    let still: Bool
    @State private var down = false
    @State private var swayed = false

    var body: some View {
        piece
            .scaleEffect(seed.scale)
            .rotationEffect(.degrees(down && !still ? seed.spin : 0))
            .offset(x: swayed ? seed.sway : -seed.sway)
            .position(
                x: seed.x * size.width,
                y: still ? seed.rest * size.height : (down ? size.height + 20 : -20)
            )
            .onAppear {
                guard !still else { return }
                withAnimation(.linear(duration: seed.duration).delay(seed.delay).repeatForever(autoreverses: false)) {
                    down = true
                }
                withAnimation(.easeInOut(duration: seed.duration / 4).repeatForever(autoreverses: true)) {
                    swayed = true
                }
            }
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

private struct Pumpkins: View {
    var body: some View {
        HStack(alignment: .bottom, spacing: 8) {
            Pumpkin().frame(width: 30, height: 24)
            Pumpkin().frame(width: 22, height: 18)
        }
    }
}

private struct Pumpkin: View {
    var body: some View {
        ZStack {
            HStack(spacing: -8) {
                Ellipse().fill(Color(red: 0.95, green: 0.5, blue: 0.1))
                Ellipse().fill(Color(red: 1.0, green: 0.58, blue: 0.15))
                Ellipse().fill(Color(red: 0.95, green: 0.5, blue: 0.1))
            }
            Capsule()
                .fill(Color(red: 0.3, green: 0.45, blue: 0.15))
                .frame(width: 3, height: 7)
                .offset(y: -13)
        }
    }
}

/// A few bats crossing the window now and then.
private struct Bats: View {
    let size: CGSize
    let still: Bool

    var body: some View {
        ZStack {
            ForEach(0..<4, id: \.self) { index in
                FlyingBat(index: index, size: size, still: still)
            }
        }
    }
}

private struct FlyingBat: View {
    let index: Int
    let size: CGSize
    let still: Bool
    @State private var across = false
    @State private var flap = false

    var body: some View {
        let height = size.height * (0.15 + 0.2 * CGFloat(index))
        Bat()
            .fill(Color.primary.opacity(0.45))
            .frame(width: 22, height: 10)
            .scaleEffect(x: 1, y: flap ? 0.4 : 1)
            .position(
                x: still ? size.width * (0.2 + 0.2 * CGFloat(index)) : (across ? size.width + 30 : -30),
                y: height
            )
            .onAppear {
                guard !still else { return }
                withAnimation(.linear(duration: 9 + Double(index) * 2).delay(Double(index) * 3)
                    .repeatForever(autoreverses: false)) { across = true }
                withAnimation(.easeInOut(duration: 0.18).repeatForever(autoreverses: true)) { flap = true }
            }
    }
}

private struct Bat: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        let mid = rect.midX
        path.move(to: CGPoint(x: mid, y: rect.midY + 2))
        path.addQuadCurve(to: CGPoint(x: rect.minX, y: rect.minY), control: CGPoint(x: mid - rect.width * 0.25, y: rect.minY - 2))
        path.addQuadCurve(to: CGPoint(x: mid - 2, y: rect.maxY), control: CGPoint(x: rect.minX + 4, y: rect.maxY))
        path.addLine(to: CGPoint(x: mid + 2, y: rect.maxY))
        path.addQuadCurve(to: CGPoint(x: rect.maxX, y: rect.minY), control: CGPoint(x: rect.maxX - 4, y: rect.maxY))
        path.addQuadCurve(to: CGPoint(x: mid, y: rect.midY + 2), control: CGPoint(x: mid + rect.width * 0.25, y: rect.minY - 2))
        path.closeSubpath()
        return path
    }
}
