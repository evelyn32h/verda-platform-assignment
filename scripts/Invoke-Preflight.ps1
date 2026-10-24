[CmdletBinding()]
param([string]$IdentityFile = 'C:\Users\hyj\.ssh\verda_assignment')
$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $repo '.local\evidence'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssZ')
$remote = @'
set -eu
printf 'UTC: '; date -u +%FT%TZ
hostname
cat /etc/os-release
printf '\nCPU / RAM / DISK\n'
nproc
free -h
df -h /
printf '\nNETWORK\n'
ip -4 -brief address
ip -4 route
printf '\nSSH source (used for firewall allowlist)\n'
printf '%s\n' "$SSH_CONNECTION"
printf '\nKERNEL / SWAP / FIREWALL\n'
uname -r
swapon --show
command -v ufw >/dev/null && ufw status || true
command -v nft >/dev/null && nft list tables || true
printf '\nLISTENERS\n'
ss -lntup
printf '\nEXISTING KUBERNETES\n'
command -v k3s || true
systemctl is-active k3s k3s-agent || true
printf '\nPEER CONNECTIVITY\n'
case "$(hostname)" in
verda-k3s-server) ping -c 2 -W 3 95.133.254.68 ;;
verda-k3s-worker) ping -c 2 -W 3 95.133.252.141 ;;
*) echo 'Unexpected hostname'; exit 1 ;;
esac
'@
foreach ($hostIp in @('95.133.252.141','95.133.254.68')) {
    $log = Join-Path $logDir "$stamp-preflight-$hostIp.txt"
    Write-Host "Read-only preflight: $hostIp (requires the key already loaded in your local ssh-agent)"
    $remote | & ssh.exe -T -o BatchMode=yes -o StrictHostKeyChecking=yes -o ConnectTimeout=15 -o IdentitiesOnly=yes -i $IdentityFile "root@$hostIp" 'tr -d ''\r'' | bash -s' 2>&1 | Tee-Object -FilePath $log
    if ($LASTEXITCODE -ne 0) { throw "SSH preflight failed for $hostIp. No deployment performed. See $log" }
}
Write-Host "Preflight complete. Evidence: $logDir"
