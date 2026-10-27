import SwiftUI

/// Schermata unica a tutto schermo: sfera animata, scritta JARVIS e ora
/// digitale al centro. Un tocco apre la dettatura e manda la domanda al PC.
struct ContentView: View {
    @StateObject private var jarvis = JarvisSession()
    @Environment(\.isLuminanceReduced) private var dimmed

    // Accento fisso della dashboard (#3987e5).
    private let accent = Color(red: 0x39 / 255, green: 0x87 / 255, blue: 0xE5 / 255)

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            TextFieldLink(prompt: Text("Chiedi a JARVIS")) {
                face
            } onSubmit: { text in
                jarvis.ask(text)
            }
            .buttonStyle(.plain)
            if let reply = jarvis.reply, !dimmed {
                ReplyCard(text: reply) { jarvis.reply = nil }
            }
        }
    }

    private var face: some View {
        ZStack {
            OrbView(state: jarvis.orbState, dimmed: dimmed)
            VStack(spacing: 0) {
                Text("JARVIS")
                    .font(.system(size: 12, weight: .semibold, design: .rounded))
                    .tracking(4)
                    .foregroundStyle(accent)
                TimelineView(.everyMinute) { context in
                    Text(context.date, style: .time)
                        .font(.system(size: 40, weight: .light, design: .rounded))
                        .monospacedDigit()
                        .foregroundStyle(dimmed ? Color.gray : Color.white)
                        .shadow(color: accent.opacity(dimmed ? 0 : 0.9), radius: 6)
                }
                if !dimmed && !jarvis.status.isEmpty {
                    Text(jarvis.status)
                        .font(.system(size: 10, design: .rounded))
                        .foregroundStyle(.white.opacity(0.6))
                }
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .contentShape(Rectangle())
        .ignoresSafeArea()
    }
}

/// Risposta in basso, scorrevole con la Digital Crown; tocco per chiudere.
struct ReplyCard: View {
    let text: String
    let dismiss: () -> Void

    var body: some View {
        VStack {
            Spacer()
            ScrollView {
                Text(text)
                    .font(.footnote)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(maxHeight: 90)
            .padding(8)
            .background(RoundedRectangle(cornerRadius: 12).fill(Color.black.opacity(0.75)))
            .onTapGesture(perform: dismiss)
        }
        .padding(.horizontal, 4)
    }
}
