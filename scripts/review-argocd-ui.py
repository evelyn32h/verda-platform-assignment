"""Verify the Argo UI over a temporary SSH tunnel; no login or Secret read."""
import datetime
import json
from pathlib import Path
import platform as project
import shlex
import ssl
import subprocess
import time
import urllib.error
import urllib.request

if __name__=='__main__':
    remote=project.Remote(project.CONFIG['server'],Path.home()/'.ssh/verda_assignment')
    code='''import subprocess,sys
p=subprocess.Popen(['k3s','kubectl','-n','argocd','port-forward','--address=127.0.0.1','svc/argocd-server','18443:443'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try: sys.stdin.buffer.read()
finally:
    p.terminate()
    try: p.wait(timeout=10)
    except subprocess.TimeoutExpired: p.kill(); p.wait()
print('FORWARD_CLEANED')
'''
    command=remote.ssh[:-1]+['-o','ExitOnForwardFailure=yes','-L','127.0.0.1:18443:127.0.0.1:18443',remote.ssh[-1],'python3 -c '+shlex.quote(code)]
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    # Argo's default self-signed UI certificate is accepted only over this loopback SSH tunnel.
    context=ssl._create_unverified_context()
    result=None
    try:
        deadline=time.monotonic()+40
        while time.monotonic()<deadline:
            try:
                with urllib.request.urlopen('https://127.0.0.1:18443/api/version',context=context,timeout=3) as response:
                    version=json.load(response)
                break
            except (OSError,urllib.error.URLError):
                if process.poll() is not None: raise RuntimeError('SSH tunnel exited before becoming ready')
                time.sleep(1)
        else: raise TimeoutError('SSH UI tunnel did not become ready')
        assert version['Version'].startswith('v3.5.6')
        with urllib.request.urlopen('https://127.0.0.1:18443/',context=context,timeout=10) as response:
            body=response.read(); assert response.status==200 and b'<html' in body.lower()
        result={'status':'PASS','checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'access':'SSH tunnel -> server loopback-only kubectl port-forward -> ClusterIP service',
            'ui_http_status':200,'reported_version':version['Version'],'login_performed':False,'secret_read':False,
            'self_signed_ui_cert_accepted_only_on_loopback_tunnel':True}
    finally:
        process.stdin.close(); process.stdin=None
        try: output,error=process.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            process.terminate(); output,error=process.communicate(timeout=10)
        if result:
            assert process.returncode==0 and b'FORWARD_CLEANED' in output,'Temporary tunnel cleanup failed'
            result['temporary_forward_cleaned']=True
    project.EVIDENCE.mkdir(parents=True,exist_ok=True)
    (project.EVIDENCE/'argocd-ui.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(result,indent=2)); print('Evidence:',project.EVIDENCE)
