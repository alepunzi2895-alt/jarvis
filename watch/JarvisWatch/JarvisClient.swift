import Foundation

struct JarvisError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}

/// POST /watch/ask su LiveBridge (core/live_server.py): testo in, testo out.
enum JarvisClient {
    static func ask(_ text: String) async throws -> String {
        guard let url = URL(string: JarvisConfig.baseURL + "/watch/ask") else {
            throw JarvisError("Indirizzo JARVIS non valido in Config.swift.")
        }
        var request = URLRequest(url: url, timeoutInterval: 60)
        request.httpMethod = "POST"
        request.setValue("Bearer \(JarvisConfig.token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(["text": text])
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            let body = String(decoding: data, as: UTF8.self)
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            guard code == 200 else {
                throw JarvisError(body.isEmpty ? "Errore \(code) dal PC." : body)
            }
            return body
        } catch let error as URLError {
            throw JarvisError(error.code == .timedOut
                ? "Il PC non ha risposto in tempo."
                : "PC non raggiungibile. Controlla iPhone e Tailscale.")
        }
    }
}
