# Assignment summary

## Result

All required items are deployed on the two existing Verda Ubuntu VMs and passed
live verification on 24 October 2026. The sample app is available at
**http://95.133.252.141/** and **https://95.133.252.141/**. HTTPS uses an explicitly
documented self-signed IP certificate. [Validation](VALIDATION.md) contains the
results and sanitized evidence; the README contains access instructions.

The **25 October delivery review** passed fresh SSH checks on both VMs from
the retained original Wi-Fi and GET-only cluster/monitoring checks: two Ready
nodes, two spread app replicas, 15 healthy targets, Grafana health and six
dashboard source queries. Public HTTP/HTTPS index and health also passed.
All 15 declared manifest objects match the live configuration (the API represents
the Helm timeout `900s` as the equivalent `15m0s`). Today's check did not repeat
authenticated Grafana browser/panel-API validation or the synthetic alert test.

An earlier network switch caused SSH timeouts. The owner returned to the original
Wi-Fi, then cancelled a staged new-IP access grant. That grant was withdrawn on
both hosts, original runtime/persistent policy restored, and its two timers stopped.
The original source `81.226.0.124/32` remains allowed. Access-management scripts
that preserve approved sources were retained; node preparation was not executed.
No workload redeployment, VM restart or application/monitoring change occurred.
[Access closure](SSH_ACCESS.md) and [today's health evidence](evidence/delivery-health.json)
record the outcome. [HANDOFF.md](HANDOFF.md) maps the PDF requirements and lists
repository-link and optional screenshot actions before Monday, 26 October.
The local repository has not been published.

Deployment scripts, workload manifests, monitoring configuration, a custom
dashboard and operator documentation are included in this Git repository.
The basic namespace RBAC and simple application alert bonuses are deployed and
verified. External notification delivery is not configured. GitOps/Argo CD remains
deferred.
The backup/recovery **notes** bonus is now complete; its procedures have not been
executed or validated through a restore drill.

## Architecture

verda-k3s-server (95.133.252.141) and verda-k3s-worker (95.133.254.68) run
k3s v1.35.9+k3s1. Both have 4 vCPUs and approximately 16 GiB of RAM. The server
hosts SQLite and the ServiceLB public entry point. Traefik terminates ingress
and routes to an application ClusterIP with one unprivileged nginx replica per
node. The README includes the architecture diagram.

Flannel WireGuard encrypts cross-node Pod traffic over the public VM addresses.
The firewall limits SSH to the operator's observed IPv4 and cluster/API, kubelet
and node-exporter ports to the peer VM. Public app ports are 80/443. Forwarded
traffic is filtered too; generated NodePorts were tested unreachable externally.

Prometheus/Grafana use kube-prometheus-stack 90.1.2. Fifteen scrape targets were
healthy at both the 24 October checks and today's read-only review. The six-panel
Verda Platform Overview dashboard shows ready nodes, app replicas, running Pods,
CPU, memory and root filesystem use. Each panel was
queried through Grafana and returned data. Monitoring uses ClusterIP services
and SSH tunnels. Grafana's 2 GiB and Prometheus's 10 GiB local-path PVCs are bound
on the server.

## What worked and what needed debugging

- Both VMs authenticated noninteractively after the owner loaded the protected
  SSH key into Windows ssh-agent. No passphrase was sent through chat.
- Two Ready nodes, ingress, metrics API, both app replicas, external HTTP/HTTPS,
  persistent monitoring and dashboard data all passed live checks.
- Initial rollout checking ran before k3s's asynchronous Traefik Deployment
  existed. The script now waits for component creation before rollout checks.
- Initial metrics checks found only one node-exporter. Traffic to the worker's
  host-network endpoint was source-masqueraded and blocked by the firewall.
  Peer-only TCP 9100 fixed collection while external access remained blocked.
- A follow-up fixed the health endpoint MIME type from application/octet-stream
  to text/plain with an exact nginx location. HTTP/HTTPS still return status 200
  and the original three-byte body; probe definitions are unchanged. Revision-aware
  topology spread preserves one app replica per node through the rolling update.

Raw troubleshooting and final evidence are saved locally. The sanitized record
includes timestamps, query values, certificate metadata, external connection
results and hashes of deployment sources and raw logs.

## Security, operations and rollback

The app runs without root, privilege escalation, Linux capabilities, a writable
root filesystem or an API credential. It has resource requests/limits and health
probes. Kubernetes Secrets are encrypted at rest. The join credential travels
through SSH stdin and stays out of local files, logs and command arguments.
Credentials and raw output are excluded from Git; host keys are strictly checked.
Root SSH is retained for this assignment.

Firewall changes own one nftables table, preserve other rules and arm a
five-minute rollback until a new SSH session passes. DHCPv4 replies are allowed
for lease renewal. Application revisions and versioned HelmChart manifests
support rollback. Teardown and backup requirements are in
[OPERATIONS.md](OPERATIONS.md). No destructive rollback, reboot or restore drill
was performed.

The 30-day self-signed certificate expires on **23 November 2026** and requires
explicit client trust. HTTP remains enabled for the demo. Pod traffic is
encrypted; node-exporter uses HTTP restricted to the peer host. Single-server
control plane, public entry point and node-local monitoring storage limit
availability. Upstream image versions and observed digests are recorded; no
vulnerability scan or immutable digest deployment is claimed.

## Backup/recovery notes bonus

[BACKUP_RESTORE.md](BACKUP_RESTORE.md) replaces the earlier brief backup paragraph
with coverage of the SQLite datastore, matching server token, Secrets encryption
material, host configuration and the two server-local monitoring PVs. Read-only
inspection confirmed a Grafana SQLite file, Delete reclaim policies, server node
affinity, and the Prometheus `prometheus-db` mount subdirectory. The current
Prometheus admin snapshot API is disabled.

The runbook describes a future coordinated backup window, full-identity SQLite
recovery with original PV/PVC bindings, and post-restore data checks. It explicitly
distinguishes metadata from volume contents and Git dashboards from UI/database
state. It records the risk of deleting local-path claims, ownership requirements,
fresh-cluster rebinding limits, unmeasured RPO/RTO and absent off-host automation.
Only metadata/file existence was inspected; services were not stopped, and no
backup, snapshot, integrity check or recovery was executed. The sanitized
[inventory](evidence/backup-inventory.json) supports the observed layout. The
owner also independently confirmed the public app, health endpoint and six panels.

## Basic RBAC bonus

[manifests/rbac.yaml](../manifests/rbac.yaml) creates `demo-reader` as a
ServiceAccount, Role and RoleBinding only in `demo`. The Role allows
`get/list/watch` on Pods, Services and Deployments, and `get` on Pod logs.
It has no write, Secret, cross-namespace or cluster-resource grants. No
ClusterRole/ClusterRoleBinding, token credential or API exposure was added.

All **92 authorization checks passed** (10 allow, 82 deny), using impersonation
with the ServiceAccount's normal groups. Real application resource/log reads
succeeded; monitoring Pod and cluster Node requests returned Forbidden.
Mutation/Secret denial was tested with `kubectl auth can-i`, without executing
mutations or reading Secrets. [Evidence](evidence/rbac-checks.json) records all
decisions, actual reads and before/after service health. The application and
monitoring retained the same Pod UIDs/restart counts, HTTP/HTTPS stayed healthy,
Grafana health was ok and all 15 Prometheus targets remained up. That RBAC change
did not include alerting; the separately requested alert follow-up is recorded
below. [RBAC usage notes](RBAC.md) explain reproduction and scope.

## Simple alert bonus

[manifests/alerts.yaml](../manifests/alerts.yaml) adds one PrometheusRule,
`monitoring/demo-availability`, selected by the existing Operator through
`release: monitoring`. `DemoAvailableReplicasLow` fires when the app's available
replica metric stays below the intended floor of two for two minutes, with
15-second evaluations and warning severity. Its annotations describe readiness,
log/event and capacity checks plus rollback of a faulty release. Missing metric
data is a known limitation of this single rule, not treated as zero.

Read-only inspection confirmed that Alertmanager was disabled/not deployed and
Prometheus had no notification targets. Those settings and the monitoring chart
were not changed. The loaded production rule was healthy and Inactive with two
available replicas. An independent synthetic rule with a 30-second hold was
observed **Pending → Firing → Inactive** without scaling or disrupting the app.
The firing instance was confirmed in the alerts API; recovery required a fresh
evaluation of a false condition and no active test alert. The test CR was then
deleted, its loaded rule removed, and the permanent rule retained. This is an
accelerated engine test, not an actual app outage or a notification delivery test.

[Evidence](evidence/alert-checks.json) records configuration discovery, timestamps,
rule details, test inputs, cleanup and service health. All app/monitoring Pod
identities and restart counts stayed unchanged; external HTTP/HTTPS, Grafana and
all 15 scrape targets were healthy. **No external channel is configured, no
notification was sent, and notification delivery is untested.** See
[ALERTS.md](ALERTS.md) for the response procedure and reproducible test. Argo CD
was not started.

## With more time

Controlled DNS with cert-manager/ACME, immutable scanned images, three
control-plane nodes, off-host storage with a restore drill, least-privilege
administration and workload network policies would be the next improvements.
