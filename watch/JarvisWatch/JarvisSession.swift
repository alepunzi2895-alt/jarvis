import AVFoundation
import SwiftUI
import WatchKit

/// Stato della conversazione: domanda dettata, risposta letta a voce,
/// colore/energia della sfera come sulla dashboard.
@MainActor
final class JarvisSession: NSObject, ObservableObject {
    static let idleStatus = "Tocca per parlare"

    @Published var orbState: OrbState = .idle
    @Published var reply: String?
    @Published var status = JarvisSession.idleStatus
    private let synthesizer = AVSpeechSynthesizer()

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    func ask(_ text: String) {
        let question = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !question.isEmpty else { return }
        synthesizer.stopSpeaking(at: .immediate)
        reply = nil
        orbState = .thinking
        status = "Elaboro…"
        Task {
            do {
                let answer = try await JarvisClient.ask(question)
                reply = answer
                WKInterfaceDevice.current().play(.notification)
                speak(answer)
            } catch {
                reply = (error as? LocalizedError)?.errorDescription ?? "Errore di rete."
                orbState = .alert
                status = "Errore"
                WKInterfaceDevice.current().play(.failure)
                try? await Task.sleep(for: .seconds(3))
                if orbState == .alert { reset() }
            }
        }
    }

    private func speak(_ text: String) {
        let utterance = AVSpeechUtterance(string: text)
        utterance.voice = AVSpeechSynthesisVoice(language: "it-IT")
        orbState = .speaking
        status = ""
        synthesizer.speak(utterance)
    }

    fileprivate func finishedSpeaking() {
        // stopSpeaking() di una nuova domanda arriva qui in ritardo: non
        // deve riportare a riposo una sfera che sta gia' elaborando.
        if orbState == .speaking { reset() }
    }

    private func reset() {
        orbState = .idle
        status = JarvisSession.idleStatus
    }
}

extension JarvisSession: AVSpeechSynthesizerDelegate {
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didFinish utterance: AVSpeechUtterance) {
        Task { @MainActor in self.finishedSpeaking() }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer, didCancel utterance: AVSpeechUtterance) {
        Task { @MainActor in self.finishedSpeaking() }
    }
}
