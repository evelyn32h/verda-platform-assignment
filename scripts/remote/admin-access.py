"""Add one IPv4 /32 SSH source with a timed rollback; never reload the firewall."""
import argparse
import contextlib
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
import uuid

CONFIG = Path('/etc/verda-platform/firewall.nft')
REGISTRY = Path('/etc/verda-platform/admin-cidrs.txt')
BACKUPS = Path('/root/verda-platform-backups')
MANAGED = Path('/etc/verda-platform/managed')
SSH_LINE = re.compile(r'(?m)^(?P<indent>[ \t]*)ip saddr (?P<cidr>[0-9./]+) tcp dport 22 accept[^\n]*$')


def cidr(value):
    network = ipaddress.ip_network(value, strict=True)
    if network.version != 4 or network.prefixlen != 32:
        raise ValueError('Administrative sources must be individual IPv4 /32 addresses')
    return str(network)


def collect(config, registry, current):
    values = [m.group('cidr') for m in SSH_LINE.finditer(config)]
    values += [line.split('#', 1)[0].strip() for line in registry.splitlines()]
    values.append(current)
    return sorted({cidr(value if '/' in value else value + '/32') for value in values if value})


def run(*args, data=None):
    result = subprocess.run(list(args), input=data, text=True, capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    return result.stdout


def rules():
    return [item['rule'] for item in json.loads(run('nft', '-j', '-a', 'list', 'chain', 'inet', 'verda_platform', 'input'))['nftables'] if 'rule' in item]


def ssh_source(rule):
    expressions = rule.get('expr', [])
    if not any('accept' in item for item in expressions):
        return None
    tcp22 = any(item.get('match', {}).get('left', {}).get('payload') == {'protocol': 'tcp', 'field': 'dport'}
                and item['match'].get('right') == 22 for item in expressions)
    if not tcp22:
        return None
    for item in expressions:
        match = item.get('match', {})
        if match.get('left', {}).get('payload') == {'protocol': 'ip', 'field': 'saddr'}:
            value = match['right']
            if isinstance(value, dict) and 'prefix' in value:
                value = str(value['prefix']['addr']) + '/' + str(value['prefix']['len'])
            if isinstance(value, str):
                return cidr(value if '/' in value else value + '/32')
    return None


def atomic(path, text, mode=0o600):
    stat = path.stat() if path.exists() else None
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix='.admin-access-')
    try:
        with os.fdopen(descriptor, 'w') as output:
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.chmod(name, stat.st_mode & 0o777 if stat else mode)
        if stat:
            os.chown(name, stat.st_uid, stat.st_gid)
        os.replace(name, path)
    finally:
        if Path(name).exists():
            Path(name).unlink()


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def remove_owned_line(text, marker, source):
    kept = []
    for line in text.splitlines(keepends=True):
        if marker not in line:
            kept.append(line)
            continue
        match = SSH_LINE.fullmatch(line.rstrip('\n'))
        if not match or cidr(match.group('cidr')) != source:
            raise RuntimeError('Tagged persistent line is outside the permitted SSH change')
    return ''.join(kept)


def no_pending_change():
    for file in BACKUPS.glob('verda-admin-*/state.json'):
        if json.loads(file.read_text()).get('status') == 'PENDING':
            raise RuntimeError('An admin-access change is pending; confirm or roll it back first: ' + str(file))


def save(state_path, state):
    atomic(state_path, json.dumps(state, indent=2) + '\n')


@contextlib.contextmanager
def lock():
    import fcntl
    with open('/run/lock/verda-admin-access.lock', 'a') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def rollback(state_path):
    state = json.loads(state_path.read_text())
    if state['status'] != 'PENDING':
        return state
    # Delete only this operation's uniquely tagged SSH rule, leaving all others intact.
    for rule in rules():
        if rule.get('comment') == state['comment']:
            assert ssh_source(rule) == state['cidr']
            run('nft', 'delete', 'rule', 'inet', 'verda_platform', 'input', 'handle', str(rule['handle']))
    for key, path in (('config', CONFIG), ('registry', REGISTRY)):
        before = state[key + '_before']
        if path.exists() and digest(path.read_text()) == state[key + '_after_sha256']:
            if before is None:
                path.unlink()
            else:
                atomic(path, before)
        elif path.exists():
            # Preserve concurrent edits rather than replacing the whole configuration.
            text = path.read_text()
            if key == 'config':
                text = remove_owned_line(text, state['comment'], state['cidr'])
            else:
                text = ''.join(line for line in text.splitlines(keepends=True) if line.strip() != state['cidr'])
            atomic(path, text)
    state['status'] = 'ROLLED_BACK'
    state['rolled_back_at_unix'] = time.time()
    save(state_path, state)
    return state


def add(source, seconds):
    if socket.gethostname() not in ('verda-k3s-server', 'verda-k3s-worker') or not MANAGED.exists():
        raise RuntimeError('Unexpected or unmanaged VM; stopped without changes')
    no_pending_change()
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'verda-firewall-rollback.timer'], timeout=15).returncode == 0:
        raise RuntimeError('The original firewall rollback timer is active; resolve it first')
    old_config = CONFIG.read_text()
    old_registry = REGISTRY.read_text() if REGISTRY.exists() else None
    before = rules()
    if source in [ssh_source(rule) for rule in before]:
        raise RuntimeError('Source already allowed; inspect/confirm any pending operation instead of duplicating it')
    if source in collect(old_config, old_registry or '', ''):
        raise RuntimeError('Source already exists in persistent policy; inspect runtime/configuration drift first')
    legacy_rule = next((rule for rule in before if ssh_source(rule)), None)
    match = SSH_LINE.search(old_config)
    if not legacy_rule or not match:
        raise RuntimeError('Expected existing SSH source rule missing; refusing to rewrite the firewall')
    allowed = collect(old_config, old_registry or '', source)
    marker = 'verda-admin-' + uuid.uuid4().hex[:12]
    line = match.group('indent') + 'ip saddr ' + source + ' tcp dport 22 accept comment "' + marker + '"\n'
    new_config = old_config[:match.start()] + line + old_config[match.start():]
    new_registry = '\n'.join(allowed) + '\n'
    insertion = f'insert rule inet verda_platform input position {int(legacy_rule["handle"])} ip saddr {source} tcp dport 22 accept comment "{marker}"\n'
    run('nft', '-c', '-f', '-', data=insertion)
    run('nft', '-c', '-f', '-', data=new_config)
    folder = BACKUPS / marker
    folder.mkdir(mode=0o700, parents=True)
    state_path = folder/'state.json'
    helper = folder/'admin-access.py'
    shutil.copyfile(Path(__file__).resolve(), helper)
    helper.chmod(0o700)
    state = {'status': 'PENDING', 'hostname': socket.gethostname(), 'cidr': source, 'comment': marker,
             'unit': marker + '-rollback', 'expires_at_unix': time.time() + seconds,
             'config_before': old_config, 'registry_before': old_registry,
             'config_after_sha256': digest(new_config), 'registry_after_sha256': digest(new_registry),
             'original_rules': before,
             'original_rule_handles': [rule['handle'] for rule in before]}
    save(state_path, state)
    # The timer is armed before changing either runtime or persistent policy.
    run('systemd-run', '--unit=' + state['unit'], '--on-active=' + str(seconds) + 's',
        '/usr/bin/python3', str(helper), 'rollback', '--state', str(state_path))
    try:
        run('nft', '-f', '-', data=insertion)
        atomic(CONFIG, new_config)
        atomic(REGISTRY, new_registry)
        after = rules()
        assert [r for r in after if r.get('comment') != marker] == before, 'Unexpected change to original runtime rules'
        assert any(r.get('comment') == marker and ssh_source(r) == source for r in after)
    except Exception:
        rollback(state_path)
        raise
    return {'status': 'PENDING', 'hostname': state['hostname'], 'cidr': source,
            'state_file': str(state_path), 'rollback_seconds': seconds,
            'confirm_from_new_ssh': f'python3 {helper} confirm --state {state_path}'}


def confirm(state_path):
    state = json.loads(state_path.read_text())
    if state['status'] != 'PENDING' or time.time() >= state['expires_at_unix']:
        raise RuntimeError('Operation is not pending within its confirmation window')
    source = os.environ.get('SSH_CONNECTION', '').split()
    if not source or cidr(source[0] + '/32') != state['cidr']:
        raise RuntimeError('Confirmation requires SSH authenticated from the newly allowed IPv4')
    assert digest(CONFIG.read_text()) == state['config_after_sha256']
    assert digest(REGISTRY.read_text()) == state['registry_after_sha256']
    current = rules()
    assert any(r.get('comment') == state['comment'] and ssh_source(r) == state['cidr'] for r in current)
    assert [r for r in current if r.get('comment') != state['comment']] == state['original_rules'], 'Original runtime rules changed; do not confirm automatically'
    state['status'] = 'CONFIRMED'
    state['confirmed_at_unix'] = time.time()
    state['verified_ssh_source'] = source[0]
    save(state_path, state)
    run('systemctl', 'stop', state['unit'] + '.timer')
    return {'status': 'CONFIRMED', 'hostname': state['hostname'], 'cidr': state['cidr'],
            'verified_ssh_source': source[0], 'original_rule_handles_preserved': state['original_rule_handles']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['add', 'confirm', 'rollback', 'cidrs'])
    parser.add_argument('--cidr')
    parser.add_argument('--current')
    parser.add_argument('--state', type=Path)
    parser.add_argument('--rollback-seconds', type=int, default=600)
    args = parser.parse_args()
    if args.action == 'cidrs':
        no_pending_change()
        print('\n'.join(collect(CONFIG.read_text() if CONFIG.exists() else '', REGISTRY.read_text() if REGISTRY.exists() else '', args.current)))
    else:
        if os.geteuid() != 0:
            raise SystemExit('Root is required')
        with lock():
            if args.action == 'add':
                if not 60 <= args.rollback_seconds <= 900:
                    raise SystemExit('Rollback must remain enabled for 60–900 seconds')
                result = add(cidr(args.cidr), args.rollback_seconds)
            elif args.action == 'confirm':
                result = confirm(args.state)
            else:
                result = rollback(args.state)
            print(json.dumps(result, indent=2))
