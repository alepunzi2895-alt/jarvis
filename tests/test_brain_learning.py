from unittest.mock import MagicMock, patch

from core import brain


def _reply(text: str):
    message = MagicMock()
    block = MagicMock()
    block.text = text
    message.content = [block]
    message.usage = MagicMock()
    return message


def test_learn_stores_durable_fact_without_user_command():
    client = MagicMock()
    client.messages.create.return_value = _reply(
        '{"nodes":[{"label":"Alessandro preferisce Lora","summary":"Font brand AURA.","tags":["preferenza"]}]}'
    )
    with patch("anthropic.Anthropic", return_value=client), \
         patch("core.brain._store") as store, patch("core.brain._bootstrap"), patch("core.costs.record"):
        brain.learn_from_exchange("Per AURA usa sempre Lora come font", "Annotato.", "jarvis", "dashboard")

    payload, workspace = store.call_args.args
    assert payload["nodes"][0]["label"] == "Alessandro preferisce Lora"
    assert workspace == "jarvis"


def test_learn_skips_when_nothing_durable():
    client = MagicMock()
    client.messages.create.return_value = _reply('{"nodes":[]}')
    with patch("anthropic.Anthropic", return_value=client), patch("core.brain._store") as store:
        brain.learn_from_exchange("che ore sono adesso?", "Sono le dieci.", "jarvis", "voice")
    store.assert_not_called()


def test_learn_skips_short_prompt_without_calling_api():
    with patch("anthropic.Anthropic") as anthropic_client:
        brain.learn_from_exchange("ciao", "Buongiorno.", "jarvis", "voice")
    anthropic_client.assert_not_called()


def test_learn_never_raises_on_bad_output():
    client = MagicMock()
    client.messages.create.return_value = _reply("non è JSON")
    with patch("anthropic.Anthropic", return_value=client), patch("core.brain._store") as store:
        brain.learn_from_exchange("Ricordati che lunedì ho la riunione", "Fatto.", "jarvis", "dashboard")
    store.assert_not_called()
