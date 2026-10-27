import Foundation

struct JarvisError: LocalizedError {
    let message: String
    init(_ message: String) { self.message = message }
    var errorDescription: String? { message }
}

/// POST /watch/ask sul ponte VPS (core/relay.py): testo in, testo out.
/// PC acceso: risponde il PC con tutte le sue app; PC spento: risponde la VPS.
enum JarvisClient {
    @MainActor
    static func ask(_ text: String) async throws -> String {
        guard let url = URL(string: JarvisConfig.baseURL + "/watch/ask") else {
            throw JarvisError("Indirizzo JARVIS non valido in Config.swift.")
        }
        var body = ["text": text]
        if let place = await LocationProvider.shared.current() {
            body["lat"] = String(place.latitude)
            body["lon"] = String(place.longitude)
            if let city = place.city { body["city"] = city }
        }
        var request = URLRequest(url: url, timeoutInterval: 60)
        request.httpMethod = "POST"
        request.setValue("Bearer \(JarvisConfig.token)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(body)
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            let reply = String(decoding: data, as: UTF8.self)
            let code = (response as? HTTPURLResponse)?.statusCode ?? 0
            guard code == 200 else {
                throw JarvisError(reply.isEmpty ? "Errore \(code) da JARVIS." : reply)
            }
            return reply
        } catch let error as URLError {
            throw JarvisError(error.code == .timedOut
                ? "JARVIS non ha risposto in tempo."
                : "JARVIS non raggiungibile. Controlla iPhone e Tailscale.")
        }
    }
}
