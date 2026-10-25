"""Operate pinned Argo CD on the existing server; no VM/network changes."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import platform as project
import shlex
import tarfile
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
LOCK=json.loads((ROOT/'gitops/argocd/version-lock.json').read_text())
def upload(remote):
    cache=ROOT/'.local/argocd-v3.5.6-install.yaml'
    if not cache.exists():
        with urllib.request.urlopen(LOCK['install_url'],timeout=45) as response: data=response.read()
        assert hashlib.sha256(data).hexdigest()==LOCK['install_sha256']
        cache.parent.mkdir(exist_ok=True); cache.write_bytes(data)
    assert hashlib.sha256(cache.read_bytes()).hexdigest()==LOCK['install_sha256']
    files=['scripts/remote/gitops.py','scripts/remote/demo-ownership.sh','scripts/remote/deploy-workloads.sh',
           'gitops/argocd/version-lock.json','gitops/argocd/project.yaml','gitops/argocd/application.yaml']
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w:gz') as archive:
        for file in files: archive.add(ROOT/file,arcname=file)
        archive.add(cache,arcname='.local/argocd-install.yaml')
    # Save previous scripts; do not run the legacy deploy script.
    backup='/root/verda-platform-backups/gitops-scripts-'+project.STAMP
    command='set -eu; install -d -m 700 '+backup+'; '
    for file in files[:3]:
        command+='if test -f /opt/verda-platform/'+file+'; then cp -p /opt/verda-platform/'+file+' '+backup+'/'+Path(file).name+'; fi; '
    command+='tar --no-same-owner -xzf - -C /opt/verda-platform; python3 -m py_compile /opt/verda-platform/scripts/remote/gitops.py; '
    command+='bash -n /opt/verda-platform/scripts/remote/demo-ownership.sh; bash -n /opt/verda-platform/scripts/remote/deploy-workloads.sh'
    remote.run(command,'upload-gitops-only',data=stream.getvalue())

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['install','adopt','sync','verify'])
    parser.add_argument('--revision')
    parser.add_argument('--identity',type=Path,default=Path.home()/'.ssh/verda_assignment')
    args=parser.parse_args()
    remote=project.Remote(project.CONFIG['server'],args.identity)
    if args.action=='install': upload(remote)
    command='python3 /opt/verda-platform/scripts/remote/gitops.py '+args.action
    if args.revision: command+=' --revision '+shlex.quote(args.revision)
    project.EVIDENCE.mkdir(parents=True,exist_ok=True)
    try:
        result=json.loads(remote.run(command,'gitops-'+args.action,timeout=1800))
        result['operator_source_sha256']={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ('scripts/gitops.py','scripts/remote/gitops.py')}
        (project.EVIDENCE/('gitops-'+args.action+'.json')).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print('Evidence:',project.EVIDENCE)
    except Exception as error:
        (project.EVIDENCE/('gitops-'+args.action+'-failed.json')).write_text(json.dumps({'status':'FAIL','action':args.action,'error':str(error)},indent=2)+'\n',encoding='utf-8')
        raise
