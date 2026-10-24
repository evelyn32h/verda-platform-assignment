# Validation record

Status: **PASS — all required items deployed and verified**.
Final verification: **2026-10-24 17:44:59 UTC** (19:44:59 Europe/Berlin),
refreshed after the health endpoint fix.

| Required item / check | Observed result |
|---|---|
| Two Verda VMs and SSH | PASS: expected hostnames; noninteractive authentication through owner-managed ssh-agent |
| Kubernetes | PASS: two Ready nodes, k3s v1.35.9+k3s1 |
| Ingress | PASS: Traefik / ServiceLB; server public IP in Ingress status |
| TLS approach | PASS: self-signed IP SAN certificate; HTTPS verified with certificate trust, without -k |
| Metrics server | PASS: metrics API Available; live kubectl top for both nodes and app Pods |
| External app | PASS: HTTP/HTTPS index and /healthz each return 200 with expected content |
| Health endpoint response type | PASS: HTTP and HTTPS return text/plain, exact body `ok\n`, and no attachment disposition |
| App manifests | PASS: two available replicas on distinct nodes, unprivileged containers |
| Monitoring | PASS: Prometheus/Grafana running, chart 90.1.2; Grafana reports 13.2.1 |
| Useful dashboard | PASS: six panels queried through Grafana's datasource proxy, all return data |
| Scrape targets | PASS: 15 healthy, zero down; node-exporter, CPU and memory series from both nodes |
| Monitoring storage | PASS: Grafana 2 GiB and Prometheus 10 GiB PVCs Bound |
| WireGuard / firewall | PASS: handshakes on both peers; k3s services active; firewall persistence enabled |
| Restricted ports | PASS: TCP 3000, 6443, 9090, 9100, 10250, 30677, 32191 unreachable on both VMs from the external client |
| Access / operations / summary | README.md, OPERATIONS.md, REPORT.md |

Sanitized machine-readable evidence: [required-checks.json](evidence/required-checks.json).
It includes actual query values, 18 external checks, certificate metadata, and
SHA-256 hashes for deployment sources and raw evidence files.

Full evidence remains local under `.local/evidence/20261024T174414Z/`, excluded
from Git. Other timestamped directories preserve preflight, deployment,
troubleshooting and earlier failed checks. No passwords, private keys,
kubeconfigs or join credentials appear in the committed evidence.

## Resolved findings

1. Owner loaded the protected SSH key locally; both VM authentications passed.
2. Added a wait for asynchronously created k3s component Deployments before rollout checks.
3. Added peer-only TCP 9100 for host-network node-exporter scraping. Both nodes
   are now collected; the port remains unreachable from the external client.
4. Allowed DHCPv4 replies for lease renewal. Firewall changes used a timed
   rollback and fresh SSH confirmation; the persistent firewall service is enabled.
5. Fixed `/healthz` serving `application/octet-stream` by adding an exact nginx
   location with `default_type text/plain`. Status 200, the original three-byte
   `ok\n` body, and readiness/liveness probe definitions are unchanged. Public
   HTTP and certificate-validated HTTPS both passed the new header/body assertions.
6. During that rollout, existing Pods influenced topology spread and the new
   replicas briefly landed on one node. Adding `matchLabelKeys: [pod-template-hash]`
   restored one replica per node and keeps the constraint scoped to each revision.
   Live metrics were rechecked after samples became available for the new Pods.

## Limits

The self-signed certificate expires **2026-11-23 15:22:06 UTC**. Browser trust is
not automatic. The control plane, public ServiceLB endpoint and monitoring disks
depend on the single server. HTTP remains enabled for this demonstration. Access
was tested from the operator's external client, not every Internet network.
Grafana authentication and panel data were verified via API; no screenshot is
claimed. No VM reboot or backup/restore drill was performed. A later read-only
storage inspection supports the [backup/recovery notes](BACKUP_RESTORE.md) bonus;
it does not change this runtime verification timestamp or constitute a restore
test. The later [basic RBAC verification](RBAC.md) separately records 92 passing
authorization checks and unchanged application/monitoring availability. Neither
follow-up changes the required-platform verification timestamp above. Alerting
and GitOps remain outside this hand-in.
