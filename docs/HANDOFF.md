# Delivery review — 25 October 2026

Submission target: Monday, **26 October 2026**. This review preserves existing
commits. It does not redeploy, rebuild VMs, install Argo CD, publish or email.

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
* All 15 manifest objects' declared fields match live objects via GET-only checks:
  [comparison](evidence/manifest-consistency.json). No cluster drift was repaired.

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
| Ingress controller | Traefik/ServiceLB implemented; external app still works today. | [App YAML](../manifests/app.yaml), [public checks](evidence/delivery-health.json) |
| cert-manager or TLS explanation | Explanation option complete: self-signed IP SAN certificate, verified HTTPS, expires 23 November. cert-manager is not claimed installed. | [TLS approach](../README.md#tls-approach), [certificate evidence](evidence/required-checks.json) |
| Metrics server | Implemented; metrics API and live node metrics reconfirmed today; Pod metrics recorded 24 October. | [Full checks](evidence/required-checks.json) |
| External sample app and manifests/chart | Implemented: two available replicas across nodes reconfirmed today; external index and health pass. | [App manifest](../manifests/app.yaml), [today's record](evidence/delivery-health.json) |
| Monitoring and useful dashboard | Prometheus/Grafana with six panels; authenticated panel queries and owner UI confirmation recorded. Today reconfirmed 15 healthy targets and all six source queries. | [Monitoring](../manifests/monitoring.yaml), [dashboard](../manifests/dashboard.yaml), [data evidence](evidence/required-checks.json) |
| Access/operations instructions or screenshots | Instructions exist. Public app accessible; private management/tunnel access requires an authorized identity and source IP; owner SSH works. Screenshots are an alternative, not an extra mandatory feature. | [README](../README.md#access), [operations](OPERATIONS.md) |
| Git repo with scripts/manifests/docs | Local repo content complete; no remote configured or published. Reviewer-accessible link remains an owner action. | [Release review](evidence/release-review.json), repository files |
| Short report: build, architecture, debugging, security/ops, improvements | Complete, with dated validation and untested limits. | [Report](REPORT.md), [architecture](../README.md#architecture-and-network) |
| Bonus: backup/restore notes | Complete as notes; no backup or restore drill claimed. | `25ff2f0`; [runbook](BACKUP_RESTORE.md), [inventory](evidence/backup-inventory.json) |
| Bonus: basic RBAC | Complete: 92 allow/deny checks; no long-lived token. | `211ce86`; [YAML](../manifests/rbac.yaml), [evidence](evidence/rbac-checks.json) |
| Bonus: simple alerts | Complete: production rule and synthetic Pending/Firing/recovery/cleanup. No external notifications. | `776c4a8`; [rule](../manifests/alerts.yaml), [evidence](evidence/alert-checks.json) |
| Bonus: Argo CD and GitOps app deployment | Not implemented/claimed. Installing Argo CD alone would not satisfy the GitOps deployment part. | No Argo CD work performed |

## Owner actions before submission

1. **Select the repository destination, visibility and reviewer access**, then
   provide the final Monday link. Publishing is not done in this review. Git
   author name/email will accompany history; confirm the intended attribution
   before making it public. Attribution metadata is separate from credentials.
2. **Choose how to demonstrate private Grafana/management access.**
   `localhost:3000` is a tunnel URL, not a public reviewer endpoint. The current
   instructions assume an authorized owner key and source IP. The reader
   ServiceAccount policy does not issue a reviewer login. Do not share the owner
   private key, root kubeconfig or Grafana admin password in the repo. Screenshots
   or an owner-led demonstration can supply evidence without sharing them.

Recommended images if providing screenshots rather than relying on instructions:

| Image | What to capture | What to hide |
|---|---|---|
| Verda console | Both VM names/status, public IPs, CPU/RAM and useful region/IDs | Billing/credits, account email and all credentials |
| Grafana | Six panels, recent time range, visible values and dashboard title | Session credentials, password prompts, unrelated personal/account data |
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
was rewritten or remote push performed. Re-run `python scripts/review-release.py`
after adding materials and immediately before publication.

[Link results](evidence/link-review.json) record reachable public references.
The private localhost Grafana URL was not retested without its SSH tunnel.

## Argo CD decision

Mandatory features and three bonus items have evidence; management access and
today's health are now verified. A configured repository source the cluster can
fetch is still missing. **Do not start Argo CD in this delivery review.** A
separately authorized GitOps follow-up is technically feasible after selecting
the Git source and its access method, but the Monday submission already has a
stable required scope. Argo CD must also manage the sample app through GitOps to
satisfy the PDF bonus; installation alone is insufficient.
