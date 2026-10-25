# Demo application source

`app.yaml` is the desired state of the existing demo application after Argo CD
adoption. It contains seven existing objects and excludes Namespace, Secrets,
monitoring and RBAC. `demo-tls` remains managed by the original platform workflow;
the Ingress/TLSStore only reference it.

All objects use `Prune=false,Delete=false`. The Application starts with manual
sync and no deletion finalizer. The legacy `manifests/app.yaml` remains a recovery
reference; protected scripts do not apply it after adoption. Do not edit both
copies to operate the app. See [GitOps operations](../../docs/GITOPS.md).
