#!/usr/bin/env bash
set -euo pipefail
expected=${1:?expected hostname required}
test "$(hostname)" = "$expected"
test "$(id -u)" = 0
printf 'UTC: '; date -u +%FT%TZ
hostname
cat /etc/os-release
nproc
free -h
df -h /
ip -4 -brief address
ip -4 route
printf 'SSH source: %s\n' "${SSH_CONNECTION%% *}"
swapon --show
ss -lntup
systemctl is-active k3s k3s-agent || true
command -v nft >/dev/null && nft list tables || true
command -v ufw >/dev/null && ufw status || true
test -f /etc/verda-platform/managed && echo MANAGED_BY_THIS_PROJECT || true
