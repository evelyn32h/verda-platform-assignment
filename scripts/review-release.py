"""Local release-content/history scan. Reports locations and categories, never matched values."""
import argparse
import collections
import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    'private_key_block': re.compile(r'-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----'),
    'credential_bearing_kubeconfig': re.compile(r'(?m)^\s*(?:client-key-data|client-key)\s*:\s*\S+'),
    'jwt_credential': re.compile(r'\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}'),
    'aws_access_key_id': re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'),
    'github_credential': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b'),
    'k3s_join_credential': re.compile(r'\bK10[0-9a-fA-F]{64}::(?:server|agent):[^\s\x22\x27]+'),
    'prometheus_style_basic_auth_secret': re.compile(r'(?m)^\s*(?:admin-password|bearer_token|client-secret)\s*:\s*[A-Za-z0-9+/=_-]{16,}\s*$'),
    'embedded_url_password': re.compile(r'https?://[^\s/:@]+:[^\s/@]+@'),
    'literal_credential_assignment': re.compile(r'''(?i)(?<![\w-])["']?(?:api[_-]?key|password|passwd|token|client[_-]?secret|admin[_-]?password)["']?\s*[:=]\s*["']([^"'\s]{12,})["']'''),
}
SENSITIVE_KEYS = {'password', 'passwd', 'token', 'api_key', 'apikey', 'client_secret', 'secret_key', 'adminpassword', 'admin_password', 'client-key-data'}
FORBIDDEN_PATH = re.compile(r'(?i)(?:^|/)(?:\.local|\.cache|tmp|output|\.ssh|\.kube)/|(?:^|/)(?:\.env(?:\..*)?|id_rsa.*|id_ed25519.*|[^/]*\.kubeconfig|kubeconfig[^/]*|[^/]*\.(?:pem|key|p12|pfx|tar|tar\.gz|zip|log))$')


def git(*args, binary=False):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=not binary)


def scan(body, location):
    findings = []
    try:
        text = body.decode('utf-8-sig')
    except UnicodeDecodeError:
        return [], False
    for category, pattern in PATTERNS.items():
        for match in pattern.finditer(text):
            findings.append({'location': location, 'category': category, 'line': text.count('\n', 0, match.start()) + 1})
    try:
        obj = json.loads(text)
    except (ValueError, RecursionError):
        obj = None
    def inspect(value, path='$'):
        if isinstance(value, dict):
            if value.get('kind') == 'Secret' and any(value.get(k) for k in ('data', 'stringData')):
                findings.append({'location': location, 'category': 'populated_kubernetes_secret', 'field': path})
            for key, child in value.items():
                if key.lower() in SENSITIVE_KEYS and isinstance(child, str) and len(child) >= 12 and not child.startswith(('$', '/', '<', '{{')):
                    findings.append({'location': location, 'category': 'structured_credential_value', 'field': path + '.' + key})
                inspect(child, path + '.' + key)
        elif isinstance(value, list):
            for index, child in enumerate(value):
                inspect(child, f'{path}[{index}]')
    if obj is not None:
        inspect(obj)
    elif location.split(':')[-1].endswith(('.yaml', '.yml')) or re.search(r'(?m)^kind:\s*(?:Secret|Config)\s*$', text):
        import yaml
        try:
            for obj in yaml.safe_load_all(text):
                inspect(obj)
        except yaml.YAMLError:
            pass
    return findings, True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'.local/release-review.json')
    args = parser.parse_args()
    candidates = sorted(set(git('ls-files', '--cached', '--others', '--exclude-standard', '-z').split('\0')) - {''})
    history_map = {}
    for line in git('rev-list', '--objects', '--all', '--reflog').splitlines():
        parts = line.split(' ', 1)
        if len(parts) == 2 and parts[1]:
            history_map.setdefault(parts[0], parts[1])
    objects = [line.split()[0] for line in git('cat-file', '--batch-all-objects', '--batch-check=%(objectname) %(objecttype)').splitlines() if line.endswith(' blob')]
    payload = subprocess.check_output(['git', 'cat-file', '--batch'], cwd=ROOT, input=('\n'.join(objects)+'\n').encode())
    position = 0
    findings = []
    binary_blobs = 0
    candidate_hashes = {}
    binary_candidates = []
    for oid in objects:
        end = payload.index(b'\n', position)
        header = payload[position:end].split()
        size = int(header[2])
        body = payload[end+1:end+1+size]
        position = end+size+2
        path = history_map.get(oid, '<unreachable-or-index-blob>')
        found, is_text = scan(body, oid + ':' + path)
        findings.extend(found)
        binary_blobs += not is_text
        if path != '<unreachable-or-index-blob>' and FORBIDDEN_PATH.search(path) and not path.endswith(('.example', '.env.example')):
            findings.append({'location': oid + ':' + path, 'category': 'unexpected_sensitive_or_raw_history_path'})
    for path in candidates:
        file = ROOT/path
        if file.is_symlink():
            findings.append({'location': 'candidate:' + path, 'category': 'symlink_requires_manual_review'})
            continue
        if file.is_file():
            body = file.read_bytes()
            found, is_text = scan(body, 'candidate:' + path)
            findings.extend(found)
            if is_text and path != 'docs/evidence/release-review.json':
                candidate_hashes[path] = hashlib.sha256(body.decode('utf-8-sig').replace('\r\n', '\n').encode()).hexdigest()
            elif not is_text:
                binary_candidates.append(path)
        if FORBIDDEN_PATH.search(path) and not path.endswith(('.example', '.env.example')):
            findings.append({'location': 'candidate:' + path, 'category': 'unexpected_sensitive_or_raw_release_path'})
    history_paths = sorted(set(history_map.values()))
    result = {
        'status': 'PASS' if not findings else 'REVIEW_REQUIRED',
        'checked_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'history_tip_at_scan': git('rev-parse', 'HEAD').strip(),
        'commit_count_all_refs_and_reflogs': len(set(git('rev-list', '--all', '--reflog').splitlines())),
        'all_git_blob_objects_scanned_including_unreachable': len(objects),
        'binary_blobs_not_text_scanned': binary_blobs,
        'release_candidate_files_scanned': len(candidates),
        'history_paths_scanned': history_paths,
        'candidate_files': candidates,
        'candidate_text_sha256_normalized_lf': candidate_hashes,
        'binary_candidates_requiring_visual_review': binary_candidates,
        'report_self_excluded_from_candidate_hashes': True,
        'pattern_categories': list(PATTERNS), 'findings': findings,
        'git_author_contact_metadata_present': bool(git('log', '--all', '--format=%an <%ae>').strip()),
        'remote_configured': bool(git('remote').strip()),
        'limitations': ['Local pattern/structured-content review; not a proof against all credential formats.',
                        'Author names/emails and public VM addresses are metadata, not credential findings.',
                        'Re-run before publishing; .local raw evidence is excluded, not deleted.',
                        'Binary images, if present, need separate visual review; matched secret values are never printed.'],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(f"{result['status']}: {len(objects)} Git blobs; {len(candidates)} release files; {len(findings)} findings.")
    for finding in findings:
        print(json.dumps(finding))
    print('Report:', args.output)
    raise SystemExit(0 if not findings else 1)


if __name__ == '__main__':
    main()
