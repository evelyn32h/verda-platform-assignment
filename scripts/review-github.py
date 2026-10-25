"""Verify the public GitHub branch and every file blob against the local Git commit."""
import datetime
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
REPO='evelyn32h/verda-platform-assignment'
def get(path):
    req=urllib.request.Request('https://api.github.com/repos/'+REPO+path,headers={'User-Agent':'verda-publication-review','Accept':'application/vnd.github+json'})
    with urllib.request.urlopen(req,timeout=30) as response: return json.load(response)

if __name__=='__main__':
    head=subprocess.check_output(['git','rev-parse','HEAD'],text=True,cwd=ROOT).strip()
    commit=get('/commits/main')
    assert commit['sha']==head,'Remote main does not match local HEAD'
    tree=get('/git/trees/'+commit['commit']['tree']['sha']+'?recursive=1')
    assert not tree['truncated']
    remote={item['path']:item['sha'] for item in tree['tree'] if item['type']=='blob'}
    local={}
    for line in subprocess.check_output(['git','ls-tree','-r','HEAD'],text=True,cwd=ROOT).splitlines():
        meta,path=line.split('\t',1); mode,kind,oid=meta.split()
        assert kind=='blob' and mode in ('100644','100755'),'Unexpected publication entry'
        local[path]=oid
    assert remote==local,'Remote paths/blob IDs differ'
    record={'status':'PASS','checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'repository':'https://github.com/'+REPO,'branch':'main','commit':head,'file_count':len(local),
        'all_remote_file_blobs_match_local':True,'history_rewritten':False}
    output=ROOT/'.local/evidence'/datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output.mkdir(parents=True,exist_ok=True)
    (output/'github-source.json').write_text(json.dumps(record,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(record,indent=2)); print('Evidence:',output)
