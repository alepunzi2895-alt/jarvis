"""Stato deploy Iveco da API GET: build, release classiche e ambienti YAML."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time
from urllib.parse import quote, urlsplit, unquote

import requests

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / '.azure-devops.json'
AUTH_DIR = ROOT / '.azure-auth'
RESOURCE = '499b84ac-1321-427f-aa17-267ca6975798'
_lock = threading.Lock()
_token = {'value': '', 'expires': 0, 'tenant': ''}
_cache = {'value': None, 'at': 0, 'key': ''}


def cli_path():
    candidates = [shutil.which('az')]
    for variable in ('ProgramFiles', 'ProgramFiles(x86)'):
        if os.getenv(variable):
            candidates.append(str(Path(os.environ[variable]) / 'Microsoft SDKs/Azure/CLI2/wbin/az.cmd'))
    return next((p for p in candidates if p and Path(p).is_file()), None)


def settings():
    if not CONFIG.exists():
        raise ValueError('Azure DevOps non configurato.')
    config = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
    parsed = urlsplit(config['project_url'])
    parts = [unquote(p) for p in parsed.path.strip('/').split('/')]
    if parsed.scheme != 'https' or parsed.netloc != 'dev.azure.com' or len(parts) != 2 or any('/' in p or '\\' in p for p in parts):
        raise ValueError('URL progetto Azure DevOps non valido')
    return config | {'organization': parts[0], 'project': parts[1]}


def auth_headers(config):
    tenant = config['tenant']
    if _token['tenant'] == tenant and _token['expires'] > time.time() + 90:
        return {'Authorization': 'Bearer ' + _token['value']}
    cli = cli_path()
    if not cli:
        raise ValueError('Accesso Microsoft richiesto: Azure CLI non installata sul PC.')
    env = os.environ | {'AZURE_CONFIG_DIR': str(AUTH_DIR)}
    result = subprocess.run([cli, 'account', 'get-access-token', '--tenant', tenant,
                             '--resource', RESOURCE, '--output', 'json', '--only-show-errors'],
                            capture_output=True, text=True, timeout=25, env=env,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise ValueError('Accesso Microsoft da completare o rinnovare sul PC con setup_devops.ps1.')
    data = json.loads(result.stdout)
    _token.update(value=data['accessToken'], expires=float(data.get('expires_on', time.time() + 300)), tenant=tenant)
    return {'Authorization': 'Bearer ' + data['accessToken']}


def _read(config, headers, path, params=None, release=False):
    host = 'vsrm.dev.azure.com' if release else 'dev.azure.com'
    base = f"https://{host}/{quote(config['organization'], safe='')}/{quote(config['project'], safe='')}/_apis/"
    response = requests.get(base + path, headers=headers, params={'api-version': '7.1', **(params or {})},
                            timeout=12, allow_redirects=False)
    if response.status_code != 200:
        raise ValueError(f'Fonte Azure DevOps non disponibile (HTTP {response.status_code}); verifica accesso/permessi.')
    data = response.json()
    return data.get('records' if path.endswith('/timeline') else 'value', []), bool(response.headers.get('x-ms-continuationtoken'))


def snapshot():
    try:
        config = settings()
        with _lock:
            key = config['project_url']
            if _cache['key'] == key and time.monotonic() - _cache['at'] < 30:
                return _cache['value']
            headers = auth_headers(config)
            result = _snapshot(config, headers)
            _cache.update(value=result, key=key, at=time.monotonic())
            return result
    except (ValueError, KeyError, OSError, subprocess.SubprocessError):
        return {'connected': False, 'error': 'Accesso Microsoft Azure DevOps da completare o rinnovare sul PC.',
                'builds': [], 'deployments': [], 'partial': True}


def _snapshot(config, headers):
    errors, partial, collections = {}, [], {}
    requests_by_kind = {
        'builds': ('build/builds', {'$top': 30, 'queryOrder': 'queueTimeDescending', 'maxBuildsPerDefinition': 1}, False),
        'releases': ('release/releases', {'$top': 20, '$expand': 'environments', 'queryOrder': 'descending'}, True),
        'environments': ('distributedtask/environments', {'$top': 30}, False),
    }
    def read(kind):
        path, params, release = requests_by_kind[kind]
        try:
            rows, more = _read(config, headers, path, params, release)
            return kind, rows, more, None
        except (requests.RequestException, ValueError):
            return kind, [], False, 'Dati non disponibili: accesso o permessi da verificare'
    with ThreadPoolExecutor(max_workers=3) as pool:
        for kind, rows, more, error in pool.map(read, requests_by_kind):
            collections[kind] = rows
            if more:
                partial.append(kind)
            if error:
                errors[kind] = error
    builds = [{
        'id': row.get('id'), 'name': (row.get('definition') or {}).get('name'),
        'number': row.get('buildNumber'), 'branch': row.get('sourceBranch'),
        'status': row.get('status'), 'result': row.get('result'),
        'at': row.get('finishTime') or row.get('startTime') or row.get('queueTime'),
    } for row in collections['builds']]
    stages, job_attention = [], []
    def timeline(build):
        try:
            rows, _ = _read(config, headers, f"build/builds/{int(build['id'])}/timeline")
            return build, rows, None
        except (requests.RequestException, ValueError):
            return build, [], 'Fasi pipeline non disponibili'
    if len(builds) > 10:
        partial.append('timelines')
    with ThreadPoolExecutor(max_workers=3) as pool:
        for build, rows, error in pool.map(timeline, builds[:10]):
            if error:
                errors['timeline:' + str(build['id'])] = error
            for row in rows:
                is_stage = row.get('type') == 'Stage'
                if not is_stage and not (row.get('type') == 'Job' and (row.get('errorCount') or row.get('warningCount'))):
                    continue
                item = {'build_id': build['id'], 'build_number': build['number'], 'pipeline': build['name'],
                        'name': row.get('name'), 'status': row.get('result') or row.get('state', 'unknown'),
                        'at': row.get('finishTime') or row.get('startTime'),
                        'errors': row.get('errorCount', 0), 'warnings': row.get('warningCount', 0)}
                (stages if is_stage else job_attention).append(item)
    deployments = []
    for release in collections['releases']:
        for environment in release.get('environments') or []:
            steps = environment.get('deploySteps') or []
            attempt = steps[-1] if steps else {}
            deployments.append({
                'kind': 'classic_release', 'name': (release.get('releaseDefinition') or {}).get('name', '') + ' / ' + release.get('name', ''),
                'environment': environment.get('name'), 'status': environment.get('status', 'unknown'),
                'at': attempt.get('lastModifiedOn') or attempt.get('queuedOn'),
                'release_created_at': release.get('createdOn'), 'id': release.get('id'),
                'pending_approvals': sum(a.get('status') == 'pending' for a in
                                         (environment.get('preDeployApprovals') or []) + (environment.get('postDeployApprovals') or [])),
            })
    def environment_history(environment):
        ident = int(environment['id'])
        try:
            rows, more = _read(config, headers, f'distributedtask/environments/{ident}/environmentdeploymentrecords', {'top': 5})
            return environment, rows, more, None
        except (requests.RequestException, ValueError):
            return environment, [], False, 'Storico ambiente non disponibile'
    with ThreadPoolExecutor(max_workers=3) as pool:
        for env, rows, more, error in pool.map(environment_history, collections['environments'][:30]):
            label = env.get('name', str(env['id']))
            if more:
                partial.append('environment:' + label)
            if error:
                errors['environment:' + label] = error
            for row in rows:
                deployments.append({'kind': 'yaml_environment', 'name': (row.get('definition') or {}).get('name') or row.get('jobName'),
                                    'environment': label, 'status': row.get('result') or ('inProgress' if row.get('startTime') else 'queued'),
                                    'at': row.get('finishTime') or row.get('startTime') or row.get('queueTime'),
                                    'id': row.get('id')})
    deployments.sort(key=lambda row: row.get('at') or row.get('release_created_at') or '', reverse=True)
    return {'connected': any(kind not in errors for kind in requests_by_kind), 'source': config['project_url'],
            'observed_at': datetime.now(timezone.utc).isoformat(), 'builds': builds, 'deployments': deployments,
            'stages': stages, 'job_attention': job_attention,
            'errors': errors, 'partial': bool(partial or errors), 'more_available': partial,
            'notice': 'Ultima build per pipeline (massimo 30), ultime 20 release e 5 deploy per ambiente (massimo 30 ambienti). '
                      'Fasi delle prime 10 build dalla timeline, anche senza Azure Environments. '
                      'Una build riuscita non prova il rilascio in produzione; fa fede lo stato della fase di deploy. '
                      'Skipped significa fase non eseguita, non errore. N/A indica dato non disponibile.'}
