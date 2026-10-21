import json
from unittest.mock import Mock

import pytest

from core import tradepilot, azure_devops


def account(login=1, equity=100):
    return {'broker': {'login': login, 'server':'broker-demo', 'status':'ok', 'account_type':'demo',
                       'currency':'EUR', 'equity':equity, 'balance':100}}


def test_equity_samples_are_real_deduplicated_and_account_scoped():
    key = tradepilot._record(account(), '2026-10-13T12:00:01+00:00')
    tradepilot._record(account(equity=102), '2026-10-13T12:00:50+00:00')
    tradepilot._record(account(equity=103), '2026-10-13T12:01:01+00:00')
    other = tradepilot._record(account(login=2), '2026-10-13T12:02:01+00:00')
    assert [row['equity'] for row in tradepilot.curve(key)] == [100,103]
    assert len(tradepilot.curve(other)) == 1
    assert tradepilot._record(account(equity=float('nan')), '2026-10-13T12:02:01+00:00') is None
    assert tradepilot._record({'broker':{'status':'unavailable'}}, '2026-10-13T12:02:01+00:00') is None


def test_tradepilot_uses_fixed_gets_and_preserves_modes(monkeypatch):
    tradepilot.CONFIG.write_text(json.dumps({'origin':'https://test.tailnet.ts.net'}))
    calls=[]
    fixtures = {'meta': {'server_time':'2026-10-13T12:00:00+00:00'}, 'account':account(),
                'journal': {'by_strategy':[{'mode':'demo','trades':2},{'mode':'shadow','trades':20}]},
                'research': {'total_trials': None, 'experiments':[]}, 'factory':{}}
    def get(url, **kwargs):
        calls.append((url,kwargs))
        kind = next(k for k,v in tradepilot.ENDPOINTS.items() if url.endswith(v))
        return Mock(status_code=200,json=lambda:fixtures[kind])
    monkeypatch.setattr(tradepilot.requests,'get',get)
    result=tradepilot.snapshot()
    assert result['connected']
    assert result['research']['total_trials'] is None
    assert [x['mode'] for x in result['strategy_stats']] == ['demo','shadow']
    assert len(calls)==5 and all(not kw['allow_redirects'] for _,kw in calls)
    assert 'login' not in result['account'] and 'server' not in result['account']
    assert tradepilot.snapshot() == result and len(calls)==5


def test_tradepilot_unavailable_not_zero_or_fake_curve(monkeypatch):
    tradepilot.CONFIG.write_text(json.dumps({'origin':'https://test.tailnet.ts.net'}))
    monkeypatch.setattr(tradepilot,'_get',Mock(side_effect=ValueError('HTTP401')))
    result=tradepilot.snapshot()
    assert not result['connected'] and result['account']['equity'] is None and not result['curve']


@pytest.mark.parametrize('origin',['https://evil.test','http://test.ts.net','https://test.ts.net@evil.test','https://test.ts.net/api'])
def test_tradepilot_rejects_external_or_credential_urls(origin):
    tradepilot.CONFIG.write_text(json.dumps({'origin':origin}))
    with pytest.raises(ValueError):tradepilot.settings()


def test_deploys_do_not_equate_build_success_with_production(monkeypatch):
    config={'organization':'Iveco','project':'Data Room','project_url':'https://dev.azure.com/Iveco/Data%20Room'}
    calls=[]
    def read(config, headers, path, params=None, release=False):
        calls.append(path)
        if path=='build/builds':return [{'id':1,'definition':{'name':'Data'},'result':'succeeded'}], True
        if path=='release/releases':return [{'name':'Release-3','environments':[{'name':'PRD','status':'notStarted'}]}], False
        if path=='distributedtask/environments':return [{'id':8,'name':'QAS'}],False
        return [{'definition':{'name':'Data'},'result':'failed','finishTime':'2026-10-13T12:00:00Z'}],False
    monkeypatch.setattr(azure_devops,'_read',read)
    result=azure_devops._snapshot(config, {'Authorization':'fake'})
    assert result['connected'] and result['partial']
    assert {d['status'] for d in result['deployments']} == {'failed','notStarted'}
    assert result['builds'][0]['result']=='succeeded'
    assert 'distributedtask/environments/8/environmentdeploymentrecords' in calls


def test_devops_auth_missing_is_explicit(monkeypatch):
    azure_devops.CONFIG.write_text(json.dumps({'project_url':'https://dev.azure.com/Iveco/Data%20Room','tenant':'tenant'}))
    monkeypatch.setattr(azure_devops,'cli_path',lambda:None)
    assert not azure_devops.snapshot()['connected']


def test_devops_never_follows_redirects_or_changes_state(monkeypatch):
    get=Mock(return_value=Mock(status_code=200,json=lambda:{'value':[]},headers={}))
    monkeypatch.setattr(azure_devops.requests,'get',get)
    azure_devops._read({'organization':'Iveco','project':'Data Room'}, {'Authorization':'private'},'release/releases',release=True)
    assert get.call_args.args[0]=='https://vsrm.dev.azure.com/Iveco/Data%20Room/_apis/release/releases'
    assert get.call_args.kwargs['allow_redirects'] is False


def test_devops_partial_permissions_are_not_no_deploys(monkeypatch):
    def read(config, headers, path, params=None, release=False):
        if path=='build/builds':return [],False
        raise ValueError('403')
    monkeypatch.setattr(azure_devops,'_read',read)
    r=azure_devops._snapshot({'project_url':'test'}, {})
    assert r['connected'] and r['partial'] and set(r['errors'])=={'releases','environments','pull_requests'}


def test_devops_rows_carry_who_ran_them(monkeypatch):
    calls=[]
    def read(config, headers, path, params=None, release=False):
        calls.append((path, params))
        if path=='build/builds' and 'buildIds' in params:
            return [{'id':77,'requestedFor':{'displayName':'ROSSI Gabriele'}}],False
        if path=='build/builds':
            return [{'id':1,'definition':{'name':'Data'},'requestedFor':{'displayName':'PUNZI Alessandro'},
                     'triggerInfo':{'ci.message':'Fix fleet KPI'}}],False
        if path=='release/releases':
            return [{'name':'R-1','createdBy':{'displayName':'Build Service'},
                     'environments':[{'name':'PRD','deploySteps':[{'requestedFor':{'displayName':'ROSSI Gabriele'}}]}]}],False
        if path=='distributedtask/environments':return [{'id':8,'name':'QAS'}],False
        if path=='git/pullrequests':
            return [{'title':'Fleet KPI','repository':{'name':'dataroom'},'createdBy':{'displayName':'PUNZI Alessandro'},
                     'status':'completed','closedDate':'2026-10-20T10:00:00Z'}],False
        if path.endswith('/timeline'):return [{'type':'Stage','name':'Deploy to QAS','result':'succeeded'}],False
        return [{'definition':{'name':'Data'},'result':'succeeded','owner':{'id':77}}],False
    monkeypatch.setattr(azure_devops,'_read',read)
    r=azure_devops._snapshot({'project_url':'test'}, {})
    assert r['builds'][0]['by']=='PUNZI Alessandro' and r['builds'][0]['message']=='Fix fleet KPI'
    assert r['stages'][0]['by']=='PUNZI Alessandro'
    assert {d['kind']:d['by'] for d in r['deployments']}=={'classic_release':'ROSSI Gabriele','yaml_environment':'ROSSI Gabriele'}
    assert ('build/builds',{'buildIds':'77'}) in calls
    assert r['pull_requests'][0]['title']=='Fleet KPI' and r['pull_requests'][0]['by']=='PUNZI Alessandro'


def test_pipeline_stages_visible_without_environment_records(monkeypatch):
    def read(config, headers, path, params=None, release=False):
        if path == 'build/builds':
            return [{'id':1172,'buildNumber':'20261013.11','result':'succeeded'}], False
        if path.endswith('/timeline'):
            return [{'type':'Stage','name':'Deploy to PROD','result':'succeeded'},
                    {'type':'Stage','name':'Deploy to QAS','result':'skipped'},
                    {'type':'Job','name':'deploy','result':'succeeded','warningCount':1},
                    {'type':'Task','name':'internal','warningCount':1}], False
        return [],False
    monkeypatch.setattr(azure_devops,'_read',read)
    result = azure_devops._snapshot({'project_url':'test'}, {})
    assert not result['deployments'] and not result['partial']
    assert [(s['name'],s['status']) for s in result['stages']] == [('Deploy to PROD','succeeded'),('Deploy to QAS','skipped')]
    assert len(result['job_attention']) == 1 and result['job_attention'][0]['warnings'] == 1


def test_timeline_response_reads_records(monkeypatch):
    monkeypatch.setattr(azure_devops.requests,'get',Mock(return_value=Mock(status_code=200,
        json=lambda:{'records':[{'type':'Stage'}]},headers={})))
    rows, _ = azure_devops._read({'organization':'Iveco','project':'Data Room'}, {},'build/builds/1172/timeline')
    assert rows == [{'type':'Stage'}]
