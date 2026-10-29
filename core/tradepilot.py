"""TradePilot privato: richieste GET fisse, curva da campioni reali, nessun comando."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import threading
import time
from urllib.parse import urlsplit

import requests

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / '.tradepilot.json'
DB = ROOT / '.tradepilot.sqlite3'
_lock = threading.Lock()
_cache = {'at': 0, 'value': None, 'key': ''}
# La VPS di TradePilot e' piccola (1,6 GB, in paging): /api/autopilot ha impiegato 11-12 s.
# Con 8 s il PC la dava per irraggiungibile anche quando era viva. Ultimo valido per endpoint:
# se una risposta manca, si mostra quella precedente e non il vuoto.
TIMEOUT_SEC = float(__import__('os').getenv('JARVIS_TRADEPILOT_TIMEOUT_SEC', '25'))
_last_good = {}
ENDPOINTS = {'meta': '/api/meta', 'account': '/api/autopilot',
             'journal': '/api/journal?limit=1', 'research': '/api/research', 'factory': '/api/factory?top=5'}


def settings():
    if not CONFIG.exists():
        return None
    config = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
    parsed = urlsplit(config.get('origin', ''))
    private = parsed.hostname in {'localhost', '127.0.0.1'} or (parsed.hostname or '').endswith('.ts.net')
    if not private or parsed.scheme not in {'http', 'https'} or (parsed.scheme != 'https' and parsed.hostname not in {'localhost', '127.0.0.1'}):
        raise ValueError('TradePilot richiede HTTPS Tailscale oppure loopback locale')
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {'', '/'}:
        raise ValueError('Usa solo l\'origine privata TradePilot')
    config['origin'] = config['origin'].rstrip('/')
    # Dashboard pubblica in sola lettura (D042), solo come link nel pannello.
    link = urlsplit(config.get('dashboard_url', ''))
    config['dashboard_url'] = config['dashboard_url'] if link.scheme == 'https' and link.hostname else None
    return config


def _get(config, kind):
    headers = {'X-TradePilot-Remote-Key': config['remote_key']} if config.get('remote_key') else {}
    response = requests.get(config['origin'] + ENDPOINTS[kind], headers=headers, timeout=TIMEOUT_SEC, allow_redirects=False)
    if response.status_code != 200:
        raise ValueError(f'TradePilot {kind}: HTTP {response.status_code}')
    return response.json()


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _record(account, timestamp):
    broker = account.get('broker') or {}
    if broker.get('status') != 'ok':
        return None
    equity = _number(broker.get('equity'))
    if equity is None or broker.get('login') is None or not broker.get('server') or not broker.get('currency'):
        return None
    at = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    if at.tzinfo is None:
        raise ValueError('Timestamp conto senza fuso orario')
    ident = hashlib.sha256(json.dumps([broker['login'], broker['server'], broker['currency'],
                                     broker.get('account_type')]).encode()).hexdigest()[:20]
    with closing(sqlite3.connect(DB, timeout=5)) as db, db:
        db.execute('''CREATE TABLE IF NOT EXISTS equity (
            account TEXT NOT NULL, minute TEXT NOT NULL, at TEXT NOT NULL,
            equity REAL NOT NULL, balance REAL, currency TEXT NOT NULL,
            mode TEXT NOT NULL, PRIMARY KEY(account,minute))''')
        db.execute('INSERT OR IGNORE INTO equity VALUES (?,?,?,?,?,?,?)',
                   (ident, at.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M'), timestamp, equity,
                    _number(broker.get('balance')), broker['currency'], broker.get('account_type') or 'unknown'))
    return ident


def curve(account):
    if not account or not DB.exists():
        return []
    with closing(sqlite3.connect(DB, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute('SELECT at,equity,balance FROM equity WHERE account=? ORDER BY at DESC LIMIT 1440', (account,))
        return list(reversed([dict(row) for row in rows]))


def sample_account():
    config = settings()
    if not config:
        return None
    meta, account = _get(config, 'meta'), _get(config, 'account')
    return _record(account, meta['server_time'])


def snapshot():
    config = settings()
    if not config:
        return {'connected': False, 'error': 'Collegamento privato TradePilot non configurato.'}
    with _lock:
        if _cache['key'] == str(CONFIG) + config['origin'] and time.monotonic() - _cache['at'] < 20:
            return _cache['value']
        data, errors = {}, {}
        def read(kind):
            try:
                return kind, _get(config, kind), None
            except (requests.RequestException, ValueError, KeyError):
                return kind, None, 'Fonte non raggiungibile o accesso negato'
        with ThreadPoolExecutor(max_workers=len(ENDPOINTS)) as pool:
            for kind, result, error in pool.map(read, ENDPOINTS):
                if result is not None:
                    _last_good[kind] = result
                elif kind in _last_good:
                    result = _last_good[kind]
                    error = None
                    errors[kind] = 'Ultimo dato ricevuto: la VPS non ha risposto in tempo'
                data[kind] = result or {}
                if error:
                    errors[kind] = error
        broker = data['account'].get('broker') or {}
        stamp = data['meta'].get('server_time')
        ident = _record(data['account'], stamp) if stamp and not errors.get('account') else None
        points = curve(ident)
        research, factory = data['research'], data['factory']
        strategies = data['account'].get('strategies', [])
        counts = {}
        for row in strategies:
            key = row.get('status', 'unknown')
            counts[key] = counts.get(key, 0) + 1
        out = {
            'connected': bool(stamp and not errors.get('account')), 'source': config['origin'],
            'observed_at': stamp, 'errors': errors, 'account': {
                'status': broker.get('status', 'unavailable'), 'mode': broker.get('account_type', 'unknown'),
                'currency': broker.get('currency'), 'equity': _number(broker.get('equity')),
                'balance': _number(broker.get('balance')), 'account_ref': ident,
                'guard': {k: _number((data['account'].get('guard') or {}).get(k))
                          for k in ('day_pct', 'week_pct', 'drawdown_pct')},
            },
            'curve': points, 'curve_started_at': points[0]['at'] if points else None,
            'curve_note': 'Ultimi 1440 campioni raccolti da JARVIS, uno al minuto mentre il servizio PC e\' attivo. '
                          'Equity del conto, non rendimento: comprende posizioni aperte ed eventuali versamenti/prelievi. '
                          'Lo storico precedente al collegamento non e\' disponibile.',
            'strategy_counts': counts,
            'strategies': [{k: row.get(k) for k in ('id', 'status', 'evidence', 'suspension', 'trial_paused')} for row in strategies],
            # Nessun aggregato misto demo/shadow/counterfactual: conserva i denominatori nativi.
            'strategy_stats': data['journal'].get('by_strategy', []),
            'research': {k: research.get(k) for k in ('updated', 'cumulative_trials', 'factory_trials', 'total_trials', 'eligible_strategies')},
            'experiments': research.get('experiments', []),
            'factory': {k: factory.get(k) for k in ('n_trials', 'batches', 'survivors', 'updated', 'last_batch', 'leaderboard')},
            'dashboard_url': config['dashboard_url'],
            'notice': 'Dati della VPS TradePilot. Demo, shadow e ricerca sono distinti; nessun comando operativo da JARVIS.',
        }
        _cache.update(at=time.monotonic(), key=str(CONFIG) + config['origin'], value=out)
        return out


def summary(section='overview', offset=0):
    data = snapshot()
    if section not in {'overview', 'research', 'strategies'} or not isinstance(offset, int) or offset < 0:
        raise ValueError('Sezione o offset non valido')
    common = {k: data.get(k) for k in ('connected', 'source', 'observed_at', 'error', 'errors', 'notice')}
    if section == 'overview':
        return common | {k: data.get(k) for k in ('account', 'research', 'strategy_counts', 'curve_started_at', 'curve_note')}
    key = 'experiments' if section == 'research' else 'strategy_stats'
    rows = data.get(key, [])
    if section == 'research':
        rows = list(reversed(rows))
    page_size = 6 if section == 'research' else 15
    return common | {'section': section, 'total': len(rows), 'items': rows[offset:offset + page_size],
                     'next_offset': offset + page_size if offset + page_size < len(rows) else None,
                     'factory': data.get('factory') if section == 'research' else None}
