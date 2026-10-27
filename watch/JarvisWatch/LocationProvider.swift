import CoreLocation

/// Posizione del Watch per il meteo di JARVIS (il ponte VPS la usa per 12 ore
/// e la inoltra al PC). Sempre facoltativa: senza permesso o senza fix entro
/// 3 secondi la domanda parte comunque, senza posizione.
@MainActor
final class LocationProvider: NSObject, CLLocationManagerDelegate {
    static let shared = LocationProvider()

    struct Place {
        let latitude: Double
        let longitude: Double
        let city: String?
    }

    private let manager = CLLocationManager()
    private var continuation: CheckedContinuation<CLLocation?, Never>?
    private var cached: (place: Place, at: Date)?

    override init() {
        super.init()
        manager.delegate = self
        manager.desiredAccuracy = kCLLocationAccuracyKilometer
    }

    func current() async -> Place? {
        if let cached, Date().timeIntervalSince(cached.at) < 600 { return cached.place }
        switch manager.authorizationStatus {
        case .notDetermined:
            manager.requestWhenInUseAuthorization()
            return nil  // la prima domanda parte senza: il permesso vale dalla prossima
        case .denied, .restricted:
            return nil
        default:
            break
        }
        guard continuation == nil else { return nil }
        let location: CLLocation? = await withCheckedContinuation { continuation in
            self.continuation = continuation
            manager.requestLocation()
            Task { @MainActor in
                try? await Task.sleep(for: .seconds(3))
                self.finish(nil)
            }
        }
        guard let location else { return nil }
        let place = Place(latitude: location.coordinate.latitude, longitude: location.coordinate.longitude,
                          city: await cityName(location))
        cached = (place, Date())
        return place
    }

    private func cityName(_ location: CLLocation) async -> String? {
        await withTaskGroup(of: String?.self) { group in
            group.addTask { try? await CLGeocoder().reverseGeocodeLocation(location).first?.locality }
            group.addTask {
                try? await Task.sleep(for: .seconds(2))
                return nil
            }
            let first = await group.next() ?? nil
            group.cancelAll()
            return first
        }
    }

    private func finish(_ location: CLLocation?) {
        continuation?.resume(returning: location)
        continuation = nil
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        let last = locations.last
        Task { @MainActor in self.finish(last) }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        Task { @MainActor in self.finish(nil) }
    }
}
