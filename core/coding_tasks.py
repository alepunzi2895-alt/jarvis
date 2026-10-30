"""Lavori Codex/Claude Code locali, tracciati e riprendibili senza bloccare la voce."""
from contextlib import closing
from datetime import datetime, timezone
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
import subprocess
import threading
import uuid

import psutil

from core import feed, projects, conversation_memory as memory
from core.executor_singleton import executor

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / '.coding.sqlite3'
TIMEOUT = 1800
GUIDANCE = ('Sei un agente delegato da JARVIS sul progetto indicato. Segui le regole del repository. '
            'Non inviare messaggi, eseguire trading, deploy, push o azioni distruttive. '
            'Non modificare credenziali o permessi. Se serve una conferma fermati e spiega cosa manca. '
            'Rispondi in italiano con massimo sei righe: esito, modifiche/risultati, verifiche, eventuali blocchi. '
            'Non dichiarare eseguite azioni che non hai verificato.\n\nRichiesta di Alessandro:\n')
IVG_KEY = 'ivgagent'
# IVGAgent lavora su Databricks Iveco: in sessione delegata niente conferme
# possibili, quindi solo il wrapper di lettura al posto di tools/dbx.py.
IVG_DBX = (ROOT / 'core' / 'ivg_dbx.py').as_posix()
IVG_GUIDANCE = (f'Sessione in sola lettura avviata dal pannello IVECO di JARVIS. Per Databricks usa '
                f'`python {IVG_DBX}` al posto di `python tools/dbx.py`, con gli stessi argomenti '
                '(--env test|prod prima del comando): consente solo comandi di lettura e SQL SELECT. '
                'Niente Chrome/Qlik, import, avvio job o scritture: se servono, scrivi il comando esatto '
                'che Alessandro deve lanciare. Indica sempre l\'ambiente usato.\n')


def _db():
    db = sqlite3.connect(DB, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('''CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, provider TEXT, project TEXT, path TEXT, prompt TEXT,
        mode TEXT, status TEXT, result TEXT, session_id TEXT, created_at TEXT,
        finished_at TEXT, owner_pid INTEGER, channel TEXT, worker_pid INTEGER DEFAULT 0)''')
    db.execute("CREATE UNIQUE INDEX IF NOT EXISTS active_project ON jobs(path) WHERE status='running'")
    # Lavori finiti non ancora letti a voce/dashboard (migrazione per DB gia' esistenti).
    if 'announced' not in {row['name'] for row in db.execute('PRAGMA table_info(jobs)')}:
        db.execute('ALTER TABLE jobs ADD COLUMN announced INTEGER DEFAULT 0')
    return db


def _resolve(project):
    found = projects.find(project)
    if not found or not found.path or not Path(found.path).is_dir():
        raise ValueError('Progetto senza cartella locale: usa list_projects.')
    return found.key, str(Path(found.path).resolve())


def _binary(provider):
    if provider not in {'codex', 'claude'}:
        raise ValueError('Agente ammesso: codex oppure claude')
    path = shutil.which(provider)
    # I task Windows possono ereditare un PATH precedente all'installazione.
    if not path:
        candidates = ([Path.home() / '.local/bin/claude.exe'] if provider == 'claude' else
                      list((Path(os.getenv('LOCALAPPDATA', '')) / 'OpenAI/Codex/bin').glob('*/codex.exe')))
        installed = [candidate for candidate in candidates if candidate.is_file()]
        if installed:
            path = str(max(installed, key=lambda candidate: candidate.stat().st_mtime))
    if not path:
        raise ValueError(f'{provider} non installato o non presente nel PATH del servizio.')
    return path


def open_project(provider, project):
    key, path = _resolve(project)
    if provider == 'codex':
        result = subprocess.run([_binary(provider), 'app', path], capture_output=True,
                                timeout=20, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise ValueError('Codex non si e aperto. Controlla installazione desktop.')
    elif provider == 'claude':
        from core.system_executor import _resolve_app_path, _resolve_known_user_app
        exe = _resolve_app_path('code') or _resolve_known_user_app('vs code')
        if not exe:
            candidate = Path.home() / 'AppData/Local/Programs/Microsoft VS Code/Code.exe'
            exe = str(candidate) if candidate.is_file() else None
        if not exe:
            raise ValueError('VS Code non trovato')
        # Aprire una cartella del catalogo non concede permessi di modifica.
        proc = subprocess.Popen([exe, path])
        from core.win_focus import bring_pid_to_foreground_bg
        bring_pid_to_foreground_bg(proc.pid)
        # Chat progetti collegata all'ultima sessione Claude Code di questo progetto.
        try:
            from core import project_chats
            project_chats.prepare(key)
        except Exception:  # noqa: BLE001 — il collegamento e' un di piu', VS Code e' gia' aperto
            pass
    else:
        raise ValueError('Agente ammesso: codex oppure claude')
    return {'opened': provider, 'project': key}


def list_tasks(job_id='', project=''):
    if not DB.exists():
        return []
    with closing(_db()) as db, db:
        for row in db.execute("SELECT id,owner_pid,worker_pid FROM jobs WHERE status='running'").fetchall():
            if not psutil.pid_exists(row['owner_pid']) and not (row['worker_pid'] and psutil.pid_exists(row['worker_pid'])):
                db.execute("UPDATE jobs SET status='interrupted',result=?,finished_at=? WHERE id=?",
                           ('Il servizio e stato riavviato. Verifica lo stato dei file prima di riprendere.',
                            datetime.now(timezone.utc).isoformat(), row['id']))
        rows = db.execute('SELECT * FROM jobs WHERE (?=\'\' OR id=?) AND (?=\'\' OR project=?) ORDER BY created_at DESC LIMIT 10',
                          (job_id, job_id, project, projects.canonical(project)))
        output = []
        for row in rows:
            item = {k: row[k] for k in ('id', 'provider', 'project', 'prompt', 'mode', 'status', 'result', 'session_id', 'created_at', 'finished_at')}
            if not job_id:
                item.update(prompt=item['prompt'][:500], result=item['result'][:1500], truncated=len(item['result']) > 1500)
            output.append(item)
        return output


def start_task(provider, project, prompt, mode='read', previous_job='', explicit=False, channel='web'):
    """explicit: richiesta da un pulsante dedicato (pannello IVECO), non da una
    conversazione: il clic e' gia' la richiesta esplicita di delega."""
    key, path = _resolve(project)
    if key == IVG_KEY and (provider != 'claude' or mode != 'read'):
        raise ValueError('IVGAgent da JARVIS: solo Claude Code in sola lettura.')
    _binary(provider)
    if mode not in {'read', 'edit'} or not isinstance(prompt, str) or not 1 <= len(prompt.strip()) <= 16000:
        raise ValueError('Prompt o modalita non validi')
    if mode == 'edit' and not executor._in_whitelist(path):
        raise ValueError('Cartella disponibile in lettura; modifiche non autorizzate nella configurazione JARVIS.')
    session_id = ''
    if previous_job:
        previous = list_tasks(job_id=previous_job)
        if not previous or previous[0]['provider'] != provider or previous[0]['project'] != key:
            raise ValueError('Il lavoro precedente non appartiene a questo agente/progetto.')
        if previous[0]['status'] == 'running' or not previous[0]['session_id']:
            raise ValueError('Sessione non ancora riprendibile.')
        session_id = previous[0]['session_id']
    request = {'prompt': prompt, 'channel': channel} if explicit else memory.current_request()
    if request is None:
        raise ValueError('La delega richiede una conversazione utente attiva.')
    if not explicit and not previous_job and not re.search(r'\b(codex|claude|vscode|vs code|visual studio|vs studio)\b', request['prompt'], re.I):
        raise ValueError('Delega un nuovo lavoro solo su richiesta esplicita di usare Codex o Claude Code.')
    # Chat progetti / pulsante dedicato: la richiesta esplicita e' gia' l'autorizzazione alle modifiche.
    if mode == 'edit' and not explicit and not re.search(r'\b(modifica|modificare|correggi|sistema|implementa|crea|scrivi|fix|aggiorna)\b', request['prompt'], re.I):
        raise ValueError('La richiesta utente non autorizza modifiche: usa read.')
    list_tasks()  # riconcilia eventuali lavori interrotti
    ident = uuid.uuid4().hex[:12]
    with closing(_db()) as db, db:
        try:
            db.execute('INSERT INTO jobs (id,provider,project,path,prompt,mode,status,result,session_id,created_at,'
                       'finished_at,owner_pid,channel,worker_pid) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (ident, provider, key, path, prompt.strip(), mode, 'running', '', session_id,
                        datetime.now(timezone.utc).isoformat(), '', os.getpid(), request.get('channel', 'web'), 0))
        except sqlite3.IntegrityError:
            raise ValueError('Un agente sta gia lavorando su questo progetto. Consulta il risultato prima di un altro prompt.')
    threading.Thread(target=_run, args=(ident,), daemon=True).start()
    return {'job_id': ident, 'status': 'running', 'provider': provider, 'project': key,
            'notice': 'Prompt inviato in background. Consulta coding_tasks per esito e riassunto; non dichiarare gia concluso.'}


def _command(job):
    if job['provider'] == 'codex':
        cmd = [_binary('codex'), '--no-daemon', '-a', 'never', '-s', 'read-only' if job['mode'] == 'read' else 'workspace-write', 'exec']
        if job['session_id']:
            cmd += ['resume', job['session_id']]
        if os.name == 'nt':
            cmd += ['-c', 'windows.sandbox="unelevated"']
        return cmd + ['--ignore-user-config', '--json', '--skip-git-repo-check', '-']
    if job.get('project') == IVG_KEY:
        cmd = [_binary('claude'), '-p', '--output-format', 'json', '--max-turns', '40',
               '--agent', 'iveco-data-agent', '--permission-mode', 'dontAsk',
               '--permission-prompts', 'none', '--strict-mcp-config',
               '--tools', 'Bash,Read,Glob,Grep,Skill',
               '--allowedTools', f'Bash(python {IVG_DBX} *)', 'Read', 'Glob', 'Grep', 'Skill',
               '--append-system-prompt', IVG_GUIDANCE]
        return cmd + (['--resume', job['session_id']] if job['session_id'] else [])
    tools = 'Read,Glob,Grep' + (',Edit,Write' if job['mode'] == 'edit' else '')
    cmd = [_binary('claude'), '-p', '--output-format', 'json', '--max-turns', '20',
           '--permission-mode', 'acceptEdits' if job['mode'] == 'edit' else 'plan',
           '--permission-prompts', 'none', '--strict-mcp-config', '--tools', tools]
    if job['session_id']:
        cmd += ['--resume', job['session_id']]
    return cmd


def _parse(provider, stdout):
    if provider == 'claude':
        data = json.loads(stdout)
        if data.get('is_error') or data.get('permission_denials'):
            return 'blocked', data.get('result') or 'Agente bloccato da permessi o limite turni.', data.get('session_id', '')
        if not data.get('result'):
            raise ValueError('Nessuna risposta finale da Claude Code')
        return 'done', data['result'], data.get('session_id', '')
    result, session, completed, failed = '', '', False, False
    for line in stdout.splitlines():
        event = json.loads(line)
        if event.get('type') == 'thread.started':
            session = event.get('thread_id', '')
        if event.get('type') in {'turn.failed', 'error'}:
            failed = True
        if event.get('type') == 'turn.completed':
            completed = True
        item = event.get('item') or {}
        if event.get('type') == 'item.completed' and item.get('type') == 'agent_message':
            result = item.get('text', '')
    if failed or not completed or not result:
        raise ValueError('Codex non ha completato il turno; nessun successo confermato.')
    return 'done', result, session


def _run(ident):
    with closing(_db()) as db:
        job = dict(db.execute('SELECT * FROM jobs WHERE id=?', (ident,)).fetchone())
    session = job['session_id']
    try:
        env = os.environ.copy()
        # Non ereditare la sessione del supervisore, ne delegare nuovamente a JARVIS.
        env.pop('CLAUDECODE', None)
        with subprocess.Popen(_command(job), cwd=job['path'], env=env, stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace',
                              creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)) as proc:
            with closing(_db()) as db, db:
                db.execute('UPDATE jobs SET worker_pid=? WHERE id=?', (proc.pid, ident))
            try:
                stdout, _stderr = proc.communicate(GUIDANCE + job['prompt'], timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                raise
            if proc.returncode:
                raise ValueError(f"{job['provider']} terminato con codice {proc.returncode}. Controlla login/permessi nell'app.")
        status, result, session = _parse(job['provider'], stdout)
        result = memory.clean_output(result)
        if len(result) > 16000:
            result = result[:16000] + '\n[risposta troncata: consulta la sessione originale]'
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        status, result = 'error', str(error) if isinstance(error, ValueError) else 'Agente non disponibile o tempo massimo raggiunto.'
    with closing(_db()) as db, db:
        db.execute('UPDATE jobs SET status=?,result=?,session_id=?,finished_at=? WHERE id=?',
                   (status, result, session, datetime.now(timezone.utc).isoformat(), ident))
    if job['channel'] == 'telegram':
        from core.telegram import send_to_owner
        send_to_owner(f"{job['provider']} · {job['project']} · {status}\n{result}\nLavoro {ident}")
        mark_announced(ident)  # Telegram lo ha gia' ricevuto: niente lettura vocale doppia
    # Chat dashboard: il resoconto resta leggibile anche senza Telegram.
    feed.add('claude', f"{job['provider']} · {job['project']} · {status}\n{result}\nLavoro {ident}", prompt=job['prompt'][:300])


_STATUS_IT = {'running': 'ancora in corso', 'done': 'completato', 'blocked': 'bloccato dai permessi o dai turni',
              'error': 'in errore', 'interrupted': 'interrotto'}
_ANNOUNCE_WINDOW = '-6 hours'


def speech_summary(job):
    """Frase breve da leggere a voce: stato e inizio del resoconto, mai il testo intero."""
    text = ' '.join(re.sub(r'[*`#]+', '', job.get('result') or '').split())
    if len(text) > 500:
        text = text[:500].rsplit(' ', 1)[0] + '...'
    return f"Claude Code su {job['project']}: {_STATUS_IT.get(job['status'], job['status'])}. {text}".strip()


def pending_announcements():
    """Lavori finiti da voce o dashboard, non ancora letti. Solo quelli recenti."""
    with closing(_db()) as db, db:
        rows = db.execute("""SELECT * FROM jobs WHERE announced=0 AND status!='running'
                              AND channel IN ('voice','web') AND replace(substr(finished_at,1,19),'T',' ') >= datetime('now', ?)
                              ORDER BY finished_at""", (_ANNOUNCE_WINDOW,)).fetchall()
        return [dict(row) for row in rows]


def mark_announced(job_id):
    with closing(_db()) as db, db:
        db.execute('UPDATE jobs SET announced=1 WHERE id=?', (job_id,))


def record_finished(provider, project, prompt, status, result, path, channel='web'):
    """Registra un turno gia' concluso (chat di progetto): compare in coding_tasks e viene letto a voce."""
    ident = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    with closing(_db()) as db, db:
        db.execute('INSERT INTO jobs (id,provider,project,path,prompt,mode,status,result,session_id,created_at,'
                   'finished_at,owner_pid,channel,worker_pid) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                   (ident, provider, project, path, prompt[:2000], 'edit', status, result[:16000], '',
                    now, now, os.getpid(), channel, 0))
    return ident


def overview(job_id='', project=''):
    """Lavori avviati da JARVIS + sessioni aperte da Alessandro in VS Code,
    terminale o app Codex (core/agent_sessions.py)."""
    from core import agent_sessions
    jobs = list_tasks(job_id, project)
    sessions = [] if job_id else agent_sessions.recent_sessions(exclude_ids={j['session_id'] for j in jobs if j.get('session_id')})
    if project:
        key = projects.canonical(project)
        sessions = [s for s in sessions if s.get('project') and projects.canonical(s['project']) == key]
    return {'jarvis_jobs': jobs, 'open_sessions': sessions,
            'notice': 'open_sessions: sessioni Claude Code/Codex aperte da Alessandro, lette dai transcript locali '
                      '(ultime 6 ore). "al lavoro" = file aggiornato negli ultimi 2 minuti.'}
