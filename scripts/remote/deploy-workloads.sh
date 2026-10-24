#!/usr/bin/env bash
set -euo pipefail
server=${1:?server IPv4}
chart_version=${2:?monitoring chart version}
test -f /etc/verda-platform/managed
cd /opt/verda-platform
k() { k3s kubectl "$@"; }
k wait nodes --all --for=condition=Ready --timeout=300s
test "$(k get nodes --no-headers | wc -l)" -eq 2
for component in traefik metrics-server; do
  for attempt in $(seq 1 120); do
    if k -n kube-system get deployment/"$component" >/dev/null 2>&1; then break; fi
    sleep 5
  done
done
k -n kube-system rollout status deployment/traefik --timeout=300s
k -n kube-system rollout status deployment/metrics-server --timeout=300s
for ns in demo monitoring; do
  k create namespace "$ns" --dry-run=client -o yaml | k apply -f -
done
install -d -m 700 /etc/verda-platform/tls
umask 077
if ! openssl x509 -checkend 86400 -noout -in /etc/verda-platform/tls/demo.crt >/dev/null 2>&1; then
  openssl req -x509 -newkey ec -pkeyopt ec_paramgen_curve:P-256 -nodes -days 30 \
    -subj '/CN=Verda Assignment Demo/O=Assignment' \
    -addext "subjectAltName=IP:$server,IP:95.133.254.68" \
    -keyout /etc/verda-platform/tls/demo.key -out /etc/verda-platform/tls/demo.crt
fi
k -n demo create secret tls demo-tls --cert=/etc/verda-platform/tls/demo.crt \
  --key=/etc/verda-platform/tls/demo.key --dry-run=client -o yaml | k apply -f -
if ! k -n monitoring get secret grafana-admin >/dev/null 2>&1; then
  openssl rand -base64 24 | tr -d '\n' > /etc/verda-platform/grafana-password
  k -n monitoring create secret generic grafana-admin --from-literal=admin-user=admin \
    --from-file=admin-password=/etc/verda-platform/grafana-password
fi
k apply --server-side -f manifests/app.yaml
python3 - "$chart_version" <<'PY'
from pathlib import Path
import sys
assert f'  version: {sys.argv[1]}\n' in Path('manifests/monitoring.yaml').read_text(), 'Chart lock mismatch'
PY
k apply -f manifests/monitoring.yaml
k apply -f manifests/dashboard.yaml
k -n demo rollout status deployment/demo --timeout=300s
for attempt in $(seq 1 180); do
  if k -n monitoring get deployment/monitoring-grafana >/dev/null 2>&1 && \
     k -n monitoring get statefulset/prometheus-monitoring-prometheus >/dev/null 2>&1; then
    break
  fi
  if (( attempt % 12 == 0 )); then
    k -n kube-system get jobs -l helmcharts.helm.cattle.io/chart=monitoring
  fi
  sleep 5
done
k -n monitoring rollout status deployment/monitoring-grafana --timeout=600s
k -n monitoring rollout status statefulset/prometheus-monitoring-prometheus --timeout=600s
k -n monitoring rollout status deployment/monitoring-kube-state-metrics --timeout=300s
k -n monitoring rollout status daemonset/monitoring-prometheus-node-exporter --timeout=300s
k get pods -A -o wide
echo 'WORKLOADS_DEPLOYED'
