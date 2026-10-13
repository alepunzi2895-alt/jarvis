"""Dashboard isolata: nessuna rete reale, registrazione o invio di comandi.

Richiede i browser Playwright: python -m playwright install chromium webkit.
WebKit desktop emulato verifica il layout e il ciclo UI, non l'hardware iOS.
"""

import json
from pathlib import Path
from urllib.parse import urlparse

import pytest

playwright = pytest.importorskip("playwright.sync_api")
PUBLIC = Path(__file__).resolve().parents[1] / "web" / "public"

MEDIA_STUB = """
window.mediaCalls = [];
window.captureStopped = 0;
window.deferPermission = false;
window.failPermission = false;
window.micAvailable = true;
window.lockHeld = false;
window.fakeNodes = [];
window.fakeTrack = {stop() { window.captureStopped++; }};
const stream = {getTracks: () => [fakeTrack], getAudioTracks: () => [fakeTrack]};
Object.defineProperty(navigator, 'mediaDevices', {value: {
  getUserMedia: async () => {
    mediaCalls.push('permission');
    if (failPermission) throw new DOMException('denied', 'NotAllowedError');
    if (deferPermission) return new Promise(resolve => { window.resolvePermission = () => resolve(stream); });
    return stream;
  },
}, configurable: true});
Object.defineProperty(navigator, 'locks', {value: {
  request: async (name, options, callback) => {
    if (!micAvailable) return callback(null);
    window.lockHeld = true;
    try { await callback({name}); } finally { window.lockHeld = false; }
  },
}, configurable: true});
function node() { return {connect() {}, disconnect() {}, gain: {value: 1}}; }
window.AudioContext = class {
  constructor() { this.state = 'suspended'; this.sampleRate = 48000; window.fakeContext = this; mediaCalls.push('context'); }
  resume() { mediaCalls.push('resume'); this.state = 'running'; return Promise.resolve(); }
  close() { this.state = 'closed'; return Promise.resolve(); }
  createMediaStreamSource() { return node(); }
  createScriptProcessor() { const n = node(); fakeNodes.push(n); return n; }
  createGain() { return node(); }
};
"""


@pytest.fixture(params=["chromium", "webkit"])
def mobile_page(request):
    with playwright.sync_playwright() as pw:
        engine = getattr(pw, request.param)
        if not Path(engine.executable_path).exists():
            pytest.skip(f"Playwright {request.param} non installato")
        browser = engine.launch()
        context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        context.add_init_script(MEDIA_STUB)
        page = context.new_page()
        page.errors = []
        page.on("pageerror", lambda error: page.errors.append(str(error)))

        def route_request(route):
            path = urlparse(route.request.url).path
            if path.startswith("/api/"):
                body = route.request.post_data_json or {}
                data = {"ok": True, "tasks": [], "speaking": False, "data": None, "nodes": [], "edges": []}
                if body.get("action") == "task_push":
                    data["task_id"] = "test-task"
                elif body.get("action") == "task_poll":
                    data["task"] = {"id": "test-task", "status": "done", "prompt": "Test", "result": "Risposta locale di test"}
                route.fulfill(json=data)
                return
            filenames = {"/": "index.html", "/app.js": "app.js", "/orb.js": "orb.js", "/style.css": "style.css"}
            if path not in filenames:
                route.fulfill(status=404)
                return
            content_types = {".html": "text/html", ".js": "application/javascript", ".css": "text/css"}
            file = PUBLIC / filenames[path]
            route.fulfill(body=file.read_bytes(), content_type=content_types[file.suffix])

        context.route("**/*", route_request)
        page.goto("http://localhost:4179/")
        page.locator("#app.visible").wait_for()
        yield page
        assert not page.errors
        context.close()
        browser.close()


def test_mobile_panels_and_controls_stay_inside_viewport(mobile_page):
    page = mobile_page
    for width, height in [(320, 568), (390, 844), (844, 390), (390, 400)]:
        page.set_viewport_size({"width": width, "height": height})
        page.locator('[data-toggle="win-weather"]').click()
        assert page.locator(".floating-window.open").count() == 1
        assert page.locator("#win-weather").is_visible()
        page.locator('[data-toggle="win-chat"]').click()
        page.wait_for_function("Math.abs(document.querySelector('#app').getBoundingClientRect().height - visualViewport.height) < 2")
        for selector in ["#win-chat", "#console-text", ".send-btn", ".dock"]:
            bounds = page.locator(selector).bounding_box()
            assert bounds["x"] >= 0 and bounds["y"] >= 0, selector
            assert bounds["x"] + bounds["width"] <= width + 1, selector
            assert bounds["y"] + bounds["height"] <= height + 1, selector
        assert page.locator(".send-btn").bounding_box()["height"] >= 44
        assert page.locator("#console-text").evaluate("el => getComputedStyle(el).fontSize") == "16px"
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


def test_mobile_mic_waits_for_tap_and_releases_on_interruption(mobile_page):
    page = mobile_page
    assert page.evaluate("mediaCalls") == []
    mic = page.locator("#mic-btn")
    mic.click()
    page.wait_for_function("document.querySelector('#mic-btn').getAttribute('aria-pressed') === 'true'")
    assert page.evaluate("mediaCalls") == ["context", "resume", "permission"]
    page.evaluate("fakeContext.state = 'interrupted'; fakeContext.onstatechange()")
    assert mic.get_attribute("aria-pressed") == "false"
    assert page.evaluate("captureStopped") == 1
    assert "interrotto" in page.locator("#voice-status").inner_text()
    page.wait_for_function("!lockHeld")
    mic.click()
    page.wait_for_function("document.querySelector('#mic-btn').getAttribute('aria-pressed') === 'true'")


def test_cancelled_permission_never_turns_mic_on_later(mobile_page):
    page = mobile_page
    page.evaluate("deferPermission = true")
    mic = page.locator("#mic-btn")
    mic.click()
    page.wait_for_function("typeof resolvePermission === 'function'")
    mic.click()
    page.evaluate("resolvePermission()")
    page.wait_for_function("captureStopped === 1")
    assert mic.get_attribute("aria-pressed") == "false"
    assert page.evaluate("fakeContext.state") == "closed"
    page.wait_for_function("!lockHeld")


def test_microphone_denial_and_busy_tab_are_recoverable(mobile_page):
    page = mobile_page
    mic = page.locator("#mic-btn")
    page.evaluate("micAvailable = false")
    mic.click()
    page.wait_for_function("document.querySelector('#voice-status').textContent.includes('altra scheda')")
    assert "permission" not in page.evaluate("mediaCalls")
    page.evaluate("micAvailable = true; failPermission = true")
    mic.click()
    page.wait_for_function("document.querySelector('#voice-status').textContent.includes('Consenti')")
    assert mic.get_attribute("aria-pressed") == "false"
    page.wait_for_function("!lockHeld")
    page.evaluate("failPermission = false")
    mic.click()
    page.wait_for_function("document.querySelector('#mic-btn').getAttribute('aria-pressed') === 'true'")


def test_background_discards_partial_recording(mobile_page):
    page = mobile_page
    uploads = []
    page.on("request", lambda req: uploads.append(req.post_data) if req.url.endswith("/api/jarvis") else None)
    page.locator("#mic-btn").click()
    page.wait_for_function("document.querySelector('#mic-btn').getAttribute('aria-pressed') === 'true'")
    page.evaluate("""() => {
      const processor = fakeNodes.at(-1);
      for (let i = 0; i < 8; i++) processor.onaudioprocess({inputBuffer: {getChannelData: () => new Float32Array(4096).fill(0.2)}});
      Object.defineProperty(document, 'hidden', {value: true, configurable: true});
      document.dispatchEvent(new Event('visibilitychange'));
    }""")
    assert page.locator("#mic-btn").get_attribute("aria-pressed") == "false"
    assert page.evaluate("captureStopped") == 1
    assert not any(json.loads(body).get("audio_b64") for body in uploads if body)


def test_short_spoken_command_submits_after_800ms_silence(mobile_page):
    page = mobile_page
    page.locator("#mic-btn").click()
    page.wait_for_function("document.querySelector('#mic-btn').getAttribute('aria-pressed') === 'true'")
    with page.expect_request(lambda req: req.post_data and '"audio_b64"' in req.post_data) as request:
        page.evaluate("""() => {
          const processor = fakeNodes.at(-1);
          const feed = value => processor.onaudioprocess({inputBuffer: {getChannelData: () => new Float32Array(4096).fill(value)}});
          for (let i = 0; i < 8; i++) feed(0.2);
          for (let i = 0; i < 10; i++) feed(0); // 853ms, less than the old 1200ms
        }""")
    assert request.value.post_data_json["audio_b64"].startswith("UklGR")


def test_mobile_projects_panel_survives_automatic_question(mobile_page):
    page = mobile_page
    with page.expect_request(lambda req: req.post_data and '"task_push"' in req.post_data):
        page.locator('[data-toggle="win-projects"]').click()
    assert page.locator("#win-projects").is_visible()
    assert page.locator("#win-chat").is_hidden()


def test_camera_permission_after_switching_panel_releases_stream(mobile_page):
    page = mobile_page
    page.evaluate("deferPermission = true")
    page.locator('[data-toggle="win-camera"]').click()
    page.wait_for_function("typeof resolvePermission === 'function'")
    page.locator('[data-toggle="win-chat"]').click()
    page.evaluate("resolvePermission()")
    page.wait_for_function("captureStopped === 1")
    assert page.locator("#win-camera").is_hidden()


def test_desktop_keeps_multiple_panels_and_rotation_selects_latest(mobile_page):
    page = mobile_page
    page.set_viewport_size({"width": 1280, "height": 800})
    page.locator('[data-toggle="win-weather"]').click()
    assert page.locator(".floating-window.open").count() == 2
    page.set_viewport_size({"width": 390, "height": 844})
    page.wait_for_function("document.querySelectorAll('.floating-window.open').length === 1")
    assert page.locator("#win-weather").is_visible()
