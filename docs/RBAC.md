# Demo namespace reader

The basic RBAC bonus is deployed and verified. Its manifest is
[rbac.yaml](../manifests/rbac.yaml). All three objects are named `demo-reader` in
the **demo** namespace: a ServiceAccount, Role and RoleBinding. No ClusterRole or
ClusterRoleBinding is created, and the running application does not use this
ServiceAccount. Existing application/monitoring Pod specifications are unchanged.

| API group | Resources | Allowed verbs |
|---|---|---|
| core | pods, services | get, list, watch |
| core | pods/log | get |
| apps | deployments | get, list, watch |

There are no wildcard grants. Secrets, ConfigMaps, resource mutations, scaling,
exec/attach/port-forward/proxy, token requests and RBAC administration are not
granted. The RoleBinding is namespace-local, so it grants no access to other
namespaces or cluster resources. Kubernetes' default authenticated API discovery
and self-review permissions remain unchanged; they are not additional grants
from this manifest. See the [RBAC reference](https://kubernetes.io/docs/reference/access-authn-authz/rbac/).

`automountServiceAccountToken: false` prevents automatic credential mounting if
the account is later selected by a Pod. It currently has zero Secret references.
No long-lived token, TokenRequest, client kubeconfig or new public API access was
created. Verification uses an already-authorized administrator over existing SSH.

## Apply and reproduce verification

From the local repository, using the existing SSH agent:

```powershell
python scripts/rbac.py apply
python scripts/rbac.py verify
```

`apply` submits only the three RBAC objects in `rbac.yaml`; `verify` does not apply
manifests. Both record service health before and after testing. The verifier uses
the identity `system:serviceaccount:demo:demo-reader` with its normal groups:
`system:serviceaccounts`, `system:serviceaccounts:demo`, `system:authenticated`.

An administrator can also inspect individual decisions on the server:

```sh
k3s kubectl auth can-i list pods -n demo \
  --as=system:serviceaccount:demo:demo-reader \
  --as-group=system:serviceaccounts --as-group=system:serviceaccounts:demo \
  --as-group=system:authenticated
# yes / exit 0

k3s kubectl auth can-i get secrets -n demo \
  --as=system:serviceaccount:demo:demo-reader \
  --as-group=system:serviceaccounts --as-group=system:serviceaccounts:demo \
  --as-group=system:authenticated
# no / exit 1 (expected)
```

Impersonation requires the caller's existing administrative permission. The
reader Role does not grant impersonation. `can-i` tests authorization without
executing the proposed resource modification. [Command reference](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_auth/kubectl_auth_can-i/)

## Observed verification

[rbac-checks.json](evidence/rbac-checks.json) contains the completion timestamp,
identity/groups, all decisions and exit codes, server-returned Role rules,
before/after availability, and SHA-256 hashes of the YAML and verification tools.
Raw local evidence is in `.local/evidence/20261024T181416Z/`.

* **92 authorization checks passed:** 10 allowed and 82 denied. Coverage includes
  all granted reads, create/update/patch/delete/deletecollection, Secrets,
  default/monitoring/kube-system namespaces, all-namespace lists, cluster Nodes,
  Namespaces, PVs and cluster RBAC resources, and privileged subresources.
* Actual impersonated list requests returned the two application Pods, one
  Service and one Deployment. A real Pod log request succeeded; log contents
  were not retained in the evidence.
* Actual impersonated requests for monitoring Pods and cluster Nodes returned
  **Forbidden**. Mutation and Secret-read prohibitions were verified through
  `can-i`; no real mutations or Secret reads were attempted as tests.
* Application and monitoring Pod UIDs and restart counts were identical before
  and after. Two app replicas remained available; public HTTP/HTTPS index and
  health endpoints returned 200, with health still `text/plain` and `ok\n`.
  Grafana's database health remained `ok`; all 15 Prometheus targets remained up.

This validates the policy on the running cluster using impersonation. It is not
a token authentication or external client credential distribution test. Re-run
the checks after changing this Role or any binding that affects the identity or
its groups. Alerting and Argo CD are outside this change.
