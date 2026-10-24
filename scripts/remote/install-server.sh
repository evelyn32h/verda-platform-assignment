#!/usr/bin/env bash
set -euo pipefail
version=${1:?k3s version}
server=${2:?server IPv4}
test -f /etc/verda-platform/managed
test "$(hostname)" = verda-k3s-server
umask 077
install -d -m 700 /etc/rancher/k3s
cat > /etc/rancher/k3s/config.yaml <<EOF
node-name: verda-k3s-server
node-ip: $server
advertise-address: $server
tls-san:
  - $server
  - 127.0.0.1
flannel-backend: wireguard-native
flannel-iface: eth0
cluster-cidr: 10.42.0.0/16
service-cidr: 10.43.0.0/16
write-kubeconfig-mode: "0600"
secrets-encryption: true
kube-apiserver-arg:
  - anonymous-auth=false
EOF
curl --fail --silent --show-error --location --retry 3 https://get.k3s.io -o /etc/verda-platform/install-k3s.sh
sha256sum /etc/verda-platform/install-k3s.sh
INSTALL_K3S_VERSION="$version" INSTALL_K3S_EXEC=server sh /etc/verda-platform/install-k3s.sh
for attempt in $(seq 1 90); do
  if k3s kubectl get --raw=/readyz >/dev/null 2>&1; then break; fi
  sleep 2
done
k3s kubectl get --raw=/readyz
k3s kubectl label node verda-k3s-server svccontroller.k3s.cattle.io/enablelb=true --overwrite
k3s --version
