"""Stage additive SSH access with rollback; confirm both fresh connections before cancelling timers."""
import argparse
import base64
import datetime
import hashlib
import io
import ipaddress
import json
from pathlib import Path
import platform as project
import shlex
import tarfile
import zlib

ROOT = Path(__file__).resolve().parents[1]
FILES = ('scripts/remote/admin-access.py', 'scripts/remote/prepare-node.sh')


def prepare(source):
    data = (ROOT/FILES[0]).read_bytes()
    checksum = hashlib.sha256(data).hexdigest()
    encoded = base64.b64encode(zlib.compress(data, 9)).decode()
    # Content-addressed filename: no existing unrelated file is overwritten.
    target = '/root/verda-admin-access-' + checksum[:12] + '.py'
    payload = "python3 - <<'PY'\nimport base64,hashlib,os,pathlib,zlib\n"
    payload += 'data=zlib.decompress(base64.b64decode(' + repr(encoded) + '))\n'
    payload += 'assert hashlib.sha256(data).hexdigest()==' + repr(checksum) + '\n'
    payload += 'p=pathlib.Path(' + repr(target) + ')\n'
    payload += "assert not p.exists() or p.read_bytes()==data, 'Unexpected existing helper'\n"
    payload += 'p.write_bytes(data); p.chmod(0o700)\n'
    payload += "os.execv('/usr/bin/python3',['python3',str(p),'add','--cidr'," + repr(source) + "])\nPY\n"
    directory = ROOT/'.local'
    directory.mkdir(exist_ok=True)
    output = directory/'admin-console-bootstrap.txt'
    output.write_text(payload, encoding='utf-8')
    print('Current-source request:', source)
    print('Readable source:', ROOT/FILES[0])
    print('Console block:', output)
    print('Source SHA256:', checksum)
    print('Execute separately on each VM through an existing root management path; rollback is 10 minutes.')


def sync_scripts(remote, folder):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as archive:
        for file in FILES:
            archive.add(ROOT/file, arcname=file)
    folder = shlex.quote(folder)
    backup = 'install -d -m 700 ' + folder + '/script-backups; '
    for file in FILES:
        target = '/opt/verda-platform/' + file
        backup += 'if test -f ' + shlex.quote(target) + '; then cp -p ' + shlex.quote(target) + ' ' + folder + '/script-backups/' + shlex.quote(Path(file).name) + '; fi; '
    sync = 'set -eu; ' + backup + 'tar --no-same-owner -xzf - -C /opt/verda-platform; '
    sync += 'python3 -m py_compile /opt/verda-platform/scripts/remote/admin-access.py; bash -n /opt/verda-platform/scripts/remote/prepare-node.sh; '
    sync += 'sha256sum ' + ' '.join('/opt/verda-platform/'+file for file in FILES)
    digests = remote.run(sync, 'sync-access-scripts', data=stream.getvalue())
    expected = {file: hashlib.sha256((ROOT/file).read_bytes()).hexdigest() for file in FILES}
    assert all(value in digests for value in expected.values())
    return expected


def stage(source, roles, identity, seconds):
    results = {}
    project.EVIDENCE.mkdir(parents=True, exist_ok=True)
    for role in roles:
        remote = project.Remote(project.CONFIG[role], identity)
        # Copy only access-management scripts; never execute node preparation.
        backup = '/root/verda-platform-backups/access-scripts-' + project.STAMP
        expected = sync_scripts(remote, backup)
        code = '''import importlib.util,json,os,pathlib,socket,subprocess,time
assert socket.gethostname()==EXPECTED_HOST
spec=importlib.util.spec_from_file_location('access','/opt/verda-platform/scripts/remote/admin-access.py')
a=importlib.util.module_from_spec(spec); spec.loader.exec_module(a)
forward=a.run('nft','-j','-a','list','chain','inet','verda_platform','forward')
with a.lock():
    result=a.add(EXPECTED_CIDR,SECONDS)
    s=json.loads(pathlib.Path(result['state_file']).read_text())
    assert a.digest(a.CONFIG.read_text())==s['config_after_sha256']
    assert a.digest(a.REGISTRY.read_text())==s['registry_after_sha256']
    assert a.run('nft','-j','-a','list','chain','inet','verda_platform','forward')==forward
    a.run('systemctl','is-active',s['unit']+'.timer')
    result.update({'ssh_source_during_staging':os.environ['SSH_CONNECTION'].split()[0],
        'expires_at_unix':s['expires_at_unix'],'timer':s['unit']+'.timer','timer_active':True,
        'allowed_cidrs':a.REGISTRY.read_text().splitlines(),'original_input_rules_preserved':True,
        'forward_chain_unchanged':True,'new_source_verified':False})
print(json.dumps(result))
'''.replace('EXPECTED_HOST', repr(project.CONFIG[role+'_name'])).replace('EXPECTED_CIDR', repr(source)).replace('SECONDS', str(seconds))
        result = json.loads(remote.run('python3 -', 'stage-admin-access', data=code.encode()))
        results[role] = {**result, 'access_script_sha256': expected, 'script_backup': backup}
        record = {'status': 'PENDING_USER_WIFI_SWITCH', 'new_source_cidr': source, 'nodes': results,
                  'new_source_verified': False, 'vm_restart_requested': False,
                  'application_or_monitoring_change_requested': False}
        (project.EVIDENCE/'admin-access-pending.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
    print('Requested nodes staged; timers remain active. Await explicit Wi-Fi switch confirmation. Evidence:', project.EVIDENCE)


def confirm(source, roles, identity):
    results = {}
    connections = {}
    # Verify ALL requested hosts over new SSH connections before confirming ANY host.
    for role in roles:
        remote = project.Remote(project.CONFIG[role], identity)
        probe = """import json,os,pathlib,socket
source=os.environ.get('SSH_CONNECTION','').split()[0]
assert source==EXPECTED_SOURCE,'SSH did not originate from the newly approved address'
states=[]
for p in pathlib.Path('/root/verda-platform-backups').glob('verda-admin-*/state.json'):
    s=json.loads(p.read_text())
    if s.get('cidr')==EXPECTED_CIDR and s.get('status')=='PENDING': states.append(p)
assert len(states)==1,'Expected one pending access change; inspect rollback state before retrying'
print(json.dumps({'hostname':socket.gethostname(),'ssh_source':source,'state':str(states[0]),'helper':str(states[0].parent/'admin-access.py')}))
""".replace('EXPECTED_SOURCE', repr(str(ipaddress.ip_network(source).network_address))).replace('EXPECTED_CIDR', repr(source))
        connection = json.loads(remote.run('python3 -', 'fresh-wifi-ssh', data=probe.encode()))
        assert connection['hostname'] == project.CONFIG[role+'_name']
        connections[role] = (remote, connection)
    for role, (remote, connection) in connections.items():
        command = 'python3 ' + shlex.quote(connection['helper']) + ' confirm --state ' + shlex.quote(connection['state'])
        verified = json.loads(remote.run(command, 'confirm-wifi-access'))
        assert verified['status'] == 'CONFIRMED' and verified['verified_ssh_source'] == connection['ssh_source']
        expected = {file: hashlib.sha256((ROOT/file).read_bytes()).hexdigest() for file in FILES}
        digests = remote.run('sha256sum ' + ' '.join('/opt/verda-platform/'+file for file in FILES), 'check-access-scripts')
        assert all(value in digests for value in expected.values())
        results[role] = {**verified, 'access_script_sha256': expected}
    record = {'status': 'PASS', 'verified_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'new_source_cidr': source, 'nodes': results,
              'scope': 'additive SSH /32 only; prior runtime rules preserved; persistent registry and access scripts synchronized',
              'vm_restart_requested': False, 'application_or_monitoring_change_requested': False}
    project.EVIDENCE.mkdir(parents=True, exist_ok=True)
    (project.EVIDENCE/'admin-access.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
    print('Management access confirmed from current Wi-Fi. Evidence:', project.EVIDENCE)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare-console', 'stage', 'confirm'])
    parser.add_argument('--cidr', required=True)
    parser.add_argument('--host', choices=['server', 'worker', 'both'], default='both')
    parser.add_argument('--identity', type=Path, default=Path.home()/'.ssh'/'verda_assignment')
    parser.add_argument('--rollback-seconds', type=int, default=900)
    args = parser.parse_args()
    network = ipaddress.ip_network(args.cidr, strict=True)
    if network.version != 4 or network.prefixlen != 32 or not network.network_address.is_global:
        raise SystemExit('A single public IPv4 /32 is required')
    source = str(network)
    if args.action == 'prepare-console':
        prepare(source)
    elif args.action == 'stage':
        if not 60 <= args.rollback_seconds <= 900:
            raise SystemExit('Rollback must remain enabled for 60–900 seconds')
        stage(source, ['server', 'worker'] if args.host == 'both' else [args.host], args.identity, args.rollback_seconds)
    else:
        confirm(source, ['server', 'worker'] if args.host == 'both' else [args.host], args.identity)
