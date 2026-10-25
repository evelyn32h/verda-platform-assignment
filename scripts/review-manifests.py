"""Compare declared manifest fields to GET-only live resources; never fetch Secrets."""
import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
spec = importlib.util.spec_from_file_location('project', ROOT/'scripts/platform.py')
project = importlib.util.module_from_spec(spec)
spec.loader.exec_module(project)
files = sorted((ROOT/'manifests').glob('*.yaml'))
gitops_app=ROOT/'gitops/demo/app.yaml'
if gitops_app.exists(): files.append(gitops_app)
expected = []
for file in files:
    for obj in yaml.safe_load_all(file.read_text(encoding='utf-8')):
        if obj:
            if gitops_app.exists() and file.name=='app.yaml' and file.parent.name=='manifests' and obj['kind']!='Namespace':
                continue  # Legacy app copy is a recovery reference after adoption.
            assert obj['kind'] in ('Namespace','ConfigMap','Deployment','Service','Ingress','TLSStore','HelmChart','ServiceAccount','Role','RoleBinding','PrometheusRule')
            expected.append({'file': file.relative_to(ROOT).as_posix(), 'object': obj})
code = 'expected=json.loads(' + repr(json.dumps(expected)) + ')\n'
code = 'import datetime,json,re,subprocess\n' + code + '''
normalizations=[]
def duration(value):
    parts=re.findall(r'([0-9]+)(h|m|s)',value)
    assert ''.join(n+u for n,u in parts)==value
    return sum(int(n)*{'h':3600,'m':60,'s':1}[u] for n,u in parts)
def compare(want,live,path='$'):
    if isinstance(want,dict):
        assert isinstance(live,dict),path
        for k,v in want.items():
            assert k in live,path+'.'+k
            compare(v,live[k],path+'.'+k)
    elif isinstance(want,list):
        assert isinstance(live,list) and len(want)==len(live),path
        for i,(a,b) in enumerate(zip(want,live)): compare(a,b,path+'['+str(i)+']')
    elif path=='$.spec.timeout' and want!=live:
        assert duration(want)==duration(live),path
        normalizations.append({'field':path,'declared':want,'live':live,'equivalent_seconds':duration(live)})
    else: assert want==live,path
results=[]
for item in expected:
    obj=item['object']; meta=obj['metadata']
    args=['k3s','kubectl','--request-timeout=20s','get',obj['kind'],meta['name'],'-o','json']
    if meta.get('namespace'): args+=['-n',meta['namespace']]
    live=json.loads(subprocess.check_output(args,text=True,timeout=30))
    compare(obj,live)
    results.append({'source':item['file'],'kind':obj['kind'],'namespace':meta.get('namespace'),
        'name':meta['name'],'declared_fields_match':True})
print(json.dumps({'status':'PASS','checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'method':'kubectl GET only; recursive declared-field subset comparison; no Secret fetch',
    'objects':results,'api_normalizations':normalizations},indent=2))
'''
remote = project.Remote(project.CONFIG['server'],Path.home()/'.ssh/verda_assignment')
record = json.loads(remote.run('python3 -', 'manifest-consistency',data=code.encode()))
record['source_sha256'] = {p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
project.EVIDENCE.mkdir(parents=True,exist_ok=True)
(project.EVIDENCE/'manifest-consistency.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
print('Evidence:',project.EVIDENCE)
