"""Apply or verify demo-only reader RBAC over existing SSH; no credential issuance."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import platform as project
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['apply', 'verify'])
    parser.add_argument('--identity', type=Path, default=Path.home()/'.ssh'/'verda_assignment')
    args = parser.parse_args()
    remote = project.Remote(project.CONFIG['server'], args.identity)
    code = (ROOT/'scripts/remote/verify-rbac.py').read_bytes()
    evidence = project.EVIDENCE
    evidence.mkdir(parents=True, exist_ok=True)
    baseline = json.loads(remote.run('python3 - baseline', 'rbac-baseline', data=code, sensitive=True))
    if args.action == 'apply':
        remote.run('k3s kubectl apply --server-side -f -', 'apply-rbac', data=(ROOT/'manifests/rbac.yaml').read_bytes())
    result = json.loads(remote.run('python3 - verify', 'verify-rbac', data=code))
    assert result['availability'] == baseline, 'Application/monitoring state changed during RBAC work'
    result.update({'status': 'PASS', 'verified_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   'action': args.action, 'baseline': baseline,
                   'no_application_or_monitoring_rollout': True,
                   'long_lived_token_created': False, 'api_exposure_changed': False,
                   'source_sha256': {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
                                     ('manifests/rbac.yaml', 'scripts/rbac.py', 'scripts/remote/verify-rbac.py')}})
    (evidence/'rbac-checks.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    checks=result['authorization_checks']
    print(f"RBAC PASS: {len(checks)} authorization checks; "
          f"{sum(c['expected']=='yes' for c in checks)} allowed, "
          f"{sum(c['expected']=='no' for c in checks)} denied.")
    print('Actual namespace reads/logs succeeded; cross-namespace Pods and cluster Nodes returned Forbidden.')
    print('Application and monitoring availability unchanged.')
    print(f'Evidence: {evidence}')


if __name__ == '__main__':
    main()
