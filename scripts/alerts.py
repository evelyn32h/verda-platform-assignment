"""Apply one app alert and verify its loading plus a synthetic Pending/Firing/recovery cycle."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import platform as project

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['apply-test'])
    parser.add_argument('--identity', type=Path, default=Path.home()/'.ssh'/'verda_assignment')
    args = parser.parse_args()
    remote = project.Remote(project.CONFIG['server'], args.identity)
    availability_code = (ROOT/'scripts/remote/verify-rbac.py').read_bytes()
    baseline = json.loads(remote.run('python3 - baseline', 'alerts-baseline', data=availability_code, sensitive=True))
    remote.run('k3s kubectl apply --server-side -f -', 'apply-alert-rule', data=(ROOT/'manifests/alerts.yaml').read_bytes())
    output = remote.run('python3 -', 'verify-alerts', data=(ROOT/'scripts/remote/verify-alerts.py').read_bytes(), timeout=900)
    result = json.loads(next(line[len('ALERT_RESULT_JSON='):] for line in output.splitlines() if line.startswith('ALERT_RESULT_JSON=')))
    assert result['status'] == 'PASS'
    after = json.loads(remote.run('python3 - baseline', 'alerts-after', data=availability_code, sensitive=True))
    assert baseline == after, 'Application or monitoring state changed during alert verification'
    result.update({'availability_before': baseline, 'availability_after': after,
                   'no_application_or_monitoring_rollout': True, 'no_external_notifications_sent': True,
                   'source_sha256': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                                     ('manifests/alerts.yaml', 'scripts/alerts.py', 'scripts/remote/verify-alerts.py')}})
    project.EVIDENCE.mkdir(parents=True, exist_ok=True)
    (project.EVIDENCE/'alert-checks.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print('ALERTS PASS: production rule loaded; synthetic Pending -> Firing -> Inactive; test rule removed.')
    print('Application and monitoring availability unchanged. No notification delivery configured or tested.')
    print('Evidence:', project.EVIDENCE)


if __name__ == '__main__':
    main()
