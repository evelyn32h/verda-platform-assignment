# Argo CD / GitOps — preparation

Stable baseline: `b3f028c`. Public source:
https://github.com/evelyn32h/verda-platform-assignment, branch `main`.
The original six-commit history and all 46 published file blobs matched GitHub
after initial publication. The assignment PDF and private/raw directories were
never part of the reachable history. No force push or history rewrite occurred.

Status: source/configuration prepared; installation, adoption and Git-change
verification are not yet claimed complete. Evidence will be added after actual
execution.

The application source is `gitops/demo/app.yaml`; Argo configuration is separately
under `gitops/argocd/`. Namespace, Secrets, monitoring and RBAC are excluded from
the Application. TLS remains under the existing platform workflow. A restricted
AppProject only permits this repository, the `demo` destination and the five
required resource kinds. Standard non-HA Argo CD control-plane installation has
cluster-level controller privileges; the AppProject is a policy boundary, not a
claim of namespace-only controller RBAC.

Argo CD is pinned to **v3.5.6** and the official manifest SHA-256 in
[version-lock.json](../gitops/argocd/version-lock.json). Argo services remain
ClusterIP with no Ingress, NodePort or LoadBalancer. Access uses an owner SSH
tunnel; no host firewall, VM network, public listener or existing ingress change
is part of this installation. No external notification channel is configured.

Initial sync is manual with prune disabled; every app object also carries
`Prune=false,Delete=false`. The Application has no cascading deletion finalizer.
The namespace and existing TLS Secret are not Argo resources. The first sync
preserves the application spec and content while adopting metadata/field ownership.
Legacy scripts check the Argo Application and a root-only ownership marker before
applying the old manifest. A later Git commit will change only the demo HTML
ConfigMap, keeping replicas and probes intact.

References: [fixed release](https://github.com/argoproj/argo-cd/releases/tag/v3.5.6),
[installation](https://argo-cd.readthedocs.io/en/stable/operator-manual/installation/),
[sync safety options](https://argo-cd.readthedocs.io/en/stable/user-guide/sync-options/),
[project policy](https://argo-cd.readthedocs.io/en/stable/user-guide/projects/).
