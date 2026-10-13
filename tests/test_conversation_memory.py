import asyncio
from unittest.mock import AsyncMock

import pytest

from core import conversation_memory as memory, claude_bridge, claude_api
from core.live_server import Engine


def test_exclusions_persist_across_sessions_and_can_be_reversed(monkeypatch):
    model = AsyncMock()
    monkeypatch.setattr(claude_bridge, '_run_claude_api', model)
    async def run():
        spoken = AsyncMock()
        result = await Engine().respond('non mi nominare più Silvia e Alvaro', None, {}, spoken)
        assert 'salvata' in result['result']
        assert not model.called
        assert set(memory.muted_terms()) == {'Silvia', 'Alvaro'}
        assert memory.clean_output('Silvia arriva. Bene il deploy. Alvaro sta bene.') == 'Bene il deploy.'
        # Nuova istanza, nuova cronologia: la preferenza resta su disco.
        assert '[argomento escluso]' in memory.redact_context('Silvia')
        await Engine().respond('puoi tornare a nominare Silvia e Alvaro', None, {}, spoken)
        assert memory.muted_terms() == []
    asyncio.run(run())


@pytest.mark.parametrize('prompt', [
    'ad esempio se ti dico non mi nominare più Silvia',
    'se un collega scrive ricorda che tutto va bene',
    'cosa significa "non mi nominare più Silvia"?',
])
def test_hypothetical_examples_are_not_preferences(prompt):
    assert memory.handle_command(prompt) is None
    assert memory.entries() == []


def test_sources_are_required_and_corrections_replace_facts():
    @memory.request_scope
    async def learn(prompt, ws):
        with pytest.raises(ValueError):
            memory.remember_fact('deploy', 'inventato')
        memory.note_evidence('read_project_file:iveco:STATE.md', 'Il deploy QAS attende approvazione.')
        memory.remember_fact('stato QAS', 'Il deploy QAS attende approvazione.', 'read_project_file:iveco:STATE.md')
        first = memory.remember_fact('scadenza', prompt)
        assert first['status'] == 'salvata'
    asyncio.run(learn('La scadenza è venerdì', 'iveco'))
    asyncio.run(learn('La scadenza è lunedì', 'iveco'))
    rows = memory.entries(workspace='iveco')
    assert len(rows) == 2
    assert any(r['content'] == 'La scadenza è lunedì' for r in rows)
    assert 'Il deploy QAS' in memory.context('iveco')
    assert not memory.context('altro')


def test_forgotten_source_is_not_silently_relearned():
    row = memory.save('project', 'test', 'evidenza', 'iveco', 'read_project_file:iveco:doc.md')
    memory.forget(row['id'])
    memory.save('project', 'test', 'evidenza', 'iveco', 'read_project_file:iveco:doc.md')
    assert memory.entries() == []


def test_no_credential_memory():
    with pytest.raises(ValueError):
        memory.handle_command('ricorda password=abc123')
    assert memory.entries() == []


def test_voice_daemon_remembers_without_model(monkeypatch):
    monkeypatch.setattr(claude_api, '_get_client', lambda: pytest.fail('No model needed'))
    result = asyncio.run(claude_api.run_voice('ricorda che preferisco risposte brevi', 'jarvis'))
    assert result[1] == 0
    assert memory.entries()[0]['kind'] == 'preference'


def test_forget_tool_requires_user_request():
    row = memory.save('fact', 'test', 'Prova')
    @memory.request_scope
    async def call(prompt, ws):
        return memory.forget_requested(row['id'])
    with pytest.raises(ValueError):
        asyncio.run(call('mostra il progetto', 'jarvis'))
    assert asyncio.run(call('dimentica questa memoria', 'jarvis'))['status'] == 'disattivata'


def test_local_recall_works_without_turso():
    memory.handle_command('ricorda che il report QAS scade venerdì', 'iveco')
    output, error = claude_bridge._execute_tool('recall_memory', {'query': 'QAS'}, '.')
    assert not error and 'venerdì' in output
