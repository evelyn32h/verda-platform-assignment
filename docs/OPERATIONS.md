# Operations and rollback

All commands below run on the server as root unless noted. Local operations use
`python scripts/platform.py verify` and save their evidence locally. No rollback
or uninstall runs automatically except the temporary firewall failsafe.

For routine delivery review, prefer `python scripts/review-health.py`: it performs
GET-only checks without reading Secret values or creating port-forward processes.
The older full verifier also reads the Grafana credential to test authenticated
panel queries and creates temporary loopback port-forwards. Neither verifier
redeploys, but the new review intentionally has a narrower inspection scope.
Authorization/source-IP access is required; see [delivery status](HANDOFF.md).

## Routine checks

```sh
k3s kubectl get nodes -o wide
k3s kubectl get pods -A -o wide
k3s kubectl top nodes
k3s kubectl -n demo describe deployment demo
k3s kubectl -n monitoring get pvc
systemctl status k3s
journalctl -u k3s --since '15 minutes ago' --no-pager
wg show flannel-wg
nft list table inet verda_platform
```

On the worker use `systemctl status k3s-agent` and `journalctl -u k3s-agent`.
Do not paste kubeconfigs, join credentials, generated passwords, or TLS private
keys into tickets or Git. Keep SSH host key verification enabled.

## Application rollback

```sh
k3s kubectl -n demo rollout history deployment/demo
k3s kubectl -n demo rollout undo deployment/demo
k3s kubectl -n demo rollout status deployment/demo
```

`rollout undo` requires a previous Deployment revision. On the first deployment
there is no previous version to restore. Versioned manifests are the source for
ConfigMap and Ingress changes: revert those files and reapply them. Application
content is mounted from a ConfigMap; content updates may take time to propagate.
An intentionally destructive application removal is `kubectl delete -f
/opt/verda-platform/manifests/app.yaml`; deleting its Namespace also deletes the
TLS Secret and other resources in that namespace.

The exact `/healthz` nginx location serves the original static file with
`Content-Type: text/plain`; both readiness and liveness probes still use that
path. The `demo-nginx` ConfigMap mounts `default.conf` using `subPath`. After
editing that ConfigMap, run `k3s kubectl -n demo rollout restart deployment/demo`
and wait for rollout to load it. Topology spread uses `pod-template-hash` so
each new Deployment revision remains spread across the two nodes during updates.

## Firewall rollback

Before applying rules, `prepare-node.sh` stores the old host ruleset as evidence
and separately saves the prior project-owned table under
`/root/verda-platform-backups/<UTC>/`. A transient systemd timer runs that
snapshot's `rollback-firewall.sh` after five minutes unless a **new** SSH session
confirms access. The script restores only the project table and its prior config,
or removes the initial project table. It does not restore the entire host
ruleset over Kubernetes' live rules.

```sh
systemctl list-timers verda-firewall-rollback.timer
# Inspect/select the actual timestamp, then run if rollback is intended:
bash /root/verda-platform-backups/<UTC>/rollback-firewall.sh
```

If SSH access is lost, wait for the failsafe and use the Verda console if needed.
Do not cancel the timer until a fresh SSH connection has passed. Before changing
the management source IP, update the allowlist while retaining an existing SSH
session and the provider console. Persist with `verda-firewall.service`; use the
same timer/confirmation workflow when changing rules.

The additive access helper also supports a narrower per-rule timed rollback
without reloading the firewall. Its staged 25 October grant was cancelled and
fully withdrawn; only the original management source remains allowed. Related
scripts were retained but do not grant the cancelled address automatically.
See [access closure and evidence](SSH_ACCESS.md). Future node preparation merges
approved policy/registry sources rather than discarding previous allowed sources.

## Monitoring changes

The k3s Helm controller owns the monitoring Helm release. Edit
`manifests/monitoring.yaml`, upload, and reapply the HelmChart. The chart version
must match `platform.json`. For rollback, restore the previous HelmChart manifest
from Git and reapply. Avoid an unmanaged `helm rollback` that the controller may
later reconcile away. PersistentVolumes are node-local; a chart rollback is not
a data restore. Do not delete monitoring PVCs during routine upgrades.

## Full teardown (destructive; only when intended)

First export needed app/monitoring data and save the cluster backup securely.
Then remove the worker node from the server, uninstall the worker, and finally
uninstall the server:

```sh
# Server, while the API is still running:
k3s kubectl delete node verda-k3s-worker
# Worker:
/usr/local/bin/k3s-agent-uninstall.sh
# Server:
/usr/local/bin/k3s-uninstall.sh
```

k3s uninstall deletes the local datastore and local-path data. After Kubernetes
has been removed, on each VM disable `verda-firewall.service` and restore the
pre-project firewall snapshot or intentionally remove `inet verda_platform`.
Restore original sysctl/configuration from the saved backup where appropriate.
This does not remove the VMs, revoke SSH keys, or reverse provider billing.

## Backup and availability tradeoffs

The single server uses SQLite, so the control plane is **not highly available**.
The complete [backup and recovery runbook](BACKUP_RESTORE.md) records the observed
SQLite files, matching credentials/encryption material, both local-path PVs,
their Delete policy, and the Prometheus data subdirectory. It distinguishes
control-plane recovery from monitoring data recovery and describes a future
coordinated maintenance backup, restoration, verification and failure limits.
Only read-only inventory and documentation were completed; no service was
stopped and no data backup or recovery drill was performed.

The two app replicas are spread across nodes. This protects a Pod failure but
does not make the single ingress/control-plane or node-local monitoring storage
highly available. More time would add a third server and suitable datastore,
off-host storage/backups, controlled DNS with ACME, narrower workload network
policies, least-privilege operator access, and immutable scanned image digests.

References: [uninstall](https://docs.k3s.io/installation/uninstall),
[SQLite backup](https://docs.k3s.io/datastore/backup-restore).
