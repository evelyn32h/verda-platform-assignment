#!/usr/bin/env bash
set -euo pipefail
server=${1:?server IPv4}
k() { k3s kubectl "$@"; }
printf 'VERIFICATION UTC: '; date -u +%FT%TZ
k get --raw=/readyz
k wait nodes --all --for=condition=Ready --timeout=120s
k get nodes -o wide
k get pods -A -o wide
k get svc,ingress -A
k -n demo get deployment demo -o json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert d["status"].get("availableReplicas")==2; print("APP_REPLICAS=2")'
k -n demo get pods -l app=demo -o json | python3 -c 'import json,sys; d=json.load(sys.stdin); nodes={p["spec"]["nodeName"] for p in d["items"] if p["status"]["phase"]=="Running"}; assert len(nodes)==2,nodes; print("APP_SPREAD_ACROSS_TWO_NODES=PASS")'
k get apiservice v1beta1.metrics.k8s.io -o json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert any(c["type"]=="Available" and c["status"]=="True" for c in d["status"]["conditions"]); print("METRICS_API=AVAILABLE")'
k top nodes
k top pods -n demo
curl --fail --silent --show-error --max-time 20 "http://$server/healthz"
curl --fail --silent --show-error --max-time 20 --cacert /etc/verda-platform/tls/demo.crt "https://$server/healthz"
openssl x509 -in /etc/verda-platform/tls/demo.crt -noout -dates -fingerprint -sha256 -ext subjectAltName
k -n monitoring get pvc
k -n monitoring get svc -o json | python3 -c 'import json,sys; d=json.load(sys.stdin); assert all(s["spec"]["type"]=="ClusterIP" for s in d["items"]); print("MONITORING_SERVICES_PRIVATE=PASS")'
k3s kubectl -n monitoring port-forward --address=127.0.0.1 svc/monitoring-prometheus 19090:9090 >/tmp/verda-prometheus-forward.log 2>&1 &
prom_pid=$!
k3s kubectl -n monitoring port-forward --address=127.0.0.1 svc/monitoring-grafana 13000:80 >/tmp/verda-grafana-forward.log 2>&1 &
grafana_pid=$!
trap 'kill "$prom_pid" "$grafana_pid" 2>/dev/null || true; wait "$prom_pid" "$grafana_pid" 2>/dev/null || true' EXIT
for attempt in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:19090/-/ready >/dev/null 2>&1 && curl -fsS http://127.0.0.1:13000/api/health >/dev/null 2>&1; then break; fi
  sleep 2
done
kill -0 "$prom_pid" "$grafana_pid"
python3 <<'PY'
import base64,json,subprocess,time,urllib.parse,urllib.request
def get(url,headers=None):
    with urllib.request.urlopen(urllib.request.Request(url,headers=headers or {}), timeout=20) as r:
        return json.load(r)
queries={
    'ready_nodes':'sum(kube_node_status_condition{condition="Ready",status="true"})',
    'app_replicas':'kube_deployment_status_replicas_available{namespace="demo",deployment="demo"}',
    'node_exporters':'count(up{job="node-exporter"} == 1)',
    'node_memory_series':'count(node_memory_MemTotal_bytes)',
    'node_cpu_series':'count(count by(instance) (node_cpu_seconds_total))',
}
for attempt in range(30):
    results={}
    for key,query in queries.items():
        data=get('http://127.0.0.1:19090/api/v1/query?'+urllib.parse.urlencode({'query':query}))
        assert data['status']=='success',data
        rows=data['data']['result']
        results[key]=float(rows[0]['value'][1]) if rows else None
    if all(value==2 for value in results.values()): break
    time.sleep(5)
assert all(value==2 for value in results.values()),results
print('PROMETHEUS_QUERIES='+json.dumps(results))
targets=get('http://127.0.0.1:19090/api/v1/targets')['data']['activeTargets']
down=[{'job':t['labels'].get('job'),'endpoint':t['scrapeUrl'],'error':t['lastError']} for t in targets if t['health']!='up']
print('PROMETHEUS_TARGETS='+json.dumps({'total':len(targets),'down':down}))
assert not down,down
raw=subprocess.check_output(['k3s','kubectl','-n','monitoring','get','secret','grafana-admin','-o','json'])
secret=json.loads(raw)['data']
username=base64.b64decode(secret['admin-user']).decode().strip()
password=base64.b64decode(secret['admin-password']).decode().strip()
headers={'Authorization':'Basic '+base64.b64encode((username+':'+password).encode()).decode()}
health=get('http://127.0.0.1:13000/api/health')
assert health['database']=='ok',health
dashboard=get('http://127.0.0.1:13000/api/dashboards/uid/verda-platform',headers)['dashboard']
assert len(dashboard['panels'])==6
print('GRAFANA='+json.dumps({'health':health,'dashboard':dashboard['title'],'uid':dashboard['uid'],'panels':len(dashboard['panels'])}))
panel_results={}
for panel in dashboard['panels']:
    assert panel['datasource']['uid']=='prometheus'
    query=panel['targets'][0]['expr']
    data=get('http://127.0.0.1:13000/api/datasources/proxy/uid/prometheus/api/v1/query?'+urllib.parse.urlencode({'query':query}),headers)
    assert data['status']=='success' and data['data']['result'], panel['title']
    panel_results[panel['title']]=[row['value'][1] for row in data['data']['result']]
print('GRAFANA_PANEL_RESULTS='+json.dumps(panel_results))
PY
k -n demo get pods -o jsonpath='{range .items[*]}{.metadata.name}{" "}{.spec.nodeName}{" "}{.status.containerStatuses[0].imageID}{"\n"}{end}'
k -n kube-system get helmchart monitoring -o jsonpath='{.spec.version}{"\n"}'
wg show flannel-wg latest-handshakes
echo 'ALL_REQUIRED_REMOTE_CHECKS_PASS'
