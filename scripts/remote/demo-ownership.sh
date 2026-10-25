#!/usr/bin/env bash
# Sourced by legacy entry points. No cluster or host mutation.
demo_is_gitops_managed() {
  test -f /etc/verda-platform/demo-gitops.json && return 0
  k3s kubectl -n argocd get applications.argoproj.io demo -o name >/dev/null 2>&1
}
require_legacy_demo_access() {
  if demo_is_gitops_managed; then
    echo 'Demo is managed by Argo CD. Change gitops/demo/app.yaml and sync; legacy apply refused.' >&2
    return 1
  fi
}
