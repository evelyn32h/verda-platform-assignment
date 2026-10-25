# Simple application alert

This adds one custom PrometheusRule through the existing Prometheus Operator.
It does not install another monitoring stack or enable Alertmanager.

## Rule and response

[alerts.yaml](../manifests/alerts.yaml) creates `monitoring/demo-availability`,
labeled `release: monitoring` to match the live Prometheus rule selector.
The rule group evaluates every **15 seconds**:

```promql
kube_deployment_status_replicas_available{deployment="demo",namespace="demo"} < 2
```

`DemoAvailableReplicasLow` becomes Pending when fewer than two application
replicas are available. It becomes Firing only if the same condition remains
true for **2 continuous minutes**. Severity is `warning`. When availability
returns to at least two, it becomes Inactive on a subsequent successful
evaluation; no `keep_firing_for` delay is configured.

Two is the intended availability floor for this assignment, including when an
operator changes the Deployment's desired count. Intentional long-term capacity
changes should update this policy deliberately. The source is kube-state-metrics;
an absent metric is not treated as zero. This single rule does not independently
detect a deleted Deployment or a monitoring data outage.

When it fires, use the existing operator SSH access to:

1. Inspect `k3s kubectl -n demo get deployment demo` and `get pods -o wide` for
   available replicas, readiness and restarts.
2. Inspect Pod events/logs and node capacity for scheduling, image pull, resource
   or application failures. The read-only demo Role does not grant event/node
   access; use appropriate operator privileges for those checks.
3. If a recent release introduced the failure, restore the known-good revision
   using the [documented rollout procedure](OPERATIONS.md#application-rollback).
   Confirm two available replicas and healthy HTTP/HTTPS before closing the issue.
   Do not lower the threshold merely to silence an unexplained outage.

The condition, duration and handling advice are also recorded in the rule's
annotations. [Prometheus alert semantics](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)

## Rule triggering is separate from notification delivery

The inspected Helm configuration has `alertmanager.enabled: false` and
`defaultRules.create: false`. The live cluster has no Alertmanager resources;
Prometheus reported no active or dropped Alertmanager targets and no configured
alerting endpoint. These settings are preserved. Custom rules are discovered by
the existing Operator using its `release: monitoring` selector.

Prometheus can evaluate rules and expose Pending/Firing states without a
notification destination. **No email, webhook, messaging receiver or external
notification channel is configured or tested. No notification was sent.**
The test refuses to proceed if it finds an Alertmanager resource or active
notification target. Recovery below means the Prometheus alert is Inactive and
absent from its active-alerts API; it is not a delivered "resolved" message.

## Reproduce the bounded test

From the local repository with the existing SSH agent:

```powershell
python scripts/alerts.py apply-test
```

This applies only the permanent rule, checks actual discovery/evaluation, and
uses a uniquely named temporary PrometheusRule in `monitoring`:

| Phase | Synthetic expression | Duration / evaluation | Expected observation |
|---|---|---|---|
| Below threshold | `vector(1) < 2` | `for: 30s`, interval 5s | Pending, then Firing |
| Recovered | `vector(2) < 2` | Same rule and labels | Inactive after a fresh evaluation; no active test alert |
| Cleanup | Delete only the temporary CR | Wait for Operator/Prometheus reload | Test rule unloaded; permanent rule retained |

The synthetic rule has a separate alert name, unique `test_id` and `severity: test`.
It exercises the same rule-loading/evaluation pipeline without changing app
replicas, metric exporters, live data or workload health. Its faster timer is an
accelerated engine test; it is not evidence of an actual two-minute app outage.
The permanent rule's loaded 120-second duration is checked separately.

Cleanup runs in `finally`, including ordinary failures and handled interruption
signals. If the process is forcibly killed or loses access before cleanup,
inspect the recorded exact temporary resource name, remove that CR only, and
confirm its rule and active alert have disappeared. Historical `ALERTS` samples
may remain under normal retention; no TSDB data deletion is needed.

The verifier records before/after Pod identities, restart counts, external
HTTP/HTTPS responses, Grafana database health and all 15 scrape targets.
It uses existing API access over SSH; no public endpoint or credential is added.

## Verification evidence

The completed run is recorded in [alert-checks.json](evidence/alert-checks.json),
including the loaded production rule, timestamped state transitions, recovery
evaluation, test configuration, cleanup and before/after service health.
On 24 October 2026, the synthetic alert was observed Pending at **18:28:30 UTC**,
Firing at **18:29:01 UTC**, and Inactive at **18:29:36 UTC**. Cleanup completed
at **18:30:45 UTC**: the test CR was absent, its rule unloaded, and active test
alerts were zero. A later read-only inspection found only the production rule,
healthy and Inactive with two available replicas. The application and monitoring
Pod UIDs/restart counts matched the pre-test baseline; external HTTP/HTTPS,
Grafana health and all 15 scrape targets remained healthy. Raw execution evidence
is preserved locally in `.local/evidence/20261024T182626Z/`.
This proves rule processing, not notification delivery. Argo CD was outside
this work.
