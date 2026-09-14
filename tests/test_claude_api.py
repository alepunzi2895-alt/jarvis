import asyncio
from unittest.mock import MagicMock

from core import claude_api


def test_split_sentences_basic():
    complete, rest = claude_api._split_sentences("Ciao Alessandro. Come va? Bene")
    assert complete == ["Ciao Alessandro.", "Come va?"]
    assert rest == "Bene"


def test_split_sentences_no_boundary_yet():
    complete, rest = claude_api._split_sentences("Sto ancora scrivendo")
    assert complete == []
    assert rest == "Sto ancora scrivendo"


def test_split_sentences_trailing_boundary_with_space():
    complete, rest = claude_api._split_sentences("Fatto. ")
    assert complete == ["Fatto."]
    assert rest == ""


def test_split_sentences_trailing_boundary_without_space():
    # Se lo stream finisce esattamente sul terminatore senza spazio dopo,
    # resta nel frammento finale - il flush finale del chiamante (buf.strip()
    # a fine stream, in run_voice_streaming) la recupera comunque.
    complete, rest = claude_api._split_sentences("Fatto.")
    assert complete == []
    assert rest == "Fatto."


def test_run_voice_wrapper_consumes_streaming(monkeypatch):
    """run_voice() e' un thin wrapper su run_voice_streaming(): verifica che
    consumi tutte le frasi e ritorni lo stesso (testo, costo), senza bisogno
    di un client Anthropic vero."""

    async def fake_streaming(prompt, ws, image_b64, result):
        result.text = "risposta finta"
        result.cost = 0.001
        yield "Prima frase."
        yield "Seconda frase."

    monkeypatch.setattr(claude_api, "run_voice_streaming", fake_streaming)

    text, cost = asyncio.run(claude_api.run_voice("ciao", "jarvis"))
    assert text == "risposta finta"
    assert cost == 0.001


class _FakeStream:
    def __init__(self, deltas, usage):
        self._deltas = deltas
        self._usage = usage

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    @property
    def text_stream(self):
        async def _gen():
            for d in self._deltas:
                yield d

        return _gen()

    async def get_final_message(self):
        return MagicMock(usage=self._usage)


class _FakeMessages:
    def __init__(self, deltas, usage):
        self._deltas = deltas
        self._usage = usage

    def stream(self, **kwargs):
        return _FakeStream(self._deltas, self._usage)


class _FakeClient:
    def __init__(self, deltas, usage=None):
        self.messages = _FakeMessages(deltas, usage or MagicMock(input_tokens=1, output_tokens=1))


async def _passthrough(text, *_args):
    return text


def _patch_common(monkeypatch, deltas):
    monkeypatch.setattr(claude_api, "_get_client", lambda: _FakeClient(deltas))
    monkeypatch.setattr(claude_api, "_build_system_prompt", lambda ws: _passthrough("SYSTEM"))
    monkeypatch.setattr("core.browser.extract_and_execute", _passthrough)
    monkeypatch.setattr("core.system_actions.extract_and_execute", _passthrough)


def test_run_voice_streaming_speaks_every_complete_sentence(monkeypatch):
    _patch_common(monkeypatch, ["Ciao Alessandro. ", "Come va? ", "Bene grazie."])

    async def _run():
        result = claude_api.VoiceStreamResult()
        spoken = [
            s async for s in claude_api.run_voice_streaming("ciao", "jarvis", None, result)
        ]
        return spoken, result

    spoken, result = asyncio.run(_run())
    assert spoken == ["Ciao Alessandro.", "Come va?", "Bene grazie."]
    assert result.text == "Ciao Alessandro. Come va? Bene grazie."
    assert result.cost > 0


def test_run_voice_streaming_never_speaks_past_a_fence(monkeypatch):
    _patch_common(
        monkeypatch,
        ["Fatto, apro Chrome. ", "```system\n", '{"action": "open_app"}\n```'],
    )

    async def _run():
        result = claude_api.VoiceStreamResult()
        spoken = [
            s async for s in claude_api.run_voice_streaming("apri chrome", "jarvis", None, result)
        ]
        return spoken, result

    spoken, result = asyncio.run(_run())
    assert spoken == ["Fatto, apro Chrome."]
    assert "open_app" not in " ".join(spoken)
    # il blocco resta nel testo completo (per l'estrazione a valle), solo mai pronunciato
    assert "```system" in result.text
    assert "open_app" in result.text
