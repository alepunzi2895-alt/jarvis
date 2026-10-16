import SwiftUI

/// Stessi stati e parametri di web/public/orb.js (ORB_STATES).
enum OrbState {
    case idle, listening, thinking, speaking, alert

    var hue: Double {
        switch self {
        case .idle, .listening: 205
        case .thinking: 38
        case .speaking: 150
        case .alert: 356
        }
    }

    var rotation: Double {
        switch self {
        case .idle: 0.0018
        case .listening: 0.0035
        case .thinking: 0.011
        case .speaking: 0.005
        case .alert: 0.007
        }
    }

    var fireRate: Double {
        switch self {
        case .idle: 0.012
        case .listening: 0.03
        case .thinking: 0.22
        case .speaking: 0.05
        case .alert: 0.12
        }
    }

    var pulseSpeed: Double {
        switch self {
        case .idle: 0.014
        case .listening: 0.022
        case .thinking: 0.045
        case .speaking: 0.03
        case .alert: 0.04
        }
    }
}

/// Sfera di nodi/archi con impulsi luminosi: porting di web/public/orb.js,
/// stile "liscia" (2026-10-16): raggio dei nodi costante, bordo e alone
/// circolari, propagazione sotto la soglia delle cascate. Meno nodi e impulsi
/// che sul PC per la batteria del Watch.
final class OrbModel {
    private struct Node {
        var x, y, z: Double
        var phase: Double
        var hue: Double
        var energy = 0.0
        var refractory = 0
        var sx = 0.0, sy = 0.0, sz = 0.0
        var neighbours: [Int] = []
    }

    private struct Pulse {
        var from: Int
        var to: Int
        var progress: Double
        var hue: Double
    }

    var state: OrbState = .idle
    private var nodes: [Node] = []
    private var edges: [(Int, Int)] = []
    private var pulses: [Pulse] = []
    private var rot: Double
    private var fire: Double
    private var speed: Double
    private var hue: Double
    private var level = 0.0
    private var rotY = 0.0
    private var rotX = 0.35
    private var t = 0.0
    private var last: Date?
    private var pending = 0.0

    init(count: Int = 100, neighbours: Int = 3) {
        rot = OrbState.idle.rotation
        fire = OrbState.idle.fireRate
        speed = OrbState.idle.pulseSpeed
        hue = OrbState.idle.hue
        let golden = Double.pi * (3 - 5.0.squareRoot())
        for i in 0..<count {
            let y = 1 - Double(i) / Double(count - 1) * 2
            let r = (1 - y * y).squareRoot()
            let theta = golden * Double(i)
            nodes.append(Node(x: cos(theta) * r, y: y, z: sin(theta) * r,
                              phase: .random(in: 0..<6.28), hue: hue))
        }
        var seen = Set<Int>()
        for i in nodes.indices {
            let nearest = nodes.indices
                .filter { $0 != i }
                .sorted { Self.distance(nodes[i], nodes[$0]) < Self.distance(nodes[i], nodes[$1]) }
                .prefix(neighbours)
            for j in nearest where seen.insert(min(i, j) * count + max(i, j)).inserted {
                edges.append((i, j))
            }
        }
        for (a, b) in edges {
            nodes[a].neighbours.append(b)
            nodes[b].neighbours.append(a)
        }
    }

    /// Avanza a passi da 1/60 s come il loop del browser, a qualunque frame rate.
    func advance(to date: Date) {
        if let last {
            pending = min(pending + date.timeIntervalSince(last) * 60, 4)
        } else {
            pending = 1
        }
        last = date
        while pending >= 1 {
            step()
            pending -= 1
        }
    }

    func draw(_ g: inout GraphicsContext, size: CGSize, dimmed: Bool) {
        let radius = project(size)
        let cx = Double(size.width) / 2, cy = Double(size.height) / 2
        let flick = (state == .alert && Double.random(in: 0..<1) < 0.08) ? 0.4 : 1.0
        let dim = dimmed ? 0.35 : 1.0

        g.blendMode = .plusLighter
        if !dimmed {
            let core = Gradient(colors: [
                Self.hsl(hue, 1, 0.7, (0.22 + level * 0.35) * flick),
                Self.hsl(hue, 1, 0.5, 0),
            ])
            g.fill(Self.circle(cx, cy, radius * 1.1),
                   with: .radialGradient(core, center: CGPoint(x: cx, y: cy), startRadius: 0,
                                         endRadius: radius * (0.55 + level * 0.5)))
        }

        for (i, j) in edges {
            let a = nodes[i], b = nodes[j]
            let depth = ((a.sz + b.sz) / 2 + 1) / 2
            let e = max(a.energy, b.energy)
            var path = Path()
            path.move(to: CGPoint(x: a.sx, y: a.sy))
            path.addLine(to: CGPoint(x: b.sx, y: b.sy))
            let alpha = (0.06 + depth * 0.18 + e * 0.45) * flick * dim
            g.stroke(path, with: .color(Self.hsl(a.hue, 0.8, 0.35 + e * 0.35, alpha)), lineWidth: 0.5 + e * 1.2)
        }

        if !dimmed {
            for p in pulses {
                let a = nodes[p.from], b = nodes[p.to]
                let x = a.sx + (b.sx - a.sx) * p.progress
                let y = a.sy + (b.sy - a.sy) * p.progress
                g.fill(Self.circle(x, y, 3), with: .color(Self.hsl(p.hue, 1, 0.65, 0.22)))
                g.fill(Self.circle(x, y, 1.1), with: .color(Self.hsl(p.hue, 1, 0.88, 0.95)))
            }
        }

        for n in nodes {
            let depth = (n.sz + 1) / 2
            let r = 0.7 + depth * 1.2 + n.energy * 1.8
            if n.energy > 0.08 && !dimmed {
                g.fill(Self.circle(n.sx, n.sy, r * 4), with: .color(Self.hsl(n.hue, 1, 0.6, n.energy * 0.2)))
            }
            let color = Self.hsl(n.hue, 0.5 + n.energy * 0.5, 0.4 + depth * 0.2 + n.energy * 0.3,
                                 (0.35 + depth * 0.65) * flick * dim)
            g.fill(Self.circle(n.sx, n.sy, r), with: .color(color))
        }

        if !dimmed {
            let halo = Gradient(stops: [
                .init(color: Self.hsl(hue, 1, 0.6, 0), location: 0),
                .init(color: Self.hsl(hue, 1, 0.62, 0.2), location: 0.35),
                .init(color: Self.hsl(hue, 1, 0.5, 0), location: 1),
            ])
            g.fill(Self.circle(cx, cy, radius * 1.22),
                   with: .radialGradient(halo, center: CGPoint(x: cx, y: cy), startRadius: radius * 0.94,
                                         endRadius: radius * 1.22))
        }

        g.blendMode = .normal
        g.stroke(Self.circle(cx, cy, radius * 1.04), with: .color(Self.hsl(hue, 0.9, 0.7, 0.55 * dim)), lineWidth: 1)
        let rings: [(k: Double, speed: Double, length: Double, alpha: Double)] = [
            (1.1, 0.0025, 0.9, 0.3), (1.16, -0.004, 0.35, 0.18),
        ]
        for (index, ring) in rings.enumerated() {
            let a0 = t * ring.speed * (1 + level * 3) + Double(index)
            for s in 0..<3 {
                let start = a0 + Double(s) * 2.094
                var arc = Path()
                arc.addArc(center: CGPoint(x: cx, y: cy), radius: radius * ring.k,
                           startAngle: .radians(start), endAngle: .radians(start + ring.length), clockwise: false)
                let color = Self.hsl(hue, 0.9, 0.65, (ring.alpha + level * 0.3) * dim)
                g.stroke(arc, with: .color(color), lineWidth: 1)
            }
        }
    }

    private func step() {
        t += 1
        rot += (state.rotation - rot) * 0.04
        fire += (state.fireRate - fire) * 0.04
        speed += (state.pulseSpeed - speed) * 0.04
        hue = Self.lerpAngle(hue, state.hue, 0.05)

        // Nessun livello audio reale sul Watch: auto-pulsa come orb.js.
        let targetLevel: Double
        switch state {
        case .speaking: targetLevel = 0.35 + abs(sin(t * 0.21) * sin(t * 0.053)) * 0.6
        case .listening: targetLevel = 0.15 + abs(sin(t * 0.13)) * 0.2
        default: targetLevel = 0
        }
        level += (targetLevel - level) * 0.25
        rotY += rot * (1 + level * 2)
        rotX = 0.35 + sin(t * 0.003) * 0.12

        if Double.random(in: 0..<1) < fire * (1 + level * 4) {
            let h = (hue + Double.random(in: -15..<15) + 360).truncatingRemainder(dividingBy: 360)
            ignite(Int.random(in: nodes.indices), hue: h)
        }
        if level > 0.5 && Double.random(in: 0..<1) < level * 0.3 {
            ignite(Int.random(in: nodes.indices), hue: hue)
        }
        for i in nodes.indices {
            nodes[i].energy *= 0.955
            if nodes[i].refractory > 0 { nodes[i].refractory -= 1 }
            nodes[i].hue = Self.lerpAngle(nodes[i].hue, hue, 0.01)
        }
        var arrived: [Pulse] = []
        var moving: [Pulse] = []
        for var p in pulses {
            p.progress += speed
            if p.progress >= 1 { arrived.append(p) } else { moving.append(p) }
        }
        pulses = moving
        for p in arrived { ignite(p.to, hue: p.hue) }
        if pulses.count > 160 { pulses.removeFirst(pulses.count - 160) }
    }

    private func ignite(_ i: Int, hue h: Double) {
        guard nodes[i].refractory == 0 else { return }
        nodes[i].energy = 1
        nodes[i].refractory = 30
        nodes[i].hue = h
        for j in nodes[i].neighbours where Double.random(in: 0..<1) < 0.32 {
            pulses.append(Pulse(from: i, to: j, progress: 0, hue: h))
        }
    }

    private func project(_ size: CGSize) -> Double {
        let w = Double(size.width), h = Double(size.height)
        let radius = min(w, h) * 0.37 * (1 + level * 0.18)
        let cosY = cos(rotY), sinY = sin(rotY), cosX = cos(rotX), sinX = sin(rotX)
        let focal = radius * 3.2
        for i in nodes.indices {
            let n = nodes[i]
            let wobble = 1 + sin(t * 0.02 + n.phase) * 0.006 + n.energy * 0.02
            let x = n.x * wobble, y = n.y * wobble, z = n.z * wobble
            let x1 = x * cosY - z * sinY, z1 = x * sinY + z * cosY
            let y1 = y * cosX - z1 * sinX, z2 = y * sinX + z1 * cosX
            let scale = focal / (focal - z2 * radius)
            nodes[i].sx = w / 2 + x1 * radius * scale
            nodes[i].sy = h / 2 + y1 * radius * scale
            nodes[i].sz = z2
        }
        return radius
    }

    private static func distance(_ a: Node, _ b: Node) -> Double {
        (a.x - b.x) * (a.x - b.x) + (a.y - b.y) * (a.y - b.y) + (a.z - b.z) * (a.z - b.z)
    }

    private static func lerpAngle(_ a: Double, _ b: Double, _ k: Double) -> Double {
        let d = (b - a + 540).truncatingRemainder(dividingBy: 360) - 180
        return (a + d * k + 360).truncatingRemainder(dividingBy: 360)
    }

    private static func circle(_ x: Double, _ y: Double, _ r: Double) -> Path {
        Path(ellipseIn: CGRect(x: x - r, y: y - r, width: r * 2, height: r * 2))
    }

    /// hsla() del canvas web convertito in HSB di SwiftUI.
    static func hsl(_ h: Double, _ s: Double, _ l: Double, _ a: Double) -> Color {
        let v = l + s * min(l, 1 - l)
        let saturation = v == 0 ? 0 : 2 * (1 - l / v)
        return Color(hue: h / 360, saturation: saturation, brightness: v, opacity: max(0, min(1, a)))
    }
}

struct OrbView: View {
    var state: OrbState
    var dimmed: Bool
    @State private var model = OrbModel()

    var body: some View {
        // Always On: niente animazione, solo un fotogramma attenuato.
        TimelineView(.animation(minimumInterval: 1.0 / 30.0, paused: dimmed)) { timeline in
            Canvas { context, size in
                model.state = state
                if !dimmed { model.advance(to: timeline.date) }
                model.draw(&context, size: size, dimmed: dimmed)
            }
        }
    }
}
