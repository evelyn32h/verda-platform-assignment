# Delivery review — 25 October 2026

Submission target: Monday, **26 October 2026**. This review preserves existing
commits. The initial read-only review was followed by separately authorized
publication and Argo CD adoption. No VM rebuild, network change or email occurred.

## Today's verification boundary

* External HTTP and certificate-validated HTTPS both returned 200 for `/` and
  `/healthz`; content is correct and health remains `text/plain` with `ok\n`.
* Fresh SSH to both VMs passed from retained source `81.226.0.124` after the
  owner returned to the original Wi-Fi. The staged new-IP grant was cancelled:
  original input/persistent rules restored and both timers stopped. The new IP
  was never verified. See [closure](SSH_ACCESS.md).
* Today's [read-only health record](evidence/delivery-health.json) passes for two
  Ready nodes, 13 ready running Pods, two spread app replicas, metrics, two Bound
  monitoring PVCs, 15 healthy targets, Grafana health, six dashboard source queries
  and the healthy/Inactive production alert. Restricted external ports remain closed.
* With the later GitOps follow-up, all four bonuses are complete. The final review passed
  for 20 ready running Pods, including Argo CD; existing app/monitoring Pods stayed
  unchanged. See [GitOps health](evidence/gitops-health.json).
* All 15 checked application/platform objects' declared fields match via GET-only
  checks: [comparison](evidence/gitops-manifest-consistency.json). Seven app objects
  now use the independent GitOps source; the Namespace remains outside Argo.

For future rechecks, run `python scripts/review-health.py` from the repo root.
It reads nodes, workloads, metrics, PVCs, Grafana health, six dashboard source
queries, the existing rule, services/firewall and external access restrictions.
It does not apply manifests, restart Pods, inject alerts, export kubeconfigs or
read Secret values. It also does not claim a fresh authenticated Grafana browser
or dashboard-panel API test.

## PDF requirements and evidence

The supplied one-page PDF was re-read and visually checked; its local SHA-256 is
`f9552a4fa4a56414b39582d74dfbeac2313e57c31d6d76ccb64c822c64c9e244`.
The original stays ignored; the table paraphrases its requirements.

| Requirement | Completion and qualification | Evidence |
|---|---|---|
| Verda CPU VMs with public IPs | Two existing Ubuntu VMs, inventoried 24 October. Provisioning is external to the repo; no VM IaC/audit trail is claimed. | [Inventory/full checks](evidence/required-checks.json); cloud-console screenshot recommended |
| Working Kubernetes | Two Ready k3s nodes reconfirmed today through restored SSH. | [Validation](VALIDATION.md), [server bootstrap](../scripts/remote/install-server.sh) |
| Ingress controller | Traefik/ServiceLB implemented; external app still works today. | [App YAML](../gitops/demo/app.yaml), [public checks](evidence/delivery-health.json) |
| cert-manager or TLS explanation | Explanation option complete: self-signed IP SAN certificate, verified HTTPS, expires 23 November. cert-manager is not claimed installed. | [TLS approach](../README.md#tls-approach), [certificate evidence](evidence/required-checks.json) |
| Metrics server | Implemented; metrics API and live node metrics reconfirmed today; Pod metrics recorded 24 October. | [Full checks](evidence/required-checks.json) |
| External sample app and manifests/chart | Implemented: two available replicas across nodes reconfirmed today; external index and health pass. | [App manifest](../gitops/demo/app.yaml), [today's record](evidence/delivery-health.json) |
| Monitoring and useful dashboard | Prometheus/Grafana with six panels; authenticated panel queries and owner UI confirmation recorded. Today reconfirmed 15 healthy targets and all six source queries. | [Monitoring](../manifests/monitoring.yaml), [dashboard](../manifests/dashboard.yaml), [data evidence](evidence/required-checks.json) |
| Access/operations instructions or screenshots | Instructions exist. Public app accessible; private management/tunnel access requires an authorized identity and source IP; owner SSH works. Screenshots are an alternative, not an extra mandatory feature. | [README](../README.md#access), [operations](OPERATIONS.md) |
| Git repo with scripts/manifests/docs | Published Public repo; original history retained, remote commit/file blobs verified. | [Repository](https://github.com/evelyn32h/verda-platform-assignment), [release review](evidence/release-review.json) |
| Short report: build, architecture, debugging, security/ops, improvements | Complete, with dated validation and untested limits. | [Report](REPORT.md), [architecture](../README.md#architecture-and-network) |
| Bonus: backup/restore notes | Complete as notes; no backup or restore drill claimed. | `25ff2f0`; [runbook](BACKUP_RESTORE.md), [inventory](evidence/backup-inventory.json) |
| Bonus: basic RBAC | Complete: 92 allow/deny checks; no long-lived token. | `211ce86`; [YAML](../manifests/rbac.yaml), [evidence](evidence/rbac-checks.json) |
| Bonus: simple alerts | Complete: production rule and synthetic Pending/Firing/recovery/cleanup. No external notifications. | `776c4a8`; [rule](../manifests/alerts.yaml), [evidence](evidence/alert-checks.json) |
| Bonus: Argo CD and GitOps app deployment | Complete: pinned v3.5.6; seven app objects Synced/Healthy; Git change 9998ec8 manually synced and verified in both Pods/public responses. | [Runbook](GITOPS.md), [evidence](evidence/gitops-checks.json) |

## Owner actions before submission

1. **Use the published Public repository URL for submission:**
   https://github.com/evelyn32h/verda-platform-assignment. Verify the final
   submitted commit after adding any optional material; no repository login is
   needed to read the code. The original history is preserved.
2. **Choose how to demonstrate private Grafana/Argo/management access.**
   `localhost:3000` is a tunnel URL, not a public reviewer endpoint. The current
   instructions assume an authorized owner key and source IP. The reader
   ServiceAccount policy does not issue a reviewer login. Argo is also tunnel-only;
   its HTML/version were checked, but authenticated UI login is still an owner action.
   Do not share the owner private key, root kubeconfig or Grafana admin password in the repo. Screenshots
   or an owner-led demonstration can supply evidence without sharing them.

Recommended images if providing screenshots rather than relying on instructions:

| Image | What to capture | What to hide |
|---|---|---|
| Verda console | Both VM names/status, public IPs, CPU/RAM and useful region/IDs | Billing/credits, account email and all credentials |
| Grafana | Six panels, recent time range, visible values and dashboard title | Session credentials, password prompts, unrelated personal/account data |
| Argo CD (optional) | demo Application, Synced/Healthy, repository path and revision | Admin password, initial-secret output, session credentials |
| Public app/health (optional) | Browser address, app and plain-text health display | Avoid confusing the assignment PDF rendering with an app screenshot |
| Nodes/Prometheus rule (optional) | Two Ready nodes and the healthy production rule | Use existing lifecycle evidence; do not create another outage/test |

No PNG/JPEG screenshot is tracked. The sole local PNG at this review is an
ignored assignment PDF rendering. No fabricated images or missing-image links
were added. Screenshots are recommended supplementary material, not a newly
invented mandatory requirement.

## Publication content and history

[release-review.json](evidence/release-review.json) records scans of all Git blob
objects, including unreachable/index objects, and release candidates. It checks
private keys, credential-bearing kubeconfigs, token formats, literal/structured
credentials, populated Secret objects, and unexpected raw/credential paths.
No credential match or raw-evidence history path was found in the reviewed
snapshot; Git object integrity also passed. Matched values are never printed.
Earlier evidence hashes identify the source used for each dated test; they are
not rewritten to match later documentation/tool fixes. The release review hashes
current text candidates with LF normalization and excludes its own report from
that map to avoid a self-reference.

This is a local pattern/content review, not proof against all unknown credential
formats. Current Git blobs are text; future screenshots require visual review.
Public VM IPs, Kubernetes IDs, standard paths and author metadata are distinct
from credentials. `docs/evidence/` contains curated JSON; `.local/`, `tmp/`, keys,
archives and the PDF remain ignored. Stage explicitly and deliver a Git
clone/archive, not a zip of the workspace including ignored files. No history
was rewritten; only normal authorized pushes were performed. Re-run `python scripts/review-release.py`
after adding materials and immediately before publication.

[Link results](evidence/link-review.json) record reachable public references.
The private localhost Grafana URL was not retested without its SSH tunnel.

## Final GitOps scope

The separately authorized Argo CD/GitOps work is complete. All required features
and four PDF bonuses have evidence; backup/restore remains notes-only. Automatic
sync/prune and external notifications are disabled. Keep the stable platform;
no further features are needed for the Monday submission. UI screenshots/login
and the final submission message remain owner actions, not unattended publishing
or credential-sharing tasks.
