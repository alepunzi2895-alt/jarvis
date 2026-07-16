from unittest.mock import MagicMock, patch

import requests

from core import weather


def _fake_response(json_data):
    r = MagicMock()
    r.json.return_value = json_data
    r.raise_for_status.return_value = None
    return r


def test_describe_known_and_unknown_codes():
    assert weather._describe(0) == "cielo sereno"
    assert weather._describe(61) == "pioggia leggera"
    assert weather._describe(9999) == "condizioni non disponibili"


def test_get_weather_line_with_explicit_coordinates(monkeypatch):
    monkeypatch.setenv("JARVIS_WEATHER_LAT", "38.9")
    monkeypatch.setenv("JARVIS_WEATHER_LON", "1.43")
    monkeypatch.setenv("JARVIS_WEATHER_CITY", "Ibiza")

    forecast = _fake_response({"current": {"temperature_2m": 27.4, "weather_code": 0, "wind_speed_10m": 12.0}})
    with patch("core.weather.requests.get", return_value=forecast) as get:
        line = weather.get_weather_line()

    assert "27" in line
    assert "cielo sereno" in line
    assert "Ibiza" in line
    get.assert_called_once()  # coordinate esplicite: niente chiamata di geocoding/IP


def test_get_weather_line_falls_back_to_ip_geolocation(monkeypatch):
    monkeypatch.delenv("JARVIS_WEATHER_LAT", raising=False)
    monkeypatch.delenv("JARVIS_WEATHER_LON", raising=False)
    monkeypatch.delenv("JARVIS_WEATHER_CITY", raising=False)

    ip_resp = _fake_response({"status": "success", "lat": 45.46, "lon": 9.19, "city": "Milano"})
    forecast_resp = _fake_response({"current": {"temperature_2m": 30.0, "weather_code": 95, "wind_speed_10m": 5.0}})
    with patch("core.weather.requests.get", side_effect=[ip_resp, forecast_resp]) as get:
        line = weather.get_weather_line()

    assert "Milano" in line
    assert "temporale" in line
    assert get.call_count == 2


def test_get_weather_line_geocodes_city_when_no_coordinates(monkeypatch):
    monkeypatch.delenv("JARVIS_WEATHER_LAT", raising=False)
    monkeypatch.delenv("JARVIS_WEATHER_LON", raising=False)
    monkeypatch.setenv("JARVIS_WEATHER_CITY", "Ibiza")

    geocode_resp = _fake_response({"results": [{"latitude": 38.9, "longitude": 1.43, "name": "Ibiza"}]})
    forecast_resp = _fake_response({"current": {"temperature_2m": 25.0, "weather_code": 2, "wind_speed_10m": 8.0}})
    with patch("core.weather.requests.get", side_effect=[geocode_resp, forecast_resp]) as get:
        line = weather.get_weather_line()

    assert "Ibiza" in line
    assert "parzialmente nuvoloso" in line
    assert get.call_count == 2


def test_get_weather_line_caches_between_calls(monkeypatch):
    monkeypatch.setenv("JARVIS_WEATHER_LAT", "38.9")
    monkeypatch.setenv("JARVIS_WEATHER_LON", "1.43")
    forecast = _fake_response({"current": {"temperature_2m": 20.0, "weather_code": 1, "wind_speed_10m": 3.0}})
    with patch("core.weather.requests.get", return_value=forecast) as get:
        weather.get_weather_line()
        weather.get_weather_line()

    get.assert_called_once()


def test_get_weather_line_returns_none_on_network_error(monkeypatch):
    monkeypatch.setenv("JARVIS_WEATHER_LAT", "38.9")
    monkeypatch.setenv("JARVIS_WEATHER_LON", "1.43")
    with patch("core.weather.requests.get", side_effect=requests.exceptions.ConnectionError("no network")):
        assert weather.get_weather_line() is None


def test_get_weather_line_returns_none_when_no_location_resolvable(monkeypatch):
    monkeypatch.delenv("JARVIS_WEATHER_LAT", raising=False)
    monkeypatch.delenv("JARVIS_WEATHER_LON", raising=False)
    monkeypatch.delenv("JARVIS_WEATHER_CITY", raising=False)

    ip_resp = _fake_response({"status": "fail"})
    with patch("core.weather.requests.get", return_value=ip_resp):
        assert weather.get_weather_line() is None
