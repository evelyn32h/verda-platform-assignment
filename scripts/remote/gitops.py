"""Install pinned Argo CD and manually adopt/sync only the existing demo app."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time

ROOT=Path('/opt/verda-platform')
STATE=Path('/etc/verda-platform')
LOCK=json.loads((ROOT/'gitops/argocd/version-lock.json').read_text())

def now(): return datetime.datetime.now(datetime.timezone.utc).isoformat()
def run(*args, timeout=120):
    result=subprocess.run(list(args),capture_output=True,text=True,timeout=timeout)
    if result.returncode:
        raise RuntimeError('Command failed: '+' '.join(args[:5])+'\n'+result.stderr[-4000:])
    return result.stdout
def k(*args,timeout=120): return run('k3s','kubectl','--request-timeout=90s',*args,timeout=timeout)
def get(kind,name=None,namespace=None):
    args=['get',kind]+([name] if name else [])+(['-n',namespace] if namespace else [])+['-o','json']
    return json.loads(k(*args))
def save(path,value):
    path.write_text(json.dumps(value,indent=2)+'\n'); path.chmod(0o600)
def pod_snapshot():
    pods=json.loads(k('get','pods','-A','-o','json'))['items']
    return {p['metadata']['namespace']+'/'+p['metadata']['name']:{
        'uid':p['metadata']['uid'],'restarts':sum(c['restartCount'] for c in p['status'].get('containerStatuses',[]))}
        for p in pods if p['metadata']['namespace'] in ('demo','monitoring') and p['status']['phase']=='Running'}
def baseline():
    return {'captured_at':now(),'pods':pod_snapshot(),
            'demo_namespace_uid':get('namespace','demo')['metadata']['uid']}
def preserved():
    before=json.loads((STATE/'gitops-baseline.json').read_text())
    assert before['pods']==pod_snapshot(),'Existing app/monitoring Pod identities or restarts changed'
    assert before['demo_namespace_uid']==get('namespace','demo')['metadata']['uid']
    return {'app_and_monitoring_pod_uids_and_restarts_unchanged':True,'demo_namespace_uid_unchanged':True}

def install():
    assert Path('/etc/verda-platform/managed').exists()
    assert hashlib.sha256((ROOT/'.local/argocd-install.yaml').read_bytes()).hexdigest()==LOCK['install_sha256']
    marker=STATE/'argocd-install.json'
    exists=k('get','namespace','argocd','--ignore-not-found','-o','name').strip()
    if exists:
        assert marker.exists(),'Existing unmanaged Argo namespace; refuse to overwrite'
        assert json.loads(marker.read_text())['version']==LOCK['version']
    else:
        assert not k('get','crd','applications.argoproj.io','--ignore-not-found','-o','name').strip(),'Existing Argo CRDs; inspect first'
        save(STATE/'gitops-baseline.json',baseline())
        save(marker,{'version':LOCK['version'],'status':'INSTALLING','started_at':now(),'install_sha256':LOCK['install_sha256']})
        k('create','namespace','argocd')
        k('apply','--server-side','--force-conflicts','-n','argocd','-f',str(ROOT/'.local/argocd-install.yaml'),timeout=240)
        # Bound only the newly created Argo workloads; existing workloads are untouched.
        k('set','resources','deployments','--all','-n','argocd','--requests=cpu=50m,memory=64Mi','--limits=cpu=1,memory=512Mi')
        k('set','resources','statefulset/argocd-application-controller','-n','argocd','--requests=cpu=100m,memory=256Mi','--limits=cpu=1,memory=1Gi')
    for kind in ('deployments','statefulsets'):
        for item in get(kind,namespace='argocd')['items']:
            k('rollout','status',kind+'/'+item['metadata']['name'],'-n','argocd','--timeout=600s',timeout=660)
    services=get('services',namespace='argocd')['items']
    assert services and all(s['spec']['type']=='ClusterIP' for s in services)
    assert not get('ingresses',namespace='argocd')['items']
    k('apply','-f',str(ROOT/'gitops/argocd/project.yaml'))
    for name in ('demo-ownership.sh','deploy-workloads.sh'):
        run('bash','-n',str(ROOT/'scripts/remote'/name))
    save(marker,{'version':LOCK['version'],'status':'READY','completed_at':now(),'install_sha256':LOCK['install_sha256']})
    return {'status':'PASS','action':'install','version':LOCK['version'],'install_sha256':LOCK['install_sha256'],
            'services':[{'name':s['metadata']['name'],'type':s['spec']['type']} for s in services],
            'public_ingress_created':False,'legacy_guard_scripts_synchronized':True,**preserved()}

def adopt():
    assert json.loads((STATE/'argocd-install.json').read_text())['status']=='READY'
    assert get('deployment','demo','demo')['status']['availableReplicas']==2
    assert k('get','namespace','demo','-o','name').strip()
    # Guard legacy entry points before creating the Application or requesting sync.
    save(STATE/'demo-gitops.json',{'application':'argocd/demo','repository':LOCK['repository'],
         'path':LOCK['application_path'],'adopted_at':now(),'namespace_and_secrets_managed':False})
    k('apply','-f',str(ROOT/'gitops/argocd/application.yaml'))
    app=get('application','demo','argocd')
    assert not app['spec']['syncPolicy'].get('automated')
    assert not app['metadata'].get('finalizers')
    return {'status':'PASS','action':'adopt','sync_requested':False,'automatic_prune':False,**preserved()}

def verify(revision=None):
    app=get('application','demo','argocd')
    assert app['spec']['project']=='demo-only'
    assert app['spec']['source']['repoURL']==LOCK['repository']
    assert app['spec']['source']['path']==LOCK['application_path']
    assert app['spec']['destination']['namespace']=='demo'
    assert not app['spec']['syncPolicy'].get('automated')
    assert {'Prune=false','Delete=false'}<=set(app['spec']['syncPolicy']['syncOptions'])
    assert not app['metadata'].get('finalizers')
    status=app['status']; operation=status.get('operationState',{})
    assert status['sync']['status']=='Synced' and status['health']['status']=='Healthy'
    assert operation.get('phase')=='Succeeded' and operation['operation']['sync'].get('prune') is False
    if revision: assert status['sync']['revision']==revision
    resources=status['resources']
    assert len(resources)==7
    assert all(r.get('namespace')=='demo' and r['kind'] not in ('Secret','Namespace','Role','RoleBinding') for r in resources)
    assert get('deployment','demo','demo')['status']['availableReplicas']==2
    return {'status':'PASS','action':'verify','version':LOCK['version'],'application':'argocd/demo',
        'sync':status['sync']['status'],'health':status['health']['status'],'revision':status['sync']['revision'],
        'operation_phase':operation['phase'],'operation_started_at':operation.get('startedAt'),
        'operation_finished_at':operation.get('finishedAt'),'prune':False,'automatic_sync':False,
        'resources':[{'group':r.get('group',''),'kind':r['kind'],'namespace':r['namespace'],'name':r['name'],'sync':r.get('status')} for r in resources],
        'conditions':status.get('conditions',[]),**preserved()}

def sync(revision):
    assert revision and re.fullmatch('[0-9a-f]{40}',revision),'Require a pushed full commit SHA'
    app=get('application','demo','argocd')
    assert not app.get('operation'),'An operation is already queued'
    options=app['spec']['syncPolicy']['syncOptions']
    patch={'operation':{'initiatedBy':{'username':'assignment-operator'},
        'sync':{'revision':revision,'prune':False,'syncOptions':options}}}
    k('patch','application','demo','-n','argocd','--type=merge','-p',json.dumps(patch))
    deadline=time.monotonic()+600
    while time.monotonic()<deadline:
        current=get('application','demo','argocd')
        status=current.get('status',{}); op=status.get('operationState',{})
        if op.get('phase') in ('Failed','Error') and not current.get('operation'):
            raise RuntimeError('Argo sync failed: '+json.dumps({'message':op.get('message'),'conditions':status.get('conditions')}))
        if (not current.get('operation') and op.get('phase')=='Succeeded'
                and status.get('sync',{}).get('revision')==revision
                and status.get('sync',{}).get('status')=='Synced'
                and status.get('health',{}).get('status')=='Healthy'):
            result=verify(revision); result['action']='manual-sync'; return result
        time.sleep(5)
    raise TimeoutError('Argo sync did not reach Synced/Healthy within ten minutes')

if __name__=='__main__':
    assert os.geteuid()==0
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['install','adopt','sync','verify'])
    parser.add_argument('--revision')
    args=parser.parse_args()
    result=install() if args.action=='install' else adopt() if args.action=='adopt' else sync(args.revision) if args.action=='sync' else verify(args.revision)
    result['checked_at']=now()
    print(json.dumps(result,indent=2))
