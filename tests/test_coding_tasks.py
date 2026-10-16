import asyncio
import json
from contextlib import closing
from unittest.mock import Mock, AsyncMock

import pytest

from core import coding_tasks as tasks, conversation_memory as memory, intents


@pytest.fixture
def coding(monkeypatch, tmp_path):
    monkeypatch.setattr(tasks, '_resolve', lambda project: ('demo', str(tmp_path)))
    monkeypatch.setattr(tasks, '_binary', lambda provider: provider)
    monkeypatch.setattr(tasks.threading, 'Thread', Mock())
    monkeypatch.setattr(tasks.executor, '_in_whitelist', lambda path: True)
    return tasks


def start(prompt='Chiedi a Codex di analizzare il progetto', provider='codex', **kwargs):
    @memory.request_scope
    async def request(prompt, ws, cwd, image, channel):
        return tasks.start_task(provider, 'demo', 'Leggi il progetto', **kwargs)
    return asyncio.run(request(prompt, 'demo', '.', None, 'telegram'))


def test_jobs_return_immediately_and_prevent_concurrent_project_edits(coding):
    job = start()
    assert job['status'] == 'running'
    assert tasks.list_tasks(job_id=job['job_id'])[0]['prompt'] == 'Leggi il progetto'
    with pytest.raises(ValueError, match='gia lavorando'):
        start(provider='claude')


def test_coding_requires_explicit_delegation_and_write_scope(coding, monkeypatch):
    with pytest.raises(ValueError, match='esplicita'):
        start(prompt='Cosa contiene il progetto?')
    with pytest.raises(ValueError, match='non autorizza'):
        start(mode='edit')
    monkeypatch.setattr(tasks.executor, '_in_whitelist', lambda path: False)
    with pytest.raises(ValueError, match='non autorizzate'):
        start(prompt='Codex modifica il progetto', mode='edit')
    assert start()['status'] == 'running'  # lettura resta possibile


def test_success_requires_final_agent_result_and_completed_turn():
    events = [{'type':'thread.started','thread_id':'abc'},
              {'type':'item.completed','item':{'type':'agent_message','text':'Controllato: due file.'}},
              {'type':'turn.completed'}]
    assert tasks._parse('codex', '\n'.join(map(json.dumps, events))) == ('done','Controllato: due file.','abc')
    with pytest.raises(ValueError):
        tasks._parse('codex', '\n'.join(map(json.dumps, events[:-1])))
    assert tasks._parse('claude',json.dumps({'is_error':False,'result':'Manca un permesso','permission_denials':[{}]}))[0] == 'blocked'


def test_result_stored_and_returned_to_originating_telegram(coding, monkeypatch):
    job = start(provider='claude')
    proc = Mock(pid=123, returncode=0)
    proc.communicate.return_value = (json.dumps({'result':'Analisi completa','session_id':'session-1'}),'')
    wrapper = Mock()
    wrapper.__enter__ = Mock(return_value=proc)
    wrapper.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(tasks.subprocess, 'Popen', Mock(return_value=wrapper))
    send = Mock()
    monkeypatch.setattr('core.telegram.send_to_owner', send)
    tasks._run(job['job_id'])
    row = tasks.list_tasks(job_id=job['job_id'])[0]
    assert row['status'] == 'done' and row['result'] == 'Analisi completa'
    assert send.call_count == 1
    follow = start(provider='claude', previous_job=job['job_id'])
    assert tasks.list_tasks(job_id=follow['job_id'])[0]['session_id'] == 'session-1'


def test_cli_policies_keep_sandbox_and_deny_unattended_permissions(coding):
    job = {'provider':'codex','mode':'read','session_id':''}
    cmd = tasks._command(job)
    assert 'read-only' in cmd and '--ignore-user-config' in cmd
    assert not any('bypass' in value for value in cmd)
    cmd = tasks._command(job | {'provider':'claude','mode':'edit'})
    assert cmd[cmd.index('--permission-prompts')+1] == 'none'
    assert 'Bash' not in cmd[cmd.index('--tools')+1]


def test_editor_project_request_not_swallowed_by_generic_app_intent():
    assert intents.parse_intent('apri VS Code su TradePilot') is None
    assert intents.parse_intent('chiudi vs code') == {'type':'close_app','name':'vs code'}


def test_interrupted_jobs_do_not_hide_live_workers(coding, monkeypatch):
    job = start()
    with closing(tasks._db()) as db, db:
        db.execute('UPDATE jobs SET owner_pid=11,worker_pid=22')
    monkeypatch.setattr(tasks.psutil, 'pid_exists', lambda pid: pid == 22)
    assert tasks.list_tasks(job_id=job['job_id'])[0]['status'] == 'running'
    monkeypatch.setattr(tasks.psutil, 'pid_exists', lambda pid: False)
    row = tasks.list_tasks(job_id=job['job_id'])[0]
    assert row['status'] == 'interrupted' and row['finished_at']
    assert start()['status'] == 'running'


def test_failed_launch_is_recorded_and_resume_requires_matching_agent(coding, monkeypatch):
    job = start(provider='claude')
    monkeypatch.setattr(tasks.subprocess, 'Popen', Mock(side_effect=OSError('private environment')))
    monkeypatch.setattr('core.telegram.send_to_owner', Mock())
    tasks._run(job['job_id'])
    row = tasks.list_tasks(job_id=job['job_id'])[0]
    assert row['status'] == 'error' and 'private environment' not in row['result']
    with pytest.raises(ValueError, match='non appartiene'):
        start(previous_job=job['job_id'])


def test_native_voice_uses_same_agent_and_propagates_failures(monkeypatch):
    from core.voice import agent
    async def response(prompt, image, history, emit):
        await emit('Prima frase.')
        return {'result':'Prima frase.', 'cost_usd':0.01}
    monkeypatch.setattr(agent._engine, 'respond', response)
    result = agent.VoiceResult()
    async def read():
        return [s async for s in agent.sentences('riassumi Codex','jarvis',None,result)]
    assert asyncio.run(read()) == ['Prima frase.']
    assert result.cost == .01
    monkeypatch.setattr(agent._engine, 'respond', AsyncMock(side_effect=ValueError('errore reale')))
    with pytest.raises(ValueError, match='errore reale'):
        asyncio.run(read())


def test_ivgagent_runs_claude_read_only_with_dbx_wrapper_only(coding, monkeypatch):
    monkeypatch.setattr(tasks, '_resolve', lambda project: (tasks.IVG_KEY, '.'))
    with pytest.raises(ValueError, match='sola lettura'):
        tasks.start_task('claude', 'IVGAgent', 'x', mode='edit', explicit=True)
    with pytest.raises(ValueError, match='sola lettura'):
        tasks.start_task('codex', 'IVGAgent', 'x', explicit=True)
    # Il pulsante del pannello e' gia' la richiesta esplicita: nessuna conversazione serve.
    job = tasks.start_task('claude', 'IVGAgent', 'Stato dei job in test', explicit=True)
    assert job['project'] == tasks.IVG_KEY
    cmd = tasks._command({'provider': 'claude', 'mode': 'read', 'session_id': '', 'project': tasks.IVG_KEY})
    assert cmd[cmd.index('--permission-mode') + 1] == 'dontAsk'
    assert cmd[cmd.index('--permission-prompts') + 1] == 'none'
    allowed = cmd[cmd.index('--allowedTools') + 1:cmd.index('--append-system-prompt')]
    assert [rule for rule in allowed if rule.startswith('Bash')] == [f'Bash(python {tasks.IVG_DBX} *)']
    assert 'tools/dbx.py' not in ' '.join(allowed)
    assert not any('bypass' in value or 'dangerously' in value for value in cmd)


def test_explicit_flag_is_needed_without_conversation(coding):
    with pytest.raises(ValueError, match='conversazione'):
        tasks.start_task('claude', 'demo', 'Leggi')
