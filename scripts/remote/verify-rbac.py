"""Read-only RBAC/availability checks. Run via an existing administrator's SSH session."""
import datetime
import json
import ssl
import subprocess
import sys
import urllib.request

IDENTITY = 'system:serviceaccount:demo:demo-reader'
GROUPS = ['system:serviceaccounts', 'system:serviceaccounts:demo', 'system:authenticated']
IMPERSONATE = ['--as=' + IDENTITY] + ['--as-group=' + group for group in GROUPS]


def command(args):
    return subprocess.run(['k3s', 'kubectl', *args], capture_output=True, text=True, timeout=25)


def get_json(*args):
    result = command(list(args))
    if result.returncode:
        raise RuntimeError(result.stderr)
    return json.loads(result.stdout)


def availability():
    pods = []
    for namespace in ('demo', 'monitoring'):
        for pod in get_json('get', 'pods', '-n', namespace, '-o', 'json')['items']:
            if pod['metadata'].get('deletionTimestamp'):
                raise AssertionError('Unexpected terminating Pod')
            statuses = pod['status'].get('containerStatuses', [])
            assert pod['status']['phase'] == 'Running' and statuses and all(c['ready'] for c in statuses), pod['metadata']['name']
            pods.append({'namespace': namespace, 'name': pod['metadata']['name'],
                         'uid': pod['metadata']['uid'], 'ready': True,
                         'restarts': sum(c['restartCount'] for c in statuses)})
    deployment = get_json('get', 'deployment', 'demo', '-n', 'demo', '-o', 'json')
    assert deployment['status'].get('availableReplicas') == 2
    service_base = '/api/v1/namespaces/monitoring/services/http:'
    grafana = get_json('get', '--raw=' + service_base + 'monitoring-grafana:80/proxy/api/health')
    assert grafana['database'] == 'ok'
    targets = get_json('get', '--raw=' + service_base + 'monitoring-prometheus:9090/proxy/api/v1/targets')
    active = targets['data']['activeTargets']
    assert len(active) == 15 and all(t['health'] == 'up' for t in active)
    app_http = []
    context = ssl.create_default_context(cafile='/etc/verda-platform/tls/demo.crt')
    for scheme in ('http', 'https'):
        for path in ('/', '/healthz'):
            with urllib.request.urlopen(scheme + '://95.133.252.141' + path, timeout=15, context=context) as response:
                body = response.read()
                assert response.status == 200
                if path == '/healthz':
                    assert body == b'ok\n' and response.headers.get_content_type() == 'text/plain'
                else:
                    assert b'The platform is running.' in body
                app_http.append({'url': scheme + '://95.133.252.141' + path, 'http_status': 200})
    return {'pods': sorted(pods, key=lambda p: (p['namespace'], p['name'])),
            'app_available_replicas': 2, 'grafana_database': 'ok',
            'prometheus_targets': {'total': len(active), 'down': 0}, 'app_http': app_http}


def verify():
    checks = []

    def can_i(verb, resource, namespace='demo', allowed=False, subresource=None, all_namespaces=False):
        args = ['auth', 'can-i', verb, resource, *IMPERSONATE]
        args += ['--all-namespaces'] if all_namespaces else ['--namespace=' + namespace]
        if subresource:
            args += ['--subresource=' + subresource]
        result = command(args)
        answer = result.stdout.strip()
        expected = 'yes' if allowed else 'no'
        expected_exit = 0 if allowed else 1
        entry = {'verb': verb, 'resource': resource, 'namespace': '*' if all_namespaces else namespace,
                 'subresource': subresource, 'expected': expected, 'observed': answer,
                 'exit_code': result.returncode, 'passed': answer == expected and result.returncode == expected_exit}
        checks.append(entry)
        assert entry['passed'], {**entry, 'stderr': result.stderr}

    for resource in ('pods', 'services', 'deployments.apps'):
        for verb in ('get', 'list', 'watch'):
            can_i(verb, resource, allowed=True)
        for verb in ('create', 'update', 'patch', 'delete', 'deletecollection'):
            can_i(verb, resource)
    can_i('get', 'pods', allowed=True, subresource='log')
    for verb in ('get', 'list', 'watch', 'create', 'update', 'patch', 'delete', 'deletecollection'):
        can_i(verb, 'secrets')
    for namespace in ('default', 'monitoring', 'kube-system'):
        for resource in ('pods', 'services', 'deployments.apps'):
            for verb in ('get', 'list', 'watch'):
                can_i(verb, resource, namespace=namespace)
        can_i('get', 'pods', namespace=namespace, subresource='log')
    for resource in ('pods', 'services', 'deployments.apps'):
        can_i('list', resource, all_namespaces=True)
    for resource in ('nodes', 'namespaces', 'persistentvolumes', 'clusterroles.rbac.authorization.k8s.io', 'clusterrolebindings.rbac.authorization.k8s.io'):
        for verb in ('get', 'list'):
            can_i(verb, resource)
    for subresource in ('exec', 'attach', 'portforward', 'proxy'):
        for verb in ('get', 'create'):
            can_i(verb, 'pods', subresource=subresource)
    can_i('patch', 'deployments.apps', subresource='scale')
    can_i('update', 'deployments.apps', subresource='scale')
    can_i('create', 'serviceaccounts', subresource='token')
    for resource in ('roles.rbac.authorization.k8s.io', 'rolebindings.rbac.authorization.k8s.io'):
        can_i('create', resource)
    can_i('bind', 'roles.rbac.authorization.k8s.io')
    can_i('escalate', 'roles.rbac.authorization.k8s.io')
    can_i('get', 'configmaps')

    reads = []
    for resource in ('pods', 'services', 'deployments.apps'):
        result = command(['get', resource, '-n', 'demo', '-o', 'name', *IMPERSONATE])
        assert result.returncode == 0 and result.stdout.strip(), result.stderr
        reads.append({'operation': 'list ' + resource, 'exit_code': 0,
                      'resource_count': len(result.stdout.strip().splitlines())})
    result = command(['get', 'pods', '-n', 'demo', '-o', 'json', *IMPERSONATE])
    assert result.returncode == 0, result.stderr
    pod = json.loads(result.stdout)['items'][0]['metadata']['name']
    result = command(['logs', pod, '-n', 'demo', '--tail=1', *IMPERSONATE])
    assert result.returncode == 0, result.stderr
    reads.append({'operation': 'get pods/log', 'exit_code': 0, 'log_contents_recorded': False})

    denied_reads = []
    for args in (['get', 'pods', '-n', 'monitoring', '-o', 'name'], ['get', 'nodes', '-o', 'name']):
        result = command([*args, *IMPERSONATE])
        assert result.returncode != 0 and '(Forbidden)' in result.stderr, result.stderr
        denied_reads.append({'operation': ' '.join(args), 'exit_code': result.returncode,
                             'reason': 'Forbidden'})

    sa = get_json('get', 'serviceaccount', 'demo-reader', '-n', 'demo', '-o', 'json')
    assert sa.get('automountServiceAccountToken') is False
    assert not sa.get('secrets'), 'Unexpected service-account credential Secret'
    role = get_json('get', 'role', 'demo-reader', '-n', 'demo', '-o', 'json')
    binding = get_json('get', 'rolebinding', 'demo-reader', '-n', 'demo', '-o', 'json')
    assert binding['roleRef'] == {'apiGroup': 'rbac.authorization.k8s.io', 'kind': 'Role', 'name': 'demo-reader'}
    return {'identity': IDENTITY, 'impersonation_groups': GROUPS,
            'authorization_checks': checks, 'actual_allowed_reads': reads,
            'actual_forbidden_reads': denied_reads, 'role_rules': role['rules'],
            'service_account_automount': sa['automountServiceAccountToken'],
            'service_account_secret_references': len(sa.get('secrets', [])),
            'role_binding_scope': 'demo', 'availability': availability()}


if __name__ == '__main__':
    result = availability() if sys.argv[1] == 'baseline' else verify()
    print(json.dumps(result, indent=2))
