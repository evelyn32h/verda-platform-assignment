"""Verify one application alert and a disposable synthetic alert without scaling workloads."""
import datetime
import json
import re
import signal
import subprocess
import sys
import time
import urllib.parse

BASE = '/api/v1/namespaces/monitoring/services/http:monitoring-prometheus:9090/proxy'
NAME = 'DemoAvailableReplicasLow'
EXPRESSION = 'kube_deployment_status_replicas_available{deployment="demo",namespace="demo"} < 2'
TEST_NAME = 'DemoAvailabilitySmokeTest'
RUN = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d%H%M%S')
RESOURCE = 'demo-availability-smoke-' + RUN
GROUP = 'verda.demo.smoke.' + RUN
record = {'status': 'RUNNING', 'started_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'test_resource': {'namespace': 'monitoring', 'name': RESOURCE}, 'observations': []}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def kubectl(*args, data=None):
    result = subprocess.run(['k3s', 'kubectl', '--request-timeout=20s', *args],
                            input=data, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout


def api(path):
    value = json.loads(kubectl('get', '--raw=' + BASE + path))
    assert value['status'] == 'success', value
    return value['data']


def managers():
    resources = json.loads(kubectl('get', 'alertmanager', '-A', '-o', 'json'))
    discovered = api('/api/v1/alertmanagers')
    assert not resources['items'] and not discovered['activeAlertmanagers'], 'Unexpected notification destination; synthetic test refused'
    return {'alertmanager_resources': 0, 'active_alertmanager_targets': 0,
            'external_notification_channel_configured': False, 'delivery_tested': False}


def find_rule(name):
    matches = [(group, rule) for group in api('/api/v1/rules?type=alert')['groups']
               for rule in group['rules'] if rule.get('name') == name]
    assert len(matches) <= 1, 'Duplicate alert name'
    return matches[0] if matches else (None, None)


def wait_for(description, predicate, timeout=180):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            print(now() + ' ' + description, flush=True)
            return value
        time.sleep(2)
    raise TimeoutError(description)


def state(expected, expression):
    group, rule = find_rule(TEST_NAME)
    if not rule or re.sub(r'\s+', '', rule['query']) != re.sub(r'\s+', '', expression):
        return None
    if rule['state'] != expected or rule.get('health') != 'ok' or rule.get('lastError'):
        return None
    if expected in ('pending', 'firing') and not any(a['state'] == expected for a in rule.get('alerts', [])):
        return None
    if expected == 'inactive' and rule.get('alerts'):
        return None
    return {'observed_at': now(), 'state': rule['state'], 'query': rule['query'],
            'last_evaluation': rule.get('lastEvaluation'), 'health': rule['health'],
            'active_alerts': len(rule.get('alerts', [])), 'group_interval_seconds': group['interval']}


def interrupt(signum, frame):
    raise KeyboardInterrupt('Interrupted; cleaning synthetic rule')


for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
    signal.signal(signum, interrupt)

created = False
try:
    record['notifications_before'] = managers()

    def production():
        group, rule = find_rule(NAME)
        if not rule or rule.get('health') != 'ok' or rule.get('lastError'):
            return None
        assert re.sub(r'\s+', '', rule['query']) == re.sub(r'\s+', '', EXPRESSION)
        assert rule['duration'] == 120 and group['interval'] == 15
        assert rule['state'] == 'inactive', 'Application alert unexpectedly active'
        return {'name': rule['name'], 'state': rule['state'], 'query': rule['query'],
                'for_seconds': rule['duration'], 'evaluation_interval_seconds': group['interval'],
                'health': rule['health'], 'source_file': group['file'],
                'last_evaluation': rule.get('lastEvaluation'), 'last_error': rule.get('lastError', '')}

    record['production_rule'] = wait_for('production rule loaded and healthy', production)
    available = api('/api/v1/query?' + urllib.parse.urlencode({'query': 'kube_deployment_status_replicas_available{deployment="demo",namespace="demo"}'}))
    assert len(available['result']) == 1 and float(available['result'][0]['value'][1]) == 2
    record['production_available_replicas'] = 2

    temporary = {'apiVersion': 'monitoring.coreos.com/v1', 'kind': 'PrometheusRule',
                 'metadata': {'name': RESOURCE, 'namespace': 'monitoring',
                              'labels': {'release': 'monitoring', 'verda-test': RUN}},
                 'spec': {'groups': [{'name': GROUP, 'interval': '5s', 'rules': [
                     {'alert': TEST_NAME, 'expr': 'vector(1) < 2', 'for': '30s',
                      'labels': {'severity': 'test', 'test_id': RUN, 'namespace': 'demo', 'deployment': 'demo'},
                      'annotations': {'summary': 'Synthetic availability pipeline test; no application outage'}}]}]}}
    record['temporary_rule'] = temporary
    kubectl('create', '-f', '-', data=json.dumps(temporary))
    created = True
    record['observations'].append(wait_for('synthetic alert Pending', lambda: state('pending', 'vector(1) < 2')))
    record['observations'].append(wait_for('synthetic alert Firing', lambda: state('firing', 'vector(1) < 2')))
    firing = api('/api/v1/alerts')['alerts']
    assert any(a['labels'].get('test_id') == RUN and a['state'] == 'firing' for a in firing)
    record['firing_confirmed_in_alerts_api'] = True

    record['recovery_requested_at'] = now()
    kubectl('patch', 'prometheusrule', RESOURCE, '-n', 'monitoring', '--type=json',
            '-p', json.dumps([{'op': 'replace', 'path': '/spec/groups/0/rules/0/expr', 'value': 'vector(2) < 2'}]))

    def recovered():
        value = state('inactive', 'vector(2) < 2')
        if not value:
            return None
        evaluated = datetime.datetime.fromisoformat(value['last_evaluation'].replace('Z', '+00:00'))
        requested = datetime.datetime.fromisoformat(record['recovery_requested_at'])
        if evaluated <= requested:
            return None
        if any(a['labels'].get('test_id') == RUN for a in api('/api/v1/alerts')['alerts']):
            return None
        return value

    record['observations'].append(wait_for('synthetic alert recovered (Inactive; no active instance)', recovered))
    record['notifications_after'] = managers()
    record['status'] = 'PASS'
except (Exception, KeyboardInterrupt) as error:
    record['status'] = 'FAIL'
    record['error'] = str(error)
finally:
    try:
        if created:
            kubectl('delete', 'prometheusrule', RESOURCE, '-n', 'monitoring', '--ignore-not-found=true', '--wait=true')
        remaining = json.loads(kubectl('get', 'prometheusrules', '-n', 'monitoring', '-o', 'json'))
        assert not any(r['metadata']['name'] == RESOURCE for r in remaining['items'])
        wait_for('synthetic rule unloaded', lambda: find_rule(TEST_NAME)[1] is None)
        assert not any(a['labels'].get('test_id') == RUN for a in api('/api/v1/alerts')['alerts'])
        record['cleanup'] = {'resource_deleted': True, 'rule_unloaded': True, 'active_test_alerts': 0}
        final_group, final_rule = find_rule(NAME)
        assert final_rule and final_rule['state'] == 'inactive' and final_rule['health'] == 'ok'
        record['production_rule_retained'] = True
    except Exception as error:
        record['status'] = 'FAIL'
        record['cleanup_error'] = str(error)
    record['finished_at'] = now()
    print('ALERT_RESULT_JSON=' + json.dumps(record), flush=True)

raise SystemExit(0 if record['status'] == 'PASS' else 1)
