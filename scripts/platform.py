"""Operate only the two assignment VMs. Uses OpenSSH/ssh-agent, never opens SSH keys."""
import argparse
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import socket
import ssl
import subprocess
import sys
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "platform.json").read_text())
STAMP = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
EVIDENCE = ROOT / ".local" / "evidence" / STAMP


class Remote:
    def __init__(self, host, identity):
        self.host = host
        self.ssh = ["ssh.exe" if os.name == "nt" else "ssh", "-T",
                    "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
                    "-o", "ConnectTimeout=15", "-o", "ServerAliveInterval=15",
                    "-o", "ServerAliveCountMax=3", "-o", "IdentitiesOnly=yes",
                    "-i", str(identity), f"root@{host}"]

    def run(self, command, label, data=None, timeout=1200, sensitive=False):
        print(f"[{self.host}] {label}", flush=True)
        result = subprocess.run(self.ssh + [command], input=data,
                                capture_output=True, timeout=timeout)
        output = result.stdout.decode("utf-8", errors="replace")
        error = result.stderr.decode("utf-8", errors="replace")
        if not sensitive:
            EVIDENCE.mkdir(parents=True, exist_ok=True)
            (EVIDENCE / f"{self.host}-{label}.txt").write_text(
                f"UTC: {dt.datetime.now(dt.timezone.utc).isoformat()}\n"
                f"EXIT: {result.returncode}\n{output}{error}", encoding="utf-8")
            print((output + error)[-7000:], flush=True)
        if result.returncode:
            # Do not include secret-bearing stdout/stderr in exceptions.
            raise RuntimeError(f"{self.host}: {label} failed (exit {result.returncode})")
        return output

    def script(self, name, *args, timeout=1200):
        command = "bash /opt/verda-platform/scripts/remote/" + shlex.quote(name)
        command += " " + " ".join(shlex.quote(str(a)) for a in args)
        return self.run(command, Path(name).stem, timeout=timeout)

    def upload(self):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for relative in ("manifests", "scripts/remote", "platform.json"):
                archive.add(ROOT / relative, arcname=relative)
        payload = stream.getvalue()
        digest = hashlib.sha256(payload).hexdigest()
        self.run("install -d -m 700 /opt/verda-platform && "
                 "tar -xzf - -C /opt/verda-platform", "upload", data=payload)
        (EVIDENCE / f"{self.host}-upload.sha256").write_text(digest + "\n")
        self.run("for script in /opt/verda-platform/scripts/remote/*.sh; "
                 "do bash -n \"$script\" || exit; done; echo REMOTE_BASH_SYNTAX_OK",
                 "shell-syntax")


def preflight(remotes):
    failures = []
    for role, remote in remotes.items():
        expected = CONFIG[role + "_name"]
        script = (ROOT / "scripts/remote/preflight.sh").read_text()
        try:
            remote.run("bash -s -- " + shlex.quote(expected), "preflight",
                       data=script.encode(), timeout=90)
        except RuntimeError as error:
            failures.append(str(error))
    if failures:
        raise RuntimeError("; ".join(failures) + ". Check the SSH errors above: network/source-IP allowlist, host verification, or agent authentication; then retry.")


def prepare_nodes(remotes):
    for role, remote in remotes.items():
        remote.upload()
        peer = CONFIG["worker" if role == "server" else "server"]
        remote.script("prepare-node.sh", role, peer, CONFIG["server"], CONFIG["worker"])
        # A new authenticated connection is required before cancelling rollback.
        remote.run("test -f /etc/verda-platform/firewall.nft && "
                   "nft list table inet verda_platform >/dev/null && "
                   "systemctl enable --now verda-firewall.service && "
                   "systemctl stop verda-firewall-rollback.timer && echo FIREWALL_CONFIRMED",
                   "confirm-firewall")


def deploy(remotes):
    preflight(remotes)
    # Do not mutate either VM until both pass authentication and inventory checks.
    prepare_nodes(remotes)
    remotes["server"].script("install-server.sh", CONFIG["k3s_version"], CONFIG["server"])
    join_value = remotes["server"].run(
        "cat /var/lib/rancher/k3s/server/agent-token", "retrieve-join-credential", sensitive=True).strip()
    # The agent credential travels in SSH stdin, never arguments, logs, or local files.
    try:
        remotes["worker"].run(
            "umask 077; install -d -m 700 /etc/rancher/k3s; "
            "cat > /etc/rancher/k3s/agent-join", "transfer-join-credential",
            data=(join_value + "\n").encode(), sensitive=True)
    finally:
        join_value = None
    remotes["worker"].script("install-worker.sh", CONFIG["k3s_version"],
                              CONFIG["server"], CONFIG["worker"])
    remotes["server"].script("deploy-workloads.sh", CONFIG["server"],
                              CONFIG["monitoring_chart_version"])


def verify(remotes):
    remotes["server"].script("verify.sh", CONFIG["server"], timeout=900)
    for role, remote in remotes.items():
        remote.run("set -eu; nft list table inet verda_platform; "
                   "wg show flannel-wg latest-handshakes; "
                   "wg show flannel-wg latest-handshakes | awk '$2 > 0 {ok=1} END {exit !ok}'; "
                   "systemctl is-enabled verda-firewall; "
                   "systemctl is-active " + ("k3s" if role == "server" else "k3s-agent"),
                   "node-security")
    verify_external(remotes)


def verify_external(remotes):
    # This is the public certificate, not its private key or an SSH key.
    certificate = remotes["server"].run(
        "cat /etc/verda-platform/tls/demo.crt", "public-tls-certificate", sensitive=True)
    (EVIDENCE / "demo-public.crt").write_text(certificate, encoding="ascii")
    context = ssl.create_default_context(cadata=certificate)
    checks = []
    for scheme in ("http", "https"):
        for path in ("/", "/healthz"):
            url = f"{scheme}://{CONFIG['server']}{path}"
            with urllib.request.urlopen(url, timeout=20, context=context) as response:
                payload = response.read()
                body = payload.decode()
                content_ok = payload == b"ok\n" if path == "/healthz" else "The platform is running." in body
                assert response.status == 200 and content_ok, (url, body)
                if path == "/healthz":
                    assert response.headers.get_content_type() == "text/plain", dict(response.headers)
                    assert response.headers.get_content_disposition() != "attachment", dict(response.headers)
                checks.append({"check": url, "status": "PASS", "http_status": response.status,
                               "content_type": response.headers.get("Content-Type"),
                               "content_disposition": response.headers.get("Content-Disposition"),
                               **({"body": body} if path == "/healthz" else {})})
    service = json.loads(remotes["server"].run(
        "k3s kubectl -n kube-system get svc traefik -o json", "ingress-nodeports", sensitive=True))
    node_ports = [entry["nodePort"] for entry in service["spec"]["ports"] if entry.get("nodePort")]
    for host in (CONFIG["server"], CONFIG["worker"]):
        for port in (6443, 10250, 9100, 3000, 9090, *node_ports):
            try:
                connection = socket.create_connection((host, port), timeout=3)
            except OSError as error:
                checks.append({"host": host, "port": port, "externally_reachable": False,
                               "result": type(error).__name__})
            else:
                connection.close()
                checks.append({"host": host, "port": port, "externally_reachable": True})
    (EVIDENCE / "external-checks.json").write_text(json.dumps(checks, indent=2) + "\n")
    assert not any(c.get("externally_reachable") for c in checks), checks
    print("PUBLIC_HTTP_HTTPS_AND_PRIVATE_PORT_CHECKS_PASS", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["preflight", "deploy", "firewall", "app", "workloads", "verify", "upload"])
    parser.add_argument("--identity", type=Path,
                        default=Path.home() / ".ssh" / "verda_assignment")
    args = parser.parse_args()
    remotes = {role: Remote(CONFIG[role], args.identity) for role in ("server", "worker")}
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    record = {"started_at": STAMP, "action": args.action, "status": "RUNNING",
              "hosts": {role: CONFIG[role] for role in remotes}}
    try:
        if args.action == "preflight":
            preflight(remotes)
        elif args.action == "deploy":
            deploy(remotes)
            verify(remotes)
        elif args.action == "verify":
            verify(remotes)
        elif args.action == "app":
            remotes["server"].run(
                "set -eu; if test -f /etc/verda-platform/demo-gitops.json || "
                "k3s kubectl -n argocd get applications.argoproj.io demo -o name >/dev/null 2>&1; "
                "then echo 'Demo is managed by Argo CD; use gitops/demo/app.yaml and sync.' >&2; exit 1; fi",
                "check-demo-ownership")
            remotes["server"].upload()
            remotes["server"].run(
                "set -eu; . /opt/verda-platform/scripts/remote/demo-ownership.sh; require_legacy_demo_access; "
                "k3s kubectl apply --server-side -f /opt/verda-platform/manifests/app.yaml; "
                "k3s kubectl -n demo rollout status deployment/demo --timeout=300s",
                "deploy-app", timeout=360)
        elif args.action == "firewall":
            preflight(remotes)
            prepare_nodes(remotes)
        elif args.action == "workloads":
            for remote in remotes.values():
                remote.upload()
            remotes["server"].script("deploy-workloads.sh", CONFIG["server"],
                                      CONFIG["monitoring_chart_version"])
            verify(remotes)
        elif args.action == "upload":
            for remote in remotes.values():
                remote.upload()
        record["status"] = "PASS"
    except (RuntimeError, subprocess.TimeoutExpired, OSError, AssertionError, ValueError) as error:
        record["status"] = "FAIL"
        record["error"] = str(error)
        print(str(error), file=sys.stderr)
    finally:
        record["finished_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        (EVIDENCE / "run.json").write_text(json.dumps(record, indent=2) + "\n")
        print(f"Evidence: {EVIDENCE}", flush=True)
    return 0 if record["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
