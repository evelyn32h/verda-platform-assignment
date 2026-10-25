"""GET-only delivery health review: no apply, rollout, Secret reads or synthetic alerts."""
import datetime
import json
import ssl
import subprocess
import urllib.parse
import urllib.request

PREFIX = '/api/v1/namespaces/monitoring/services/http:'


def run(*args):
    return subprocess.check_output(list(args), text=True, timeout=30)


def get(*args):
    return json.loads(run('k3s', 'kubectl', '--request-timeout=20s', *args, '-o', 'json'))


def prom(path):
    data = json.loads(run('k3s', 'kubectl', 'get', '--raw=' + PREFIX + 'monitoring-prometheus:9090/proxy' + path))
    assert data['status'] == 'success'
    return data['data']


nodes = get('get', 'nodes')['items']
assert len(nodes) == 2 and all(any(c['type'] == 'Ready' and c['status'] == 'True' for c in n['status']['conditions']) for n in nodes)
pods = get('get', 'pods', '-A')['items']
running = [p for p in pods if p['status']['phase'] != 'Succeeded']
assert all(p['status']['phase'] == 'Running' and p['status'].get('containerStatuses') and all(c['ready'] for c in p['status']['containerStatuses']) for p in running)
app = get('get', 'deployment', 'demo', '-n', 'demo')
assert app['status'].get('availableReplicas') == 2
app_pods = [p for p in pods if p['metadata']['namespace'] == 'demo' and p['metadata'].get('labels', {}).get('app') == 'demo']
assert len(app_pods) == 2 and len({p['spec']['nodeName'] for p in app_pods}) == 2
metric_api = get('get', 'apiservice', 'v1beta1.metrics.k8s.io')
assert any(c['type'] == 'Available' and c['status'] == 'True' for c in metric_api['status']['conditions'])
metrics = run('k3s', 'kubectl', 'top', 'nodes')
services = get('get', 'services', '-n', 'monitoring')['items']
assert all(s['spec']['type'] == 'ClusterIP' for s in services)
claims = get('get', 'pvc', '-n', 'monitoring')['items']
assert len(claims) == 2 and all(c['status']['phase'] == 'Bound' for c in claims)
targets = prom('/api/v1/targets')['activeTargets']
assert len(targets) == 15 and all(t['health'] == 'up' for t in targets)
grafana = json.loads(run('k3s', 'kubectl', 'get', '--raw=' + PREFIX + 'monitoring-grafana:80/proxy/api/health'))
assert grafana['database'] == 'ok'
dashboard = json.loads(get('get', 'configmap', 'verda-platform-dashboard', '-n', 'monitoring')['data']['verda-platform.json'])
assert len(dashboard['panels']) == 6
panel_queries = []
for panel in dashboard['panels']:
    values = prom('/api/v1/query?' + urllib.parse.urlencode({'query': panel['targets'][0]['expr']}))['result']
    assert values, panel['title']
    panel_queries.append({'title': panel['title'], 'series': len(values), 'values': [v['value'][1] for v in values]})
groups = prom('/api/v1/rules?type=alert')['groups']
rules = [r for g in groups for r in g['rules']]
assert len(rules) == 1 and rules[0]['name'] == 'DemoAvailableReplicasLow'
assert rules[0]['state'] == 'inactive' and rules[0]['health'] == 'ok'
rule_objects = get('get', 'prometheusrules', '-n', 'monitoring')['items']
assert [r['metadata']['name'] for r in rule_objects] == ['demo-availability']
managers = prom('/api/v1/alertmanagers')
assert not managers['activeAlertmanagers']
sa = get('get', 'sa', 'demo-reader', '-n', 'demo')
role = get('get', 'role', 'demo-reader', '-n', 'demo')
binding = get('get', 'rolebinding', 'demo-reader', '-n', 'demo')
assert sa.get('automountServiceAccountToken') is False and binding['roleRef']['kind'] == 'Role'
certificate = run('openssl', 'x509', '-in', '/etc/verda-platform/tls/demo.crt', '-noout', '-dates', '-fingerprint', '-sha256')
health = []
context = ssl.create_default_context(cafile='/etc/verda-platform/tls/demo.crt')
for scheme in ('http', 'https'):
    for path in ('/', '/healthz'):
        with urllib.request.urlopen(scheme + '://95.133.252.141' + path, timeout=15, context=context) as response:
            body = response.read()
            assert response.status == 200
            assert (body == b'ok\n' and response.headers.get_content_type() == 'text/plain') if path == '/healthz' else b'The platform is running.' in body
            health.append({'url': scheme + '://95.133.252.141' + path, 'status': response.status, 'content_type': response.headers.get_content_type()})
chart = get('get', 'helmchart', 'monitoring', '-n', 'kube-system')
result = {
    'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'nodes': [{'name': n['metadata']['name'], 'ready': True, 'kubelet': n['status']['nodeInfo']['kubeletVersion']} for n in nodes],
    'running_pods': [{'namespace': p['metadata']['namespace'], 'name': p['metadata']['name'], 'uid': p['metadata']['uid'], 'ready': True, 'restarts': sum(c['restartCount'] for c in p['status']['containerStatuses'])} for p in running],
    'available_app_replicas': 2, 'app_spread_nodes': sorted({p['spec']['nodeName'] for p in app_pods}),
    'metrics_api_available': True, 'node_metrics': metrics,
    'monitoring_services_private': True, 'monitoring_pvcs': [{'name': c['metadata']['name'], 'phase': c['status']['phase'], 'capacity': c['status']['capacity']} for c in claims],
    'prometheus_targets': {'healthy': len(targets), 'down': 0},
    'grafana_health': grafana, 'dashboard_definition_panels': len(dashboard['panels']), 'dashboard_source_queries': panel_queries,
    'grafana_authenticated_browser_or_panel_api_retested_today': False,
    'production_alert': {'name': rules[0]['name'], 'state': rules[0]['state'], 'health': rules[0]['health'], 'duration_seconds': rules[0]['duration']},
    'temporary_alert_rule_resources': 0, 'active_alertmanager_targets': len(managers['activeAlertmanagers']),
    'rbac': {'service_account': sa['metadata']['name'], 'namespace': sa['metadata']['namespace'], 'automount': sa['automountServiceAccountToken'], 'rules': role['rules'], 'role_ref': binding['roleRef']},
    'certificate_metadata': certificate, 'app_http': health,
    'chart_version': chart['spec']['version'],
}
print(json.dumps(result, indent=2))
