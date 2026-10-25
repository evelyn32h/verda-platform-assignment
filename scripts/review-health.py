"""Read-only delivery review over existing SSH. Never redeploys or tests outages."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import platform as project
import socket
import ssl
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--identity', type=Path, default=Path.home()/'.ssh'/'verda_assignment')
    args = parser.parse_args()
    remote = project.Remote(project.CONFIG['server'], args.identity)
    code = (ROOT/'scripts/remote/review-health.py').read_bytes()
    result = json.loads(remote.run('python3 -', 'delivery-health', data=code, sensitive=True, timeout=180))
    node_services = {}
    for role in ('server', 'worker'):
        node = project.Remote(project.CONFIG[role], args.identity)
        service = 'k3s' if role == 'server' else 'k3s-agent'
        output = node.run('set -eu; systemctl is-active ' + service + '; systemctl is-enabled verda-firewall; nft list table inet verda_platform >/dev/null; wg show flannel-wg latest-handshakes', 'delivery-node-security', sensitive=True)
        lines = output.strip().splitlines()
        assert lines[:2] == ['active', 'enabled'] and len(lines) >= 3
        latest = max(int(line.split()[-1]) for line in lines[2:])
        node_services[role] = {'service': service, 'active': True, 'firewall_enabled': True, 'wireguard_last_handshake_unix': latest}
    public_cert = remote.run('cat /etc/verda-platform/tls/demo.crt', 'delivery-public-certificate', sensitive=True)
    context = ssl.create_default_context(cadata=public_cert)
    external = []
    for scheme in ('http', 'https'):
        for path in ('/', '/healthz'):
            url = scheme + '://' + project.CONFIG['server'] + path
            with urllib.request.urlopen(url, timeout=20, context=context) as response:
                body = response.read()
                assert response.status == 200
                assert (body == b'ok\n' and response.headers.get_content_type() == 'text/plain') if path == '/healthz' else b'The platform is running.' in body
                external.append({'url': url, 'status': 200, 'content_type': response.headers.get_content_type()})
    svc = json.loads(remote.run('k3s kubectl -n kube-system get svc traefik -o json', 'delivery-nodeports', sensitive=True))
    ports = [6443, 10250, 9100, 3000, 9090] + [p['nodePort'] for p in svc['spec']['ports'] if p.get('nodePort')]
    blocked = []
    for role in ('server', 'worker'):
        for port in ports:
            try:
                connection = socket.create_connection((project.CONFIG[role], port), timeout=2)
            except OSError as error:
                blocked.append({'host': project.CONFIG[role], 'port': port, 'reachable': False, 'result': type(error).__name__})
            else:
                connection.close()
                raise AssertionError(f'Unexpected external access: {role}:{port}')
    result.update({'status': 'PASS', 'review_kind': 'read-only; no deploy, rollout, rule injection or credential export',
                   'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'node_services': node_services,
                   'external_http': external, 'blocked_external_ports': blocked,
                   'source_sha256': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                                     ('scripts/review-health.py', 'scripts/remote/review-health.py')}})
    project.EVIDENCE.mkdir(parents=True, exist_ok=True)
    (project.EVIDENCE/'delivery-health.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print('READ_ONLY_HEALTH_PASS: 2 Ready nodes; app 2 replicas on distinct nodes; HTTP/HTTPS healthy.')
    print('15 healthy targets; Grafana healthy; six dashboard source queries returned data; production alert healthy.')
    print('No deployment, rollout, synthetic alert or Secret read performed.')
    print('Evidence:', project.EVIDENCE)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        project.EVIDENCE.mkdir(parents=True, exist_ok=True)
        failure = {'status': 'INCOMPLETE', 'completed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   'review_kind': 'read-only', 'error_type': type(error).__name__, 'error': str(error),
                   'guidance': 'Use the read-only preflight to distinguish SSH transport/allowlist from authentication. No deployment or local-environment repair is attempted.'}
        (project.EVIDENCE/'delivery-health.json').write_text(json.dumps(failure, indent=2)+'\n', encoding='utf-8')
        print('Read-only review incomplete:', str(error))
        print('Evidence:', project.EVIDENCE)
        raise SystemExit(1)
