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
window.playedSources = [];
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
  createBuffer() { return {}; }
  decodeAudioData() { return Promise.resolve({duration: 1}); }
  createBufferSource() { const source = {...node(), start() { playedSources.push(this); }, stop() { this.stopped = true; }}; return source; }
};
"""

DIRECT_STUB = """
window.JARVIS_LOCAL = true;
window.liveMessages = [];
window.WebSocket = class {
  static OPEN = 1;
  constructor() {
    this.readyState = 0; window.liveSocket = this;
    this.open = () => { this.readyState = 1; this.onopen?.(); this.emit({type: 'ready', stt_ready: true, device: 'cpu'}); };
    if (!window.deferSocketOpen) setTimeout(this.open, 0);
  }
  send(data) { liveMessages.push(JSON.parse(data)); }
  emit(data) { this.onmessage?.({data: JSON.stringify(data)}); }
  close() { this.readyState = 3; this.onclose?.(); }
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
        if "direct" in request.node.name:
            context.add_init_script(DIRECT_STUB)
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
            filenames = {"/": "index.html", "/app.js": "app.js", "/live.js": "live.js", "/orb.js": "orb.js", "/style.css": "style.css"}
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


def test_direct_unified_starters_and_dynamic_project_labels(mobile_page):
    page = mobile_page
    assert page.locator('[data-toggle="win-tradeflow"]').count() == 0
    page.get_by_role("button", name="Organizza oggi", exact=True).click()
    page.wait_for_function("liveMessages.some(m => m.type === 'text')")
    assert "Organizza" in page.evaluate("liveMessages.find(m => m.type === 'text').prompt")
    page.evaluate("""async () => {
      const original = api;
      api = async (action) => action === 'project_status_data' ? {projects:[
        {label:'<img src=x onerror=alert(1)>',configured:true,branch:'<main>',dirty_files:1,last_commit:'a (<script>)'},
        {label:'Nuovo progetto',configured:false}
      ]} : original(action);
      await refreshProjectStatus();
      api = original;
    }""")
    assert page.locator("#project-cards img, #project-cards script").count() == 0
    assert "Nuovo progetto" in page.locator("#project-cards").inner_text()


def test_direct_network_indicator_tracks_socket_not_widget_requests(mobile_page):
    page = mobile_page
    page.wait_for_function("document.querySelector('.live-controls span').textContent.includes('pronta')")
    assert page.locator("#hud-conn").inner_text() == "online"
    page.evaluate("window.oldSocket = liveSocket; liveSocket.close(); window.deferSocketOpen = true")
    assert page.locator("#hud-conn").inner_text() == "offline"
    page.evaluate("api('runtime_status')")
    assert page.locator("#hud-conn").inner_text() == "offline"
    page.get_by_role("button", name="Organizza oggi", exact=True).click()
    assert page.locator("#hud-conn").inner_text() == "collegamento"
    page.evaluate("liveSocket.open()")
    assert page.locator("#hud-conn").inner_text() == "online"
    page.evaluate("oldSocket.onclose()")
    assert page.locator("#hud-conn").inner_text() == "online"
    page.evaluate("liveSocket.onerror({})")
    assert page.locator("#hud-conn").inner_text() == "offline"


def test_network_indicator_tracks_cloud_api_and_recovers(mobile_page):
    page = mobile_page
    page.evaluate("api('runtime_status')")
    assert page.locator("#hud-conn").inner_text() == "online"
    page.route("**/api/jarvis", lambda route: route.abort())
    page.evaluate("api('runtime_status').catch(() => {})")
    assert page.locator("#hud-conn").inner_text() == "offline"
    page.unroute("**/api/jarvis")
    page.evaluate("api('runtime_status')")
    assert page.locator("#hud-conn").inner_text() == "online"


def test_weather_header_stays_below_topbar_on_desktop(mobile_page):
    page = mobile_page
    page.set_viewport_size({"width": 1366, "height": 768})
    page.evaluate("""() => {
      const original = api;
      api = async (action) => action === 'weather_forecast' ? {forecast: {place:'Ibiza', days:
        Array.from({length:7}, (_, i) => ({date:`2026-10-${13+i}`,code:0,high:24,low:18}))
      }} : original(action);
    }""")
    page.locator('[data-toggle="win-weather"]').click()
    page.wait_for_function("document.querySelectorAll('.weather-day').length === 7")
    for width, height in [(1366, 768), (1024, 600), (900, 500)]:
        page.set_viewport_size({"width": width, "height": height})
        page.wait_for_function("""() => {
          const w = document.querySelector('#win-weather').getBoundingClientRect();
          const header = document.querySelector('#app > header').getBoundingClientRect();
          return w.top >= header.bottom + 8;
        }""")
        assert page.locator("#weather-place").text_content() == "Ibiza"
        box = page.locator("#win-weather").bounding_box()
        assert box["y"] + box["height"] < height


def test_weather_starts_closed_on_desktop_and_uses_svg_icons(mobile_page):
    page = mobile_page
    page.set_viewport_size({"width": 1366, "height": 768})
    page.reload()
    page.locator("#app.visible").wait_for()
    page.wait_for_timeout(300)
    assert not page.evaluate("document.querySelector('#win-weather').classList.contains('open')")
    page.evaluate("""() => {
      const original = api;
      api = async (action) => action === 'weather_forecast' ? {forecast: {place:'Torino', days:
        [0, 2, 3, 45, 53, 63, 73, 95, 7].map((code, i) => ({date:`2026-10-${10+i}`, code, high:20, low:10}))
      }} : original(action);
    }""")
    page.locator('[data-toggle="win-weather"]').click()
    page.wait_for_function("document.querySelectorAll('.weather-day').length === 9")
    kinds = page.evaluate("[...document.querySelectorAll('.weather-day svg.weather-icon')].map(s => s.getAttribute('class'))")
    assert kinds == [f"weather-icon wx-{k}" for k in ["sun", "partly", "cloud", "fog", "drizzle", "rain", "snow", "storm", "cloud"]]
    assert page.locator(".weather-day svg title").first.text_content() == "Sereno"
    assert not page.evaluate(r"/\p{Extended_Pictographic}/u.test(document.querySelector('#weather-days').textContent)")


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


def test_direct_text_stream_audio_stop_and_no_cloud_fallback(mobile_page):
    page = mobile_page
    uploads = []
    page.on("request", lambda req: uploads.append(req.post_data) if req.url.endswith("/api/jarvis") else None)
    page.locator("#console-text").fill("come stai")
    page.locator(".send-btn").click()
    page.wait_for_function("liveMessages.some(m => m.type === 'text')")
    assert "resume" in page.evaluate("mediaCalls")
    page.evaluate("""() => {
      const id = liveMessages.find(m => m.type === 'text').id;
      liveSocket.emit({type:'accepted', id, prompt:'come stai'});
      liveSocket.emit({type:'sentence', id, text:'Prima frase.'});
      liveSocket.emit({type:'audio', id, data:btoa('mp3')});
    }""")
    assert "Prima frase." in page.locator(".entry .result").last.inner_text()
    page.wait_for_function("playedSources.length >= 2")
    page.get_by_role("button", name="Stop", exact=True).click()
    assert page.evaluate("playedSources.at(-1).stopped")
    page.evaluate("liveSocket.close()")
    assert not any(json.loads(body).get("action") == "task_push" for body in uploads if body)
    assert "scollegato" in page.locator(".live-controls span").inner_text()


def test_direct_hidden_page_keeps_long_command_and_labels_superseded(mobile_page):
    page = mobile_page
    page.locator("#console-text").fill("analizza i job")
    page.locator(".send-btn").click()
    page.wait_for_function("liveMessages.some(m => m.type === 'text')")
    page.evaluate("""() => {
      window.firstId = liveMessages.find(m => m.type === 'text').id;
      liveSocket.emit({type:'accepted', id:firstId, prompt:'analizza i job'});
      Object.defineProperty(document, 'hidden', {value: true, configurable: true});
      document.dispatchEvent(new Event('visibilitychange'));
      Object.defineProperty(document, 'hidden', {value: false, configurable: true});
    }""")
    assert not page.evaluate("liveMessages.some(m => m.type === 'cancel')")
    page.evaluate("liveSocket.emit({type:'sentence', id:firstId, text:'Analisi pronta.'})")
    assert "Analisi pronta." in page.locator(".entry .result").last.inner_text()
    page.locator("#console-text").fill("organizza oggi")
    page.locator(".send-btn").click()
    page.wait_for_function("liveMessages.filter(m => m.type === 'text').length === 2")
    page.evaluate("""() => {
      const second = liveMessages.filter(m => m.type === 'text')[1].id;
      liveSocket.emit({type:'accepted', id:second, prompt:'organizza oggi'});
      liveSocket.emit({type:'cancelled', id:firstId});
    }""")
    assert page.get_by_text("Sostituito dal comando successivo.").count() == 1


@pytest.mark.parametrize('volume', [.2, .025])
def test_direct_mic_sends_wav_only_over_websocket(mobile_page, volume):
    page = mobile_page
    uploads = []
    page.on("request", lambda req: uploads.append(req.post_data) if req.url.endswith("/api/jarvis") else None)
    page.locator("#mic-btn").click()
    page.wait_for_function("document.querySelector('#mic-btn').getAttribute('aria-pressed') === 'true'")
    page.evaluate("""volume => {
      const processor = fakeNodes.at(-1);
      const feed = value => processor.onaudioprocess({inputBuffer:{getChannelData:() => new Float32Array(4096).fill(value)}});
      for(let i=0;i<8;i++) feed(volume);
      for(let i=0;i<10;i++) feed(0);
    }""", volume)
    page.wait_for_function("liveMessages.some(m => m.type === 'audio')")
    assert page.evaluate("liveMessages.find(m => m.type === 'audio').data.startsWith('UklGR')")
    assert not any(json.loads(body).get("audio_b64") for body in uploads if body)
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")


def test_direct_mic_rejects_background_noise_and_explains_ignored_speech(mobile_page):
    page = mobile_page
    page.locator('#mic-btn').click()
    page.wait_for_function("document.querySelector('#mic-btn').getAttribute('aria-pressed') === 'true'")
    page.evaluate("""() => {
      const feed = value => fakeNodes.at(-1).onaudioprocess({inputBuffer:{getChannelData:() => new Float32Array(4096).fill(value)}});
      for(let i=0;i<20;i++) feed(.005);
      feed(.2);
      for(let i=0;i<20;i++) feed(0);
    }""")
    assert not page.evaluate("liveMessages.some(m => m.type === 'audio')")
    page.evaluate("""() => {
      const feed = value => fakeNodes.at(-1).onaudioprocess({inputBuffer:{getChannelData:() => new Float32Array(4096).fill(value)}});
      for(let i=0;i<8;i++) feed(.025);
      for(let i=0;i<10;i++) feed(0);
    }""")
    page.wait_for_function("liveMessages.some(m => m.type === 'audio')")
    page.evaluate("liveSocket.emit({type:'ignored', id:liveMessages.find(m=>m.type==='audio').id})")
    assert 'Audio ricevuto' in page.locator('.live-controls span').inner_text()
    page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")


def test_direct_mobile_controls_fit_and_stale_audio_is_discarded(mobile_page):
    page = mobile_page
    page.set_viewport_size({"width": 320, "height": 568})
    for selector in [".live-controls", "#console-text"]:
        box = page.locator(selector).bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= 321
    page.locator("#console-text").fill("prima")
    page.locator(".send-btn").click()
    page.wait_for_function("liveMessages.some(m => m.type === 'text')")
    page.evaluate("""() => {
      const id = liveMessages.find(m => m.type === 'text').id;
      liveSocket.emit({type:'accepted', id, prompt:'prima'});
    }""")
    page.get_by_role("button", name="Stop", exact=True).click()
    before = page.evaluate("playedSources.length")
    page.evaluate("liveSocket.emit({type:'audio', id:liveMessages.find(m=>m.type==='text').id, data:btoa('stale')})")
    assert page.evaluate("playedSources.length") == before


def test_direct_connected_data_memory_and_chart_are_mobile_safe(mobile_page):
    page = mobile_page
    page.evaluate("""() => {
      api = async (action) => {
        if (action === 'tradepilot_data') return {connected:true,observed_at:'2026-10-13T12:00:00Z',
          account:{status:'ok',mode:'demo',currency:'EUR',equity:102,balance:100,guard:{day_pct:2,drawdown_pct:0}},
          curve:[{at:'2026-10-13T12:00:00Z',equity:100},{at:'2026-10-13T12:01:00Z',equity:102}],
          research:{updated:'2026-10-13',total_trials:20,eligible_strategies:0},
          experiments:[{id:'EXP-1',title:'<img src=x onerror=alert(1)>',verdict:'research-only',headline:'non validato'}],
          strategy_stats:[{mode:'shadow',strategy_id:'test',trades:20,win_rate:.5,profit_factor:1,expectancy_r:0}]};
        if (action === 'devops_data') return {connected:false,error:'Accesso Microsoft richiesto',builds:[],deployments:[]};
        if (action === 'memories_list') return {memories:window.forgot ? [] : [{id:'abc',kind:'fact',content:'<img src=x>',source:'utente',updated_at:'2026-10-13T12:00:00Z'}]};
        if (action === 'memory_forget') { window.forgot=true; return {status:'disattivata'}; }
        return {ok:true,nodes:[],edges:[],projects:[]};
      };
    }""")
    page.get_by_role('button',name='Equity e deploy',exact=True).click()
    page.locator('.equity-chart').wait_for()
    assert 'demo' in page.locator('#tradepilot-data').inner_text().casefold()
    assert 'Accesso Microsoft richiesto' in page.locator('#devops-data').inner_text()
    page.evaluate("""renderDevOps({connected:true,stages:[
      {name:'Deploy to PROD',status:'succeeded',build_number:'20261013.11',at:'2026-10-13T14:21:57Z'},
      {name:'Deploy to QAS',status:'skipped',build_number:'20261013.11'}],
      job_attention:[{name:'deploy',build_number:'20261013.11',errors:0,warnings:1}]})""")
    assert 'Deploy to PROD · riuscita' in page.locator('#devops-data').inner_text()
    assert 'Deploy to QAS · non eseguita' in page.locator('#devops-data').inner_text()
    assert '1 avvisi' in page.locator('#devops-data').inner_text()
    assert page.locator('#tradepilot-data img, #tradepilot-data script').count() == 0
    bounds=page.locator('#win-projects').bounding_box()
    assert bounds['x'] >= 0 and bounds['x']+bounds['width'] <= 391
    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
    page.locator('[data-toggle="win-brain"]').click()
    page.locator('#learned-memory summary').click()
    page.get_by_role('button',name='Dimentica',exact=True).click()
    page.wait_for_function('window.forgot === true')
    assert page.locator('#memory-items img').count() == 0


def test_direct_mobile_orb_visible_animated_and_paused_in_background(mobile_page):
    page = mobile_page
    page.wait_for_function("document.querySelector('#orb-canvas').width > 0")
    orb = page.locator('#jarvis-orb').bounding_box()
    chat = page.locator('#win-chat').bounding_box()
    assert orb['y'] + orb['height'] <= chat['y']
    assert page.evaluate("""() => {
      const r = document.querySelector('#orb-canvas').getBoundingClientRect();
      return document.elementFromPoint(r.x+r.width/2,r.y+r.height/2)?.id === 'orb-canvas';
    }""")
    page.evaluate("window.orbBefore = document.querySelector('#orb-canvas').toDataURL()")
    page.wait_for_function("document.querySelector('#orb-canvas').toDataURL() !== orbBefore")
    page.evaluate("""() => {
      Object.defineProperty(document,'hidden',{value:true,configurable:true});
      document.dispatchEvent(new Event('visibilitychange'));
      window.orbBefore = document.querySelector('#orb-canvas').toDataURL();
    }""")
    page.wait_for_timeout(150)
    assert page.evaluate("document.querySelector('#orb-canvas').toDataURL() === orbBefore")
    page.evaluate("""() => {
      Object.defineProperty(document,'hidden',{value:false,configurable:true});
      document.dispatchEvent(new Event('visibilitychange'));
    }""")
    page.wait_for_function("document.querySelector('#orb-canvas').toDataURL() !== orbBefore")
