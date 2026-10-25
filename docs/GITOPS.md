# Argo CD and application GitOps

Status: **deployed and verified on 25 October 2026**. Stable pre-Argo baseline
`b3f028c` remains an ancestor of the published history. Repository:
https://github.com/evelyn32h/verda-platform-assignment, branch `main`.

## Scope and source

The Application `argocd/demo` reads only `gitops/demo/app.yaml`. It manages seven
existing objects in `demo`: two ConfigMaps, one Deployment, one Service, two
Ingresses and one TLSStore. Namespace, Secrets, monitoring and RBAC are excluded.
Ingress/TLSStore reference the existing `demo-tls`; TLS material stays under the
original platform workflow. No repository credential is needed for this Public
Git source. The supplied assignment PDF, recruitment mail/coupon material,
credentials and raw private logs were not in reachable history before publication.
Normal pushes preserve the original commits; no history rewrite or force push occurred.

The `demo-only` AppProject restricts the repository, destination namespace and
five resource kinds; cluster resources and Secrets/RBAC are excluded. The standard
non-HA Argo installation itself has cluster-level controller RBAC. This is a
documented demo tradeoff, not namespace-only controller authorization.

Argo CD is fixed at **v3.5.6**, including the observed controller/server image tag.
The official manifest SHA-256 is locked in
[version-lock.json](../gitops/argocd/version-lock.json). All eight Argo Services
are ClusterIP. There is no Argo Ingress, host-network Pod or host port. Both VMs'
original SSH input rules and persistent policy were verified identical after
installation; public TCP 8080/8443/18443 probes were unreachable on both hosts.

## Access through SSH

Run locally and leave the tunnel open:

```powershell
ssh -i "$env:USERPROFILE\.ssh\verda_assignment" -o ExitOnForwardFailure=yes -L 127.0.0.1:8080:127.0.0.1:18443 root@95.133.252.141 "k3s kubectl -n argocd port-forward --address=127.0.0.1 svc/argocd-server 18443:443"
```

Open **https://localhost:8080**. Argo's default self-signed UI certificate causes
a browser warning. SSH host-key verification remains enabled; the public app's
separate certificate is still validated normally by the health checks. End the
tunnel with Ctrl+C when finished. `localhost` is not a reviewer-accessible public URL.

Initial user: `admin`. Retrieve the bootstrap password **only in the owner's
terminal**, without recording/publishing it:

```powershell
ssh -i "$env:USERPROFILE\.ssh\verda_assignment" root@95.133.252.141 "k3s kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d"
```

If the initial password was subsequently changed, use the current credential.
Automated validation fetched UI HTML and version through a temporary SSH tunnel,
accepted the self-signed certificate only on that loopback connection, and cleaned
both forwards. It did not read this Secret or test authenticated UI login.

## Normal updates and validation

The first adoption is **manual**. Automatic sync, self-heal and prune are disabled.
Every app object also carries `Prune=false,Delete=false`; the Application has no
cascading deletion finalizer. Namespace creation is not part of the Application.
Legacy `platform.py app` refuses an adopted app; `deploy-workloads.sh` skips its
old app manifest. Both check the Application and a root-only ownership marker at
`/etc/verda-platform/demo-gitops.json`. Do not bypass these guards for an update.

1. Edit `gitops/demo/app.yaml`; review the diff and run local policy tests.
2. Commit and normally push `main`, then sync that full commit explicitly.
3. Verify revision, health, public content and unchanged monitoring.

From the repository root (owner SSH/agent access required):

```powershell
python -m unittest discover -s tests -p test_gitops_policy.py -v
git diff --check
# Commit and push the intended change first.
python scripts/review-github.py
python scripts/gitops.py sync --revision (git rev-parse HEAD)
python scripts/gitops.py verify
python scripts/review-health.py
python scripts/review-manifests.py
```

The sync operator submits an Argo Application operation with `prune:false`; it
does not apply app manifests directly. It checks Synced/Healthy, the actual Git
revision, and a canonical hash of live ConfigMap data against that Git commit.
The old app YAML is a recovery reference; edit the GitOps source for operation.
The live manifest reviewer compares that source plus the separately managed
Namespace/platform objects. These local reviewers additionally use PyYAML.

The HTML ConfigMap mounts as a directory, so updates propagate through kubelet's
normal refresh without restarting Pods. The nginx configuration uses `subPath`:
a future nginx-config change needs a Pod-template revision annotation changed in
the same Git commit to trigger a controlled rolling update. That change was not
part of this demonstration.

## Actual verification

* First manual sync of `4dda8de56108be08236288269789b4eae8b3f3a7` reached
  Succeeded/Synced/Healthy at 16:29:24 UTC. No application spec/content change or
  Pod restart was needed for metadata/field ownership adoption.
* The first validator incorrectly required an explicit `prune:false` field. Argo
  omits that default boolean. Reading the actual operation confirmed success and
  `Prune=false`; the corrected read-only verifier passed. The original failed
  validator evidence remains local, and this issue is recorded in the report.
* Commit `9998ec851101d8308f32fd120ed95109ed23ef6d` changed only the HTML ConfigMap
  to add “Managed with Argo CD from Git.” Before sync at 16:35:13 UTC, Argo was
  OutOfSync/Healthy and the live ConfigMap still had old content. Manual sync at
  16:35:18 UTC returned Synced/Healthy with the new revision and matching data hash.
* Both app Pods and public HTTP/HTTPS served the marker. `/healthz` remained
  200/text/plain with exact `ok\n`. Original app/monitoring Pod UIDs and restart
  counts plus the demo Namespace UID were unchanged. Legacy apply was refused.
* Final health passed for two Ready nodes, 20 ready running Pods, 15 healthy
  Prometheus targets, both monitoring PVCs Bound, Grafana, six source queries and
  the healthy/Inactive production alert. Argo-related public port probes stayed closed.

[GitOps evidence](evidence/gitops-checks.json), [health](evidence/gitops-health.json),
[manifest comparison](evidence/gitops-manifest-consistency.json) and
[initial publication check](evidence/gitops-publication.json) contain timestamps,
hashes and qualifications. Timestamped raw execution output stays ignored locally.

## Rollback and emergency handback

These are **documented future procedures**, not an executed rollback/uninstall
drill. No data restore, resource deletion, VM rebuild or reboot was performed.

For a faulty app change, revert the offending Git commit, push, then manually
sync the new revert commit. For example, to undo just the demonstration:

```powershell
git revert 9998ec8
git push origin main
python scripts/gitops.py sync --revision (git rev-parse HEAD)
python scripts/review-health.py
```

Do not point Argo at `b3f028c`: that stable commit predates the `gitops/demo` path.
Use a new Git revert/restoration commit that retains the GitOps directory, or
perform the explicit handback below if Argo itself is unavailable.

1. Inspect `argocd/demo` and ensure no sync is running or automatic policy enabled.
   Confirm its deletion finalizers are empty and all seven app objects have
   `Delete=false`. Record the current revision and resource UIDs.
2. Delete **only the Application with orphan semantics**, never its Namespace or
   workload manifests: `k3s kubectl -n argocd delete application demo --cascade=orphan`.
   Verify all demo objects, TLS Secret, Namespace and monitoring remain. If
   finalizers differ from this verified configuration, inspect before deleting.
3. Only after the Application is absent, move the root-only ownership marker to
   a unique protected backup path under `/root/verda-platform-backups/`. This
   permits legacy application management again; do not remove the marker earlier.
4. Recover the reviewed app configuration from stable `b3f028c` as a reference.
   Export/apply only the seven namespaced app objects, excluding its Namespace
   document. Preserve existing TLS Secret and monitoring/RBAC. Verify public
   HTTP/HTTPS, two spread replicas and monitoring before further work.
5. Leave Argo installed but idle while diagnosing it. Uninstalling Argo or deleting
   its namespace/CRDs is a separate administrative operation and was not tested.

This is a single-instance demo controller. No automatic pruning, HA, Git webhook,
external notifications, UI login, credential rotation or backup/restore drill is
claimed. Backup/restore remains the separately completed notes-only bonus.

References: [fixed release](https://github.com/argoproj/argo-cd/releases/tag/v3.5.6),
[installation](https://argo-cd.readthedocs.io/en/stable/operator-manual/installation/),
[sync safety options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/),
[project policy](https://argo-cd.readthedocs.io/en/stable/user-guide/projects/).
