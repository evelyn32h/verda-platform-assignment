#!/usr/bin/env bash
set -euo pipefail
role=${1:?role}
peer=${2:?peer IPv4}
server=${3:?server IPv4}
worker=${4:?worker IPv4}
test "$(id -u)" = 0
case "$role:$(hostname)" in
  server:verda-k3s-server|worker:verda-k3s-worker) ;;
  *) echo 'Unexpected host; no changes made'; exit 1 ;;
esac
admin=${SSH_CONNECTION%% *}
[[ "$admin" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Expected IPv4 SSH source'; exit 1; }
if { command -v k3s >/dev/null || test -e /etc/rancher/k3s/config.yaml; } && ! test -f /etc/verda-platform/managed; then
  echo 'Unmanaged Kubernetes installation found; refusing to overwrite'; exit 1
fi
if command -v ufw >/dev/null && ufw status | grep -q '^Status: active'; then
  echo 'Existing active UFW policy found; inspect before changing'; exit 1
fi
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq curl ca-certificates nftables wireguard-tools openssl
modprobe wireguard
install -d -m 700 /etc/verda-platform
snapshot="/root/verda-platform-backups/$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 700 "$snapshot"
nft list ruleset > "$snapshot/nft-before.txt"
if nft list table inet verda_platform > "$snapshot/previous-table.nft" 2>/dev/null; then
  echo 'Existing project firewall saved'
else
  : > "$snapshot/previous-table.nft"
fi
if test -f /etc/verda-platform/firewall.nft; then
  cp -a /etc/verda-platform/firewall.nft "$snapshot/previous-config.nft"
fi
for path in /etc/rancher/k3s/config.yaml /etc/sysctl.d/90-verda-platform.conf; do
  if test -f "$path"; then cp -a --parents "$path" "$snapshot/"; fi
done
cat > "$snapshot/rollback-firewall.sh" <<EOF
#!/usr/bin/env bash
set -eu
nft delete table inet verda_platform 2>/dev/null || true
if test -s '$snapshot/previous-table.nft'; then
  nft -f '$snapshot/previous-table.nft'
fi
if test -f '$snapshot/previous-config.nft'; then
  cp '$snapshot/previous-config.nft' /etc/verda-platform/firewall.nft
else
  systemctl disable verda-firewall.service || true
fi
EOF
chmod 700 "$snapshot/rollback-firewall.sh"
cat > /etc/verda-platform/firewall.nft <<EOF
table inet verda_platform {
  chain input {
    type filter hook input priority -10; policy drop;
    ct state invalid drop
    ct state established,related accept
    iifname "lo" accept
    iifname "eth0" udp sport 67 udp dport 68 accept
    meta l4proto { icmp, ipv6-icmp } accept
    ip saddr $admin tcp dport 22 accept
    ip saddr $peer tcp dport { 6443, 10250, 9100 } accept
    ip saddr $peer udp dport 51820 accept
    iifname "eth0" ip saddr 10.42.0.0/16 drop
    ip saddr 10.42.0.0/16 accept
    ip saddr 10.43.0.0/16 accept
    tcp dport { 80, 443 } accept
  }
  chain forward {
    type filter hook forward priority -10; policy accept;
    ct state invalid drop
    ct state established,related accept
    iifname "eth0" ip saddr $peer accept
    iifname "eth0" meta l4proto tcp ct original proto-dst { 80, 443 } accept
    iifname "eth0" ct state new drop
  }
}
EOF
cat > /usr/local/sbin/verda-firewall <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
rules=$(mktemp)
trap 'rm -f "$rules"' EXIT
if nft list table inet verda_platform >/dev/null 2>&1; then
  echo 'delete table inet verda_platform' >> "$rules"
fi
cat /etc/verda-platform/firewall.nft >> "$rules"
nft -c -f "$rules"
nft -f "$rules"
EOF
chmod 700 /usr/local/sbin/verda-firewall
cat > /etc/systemd/system/verda-firewall.service <<'EOF'
[Unit]
Description=Verda assignment host firewall (isolated nftables table)
After=network-pre.target
Before=k3s.service k3s-agent.service
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/verda-firewall
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
if systemctl is-active --quiet verda-firewall-rollback.timer; then
  echo 'A previous firewall rollback is pending; inspect it before retrying'; exit 1
fi
systemd-run --unit=verda-firewall-rollback --on-active=5m /bin/bash "$snapshot/rollback-firewall.sh"
/usr/local/sbin/verda-firewall
touch /etc/verda-platform/managed
printf 'net.ipv4.ip_forward = 1\n' > /etc/sysctl.d/90-verda-platform.conf
sysctl -p /etc/sysctl.d/90-verda-platform.conf
printf 'Firewall applied; rollback armed for five minutes. Backup: %s\n' "$snapshot"
