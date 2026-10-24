#!/usr/bin/env bash
set -euo pipefail
version=${1:?k3s version}
server=${2:?server IPv4}
worker=${3:?worker IPv4}
test -f /etc/verda-platform/managed
test "$(hostname)" = verda-k3s-worker
test -s /etc/rancher/k3s/agent-join
umask 077
cat > /etc/rancher/k3s/config.yaml <<EOF
server: https://$server:6443
token-file: /etc/rancher/k3s/agent-join
node-name: verda-k3s-worker
node-ip: $worker
flannel-iface: eth0
EOF
curl --fail --silent --show-error --location --retry 3 https://get.k3s.io -o /etc/verda-platform/install-k3s.sh
sha256sum /etc/verda-platform/install-k3s.sh
INSTALL_K3S_VERSION="$version" INSTALL_K3S_EXEC=agent sh /etc/verda-platform/install-k3s.sh
systemctl is-active k3s-agent
k3s --version
