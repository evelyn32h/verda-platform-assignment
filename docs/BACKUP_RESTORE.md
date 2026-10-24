# Backup and recovery notes

Status: **documentation complete; backup and recovery execution untested**.
This change performed read-only storage inspection on 24 October 2026. It did
not stop services, scale workloads, copy live databases, create snapshots, or
restore data. The owner separately confirmed the public app, health endpoint
and six Grafana panels. That acceptance does not constitute a recovery test.

## Actual storage layout

The server is `verda-k3s-server` (95.133.252.141), running k3s
`v1.35.9+k3s1` with SQLite. `server/db/state.db`, its WAL and SHM files exist
under `/var/lib/rancher/k3s/`. The server token and Secrets encryption
configuration are present; their contents were not read.

Both monitoring PVCs are Bound, use `local-path`, have **Delete** reclaim policy,
and are pinned by PV node affinity to `verda-k3s-server`:

| Component | PVC / capacity | Container data path | Backup requirement |
|---|---|---|---|
| Grafana | `monitoring-grafana` / 2 GiB | `/var/lib/grafana` | Entire PV directory, including observed `grafana.db`, plugins and other persistent files |
| Prometheus | `prometheus-monitoring-prometheus-db-prometheus-monitoring-prometheus-0` / 10 GiB | `/prometheus` | Entire PV directory; its **`prometheus-db` subdirectory** is mounted at `/prometheus` |

The complete current PV names, host paths, node affinity and mount details are in
[backup-inventory.json](evidence/backup-inventory.json). Rediscover and record
them for each future backup; a newly provisioned PVC may have another UUID/path.
The application has no PVC: its HTML, nginx configuration and health file come
from the versioned ConfigMaps, while its temporary directory is disposable.

Prometheus has one replica and configured retention of 2 days / 4 GB, whichever
limit is reached first. Its admin API is **disabled**. Grafana has one replica
and an observed SQLite file. The backup procedure below therefore uses a future
maintenance window rather than assuming an available live snapshot facility.

## Backup coverage and exclusions

Treat one recovery set as the following components, captured in one coordinated
window and catalogued with UTC time, Git revision, versions and checksums:

| Layer | Include | What it restores |
|---|---|---|
| Control plane | Entire `/var/lib/rancher/k3s/server/`, including `db/`, `token`, `cred/`, `tls/` and server manifests; `/etc/rancher/k3s/`; `/etc/rancher/node/` | Kubernetes objects, PV/PVC bindings, cluster identity, bootstrap credentials and Secrets encryption material |
| Host configuration | `/etc/verda-platform/`, `verda-firewall.service`, `/usr/local/sbin/verda-firewall`, `/etc/sysctl.d/90-verda-platform.conf` | Firewall/sysctl configuration and generated demo TLS/bootstrap material |
| Grafana data | Complete host directory backing its PV | UI-created users, dashboards and preferences in SQLite, and persistent plugins/files |
| Prometheus data | Complete host directory backing its PV, including `prometheus-db/` and its blocks, WAL and head data | Metric history present at the backup cutoff |
| Rebuild information | Git repository/revision; `platform.json`; actual image versions; PV/PVC/StorageClass metadata; original workload replica counts | Reproduction and interpretation of the recovery set |

The **matching server token is required** to recover the saved datastore. This
cluster also encrypts Kubernetes Secrets at rest, so retain its encryption
configuration under `server/cred/` with the same set. Do not mix credentials or
encryption keys from another date/cluster. K3s's documented datastore copy does
not include PV file contents. [K3s backup reference](https://docs.k3s.io/datastore/backup-restore)

The SQLite datastore includes the `grafana-admin` and demo TLS Secrets and their
Kubernetes configuration objects. It does not contain Grafana's database or
Prometheus samples. The Git-provisioned dashboard can be recreated from Git;
UI changes require the Grafana data backup. Preserve Grafana's configuration
and any configured encryption secret with its database, not just dashboard JSON.
[Grafana backup reference](https://grafana.com/docs/grafana/latest/administration/back-up-grafana/)

The worker has no persistent application volume at this inspection. Record its
hostname, node password/configuration and join configuration in the protected
recovery set if retaining its identity; otherwise plan a controlled rejoin.
Do not back up SSH private keys into this repository. Container image caches,
running processes, ephemeral Pod files/logs, VM provisioning and provider network
configuration are outside the data archives and must be recreated separately.
The existing `/root/verda-platform-backups/` folders are firewall/configuration
rollback records, **not complete cluster or monitoring data backups**.

## Consistent backup procedure — future maintenance only

**None of this procedure was executed for this documentation change.** It entails
temporary monitoring/control-plane downtime and requires a separately scheduled
window. A plain filesystem copy of an active SQLite database or its WAL is not
an established consistent backup. [SQLite consistency guidance](https://sqlite.org/howtocorrupt.html#_backup_or_restore_while_a_transaction_is_active)

1. While the API is available, record the Git revision, installed versions,
   replica counts (currently Grafana 1, Prometheus 1), PVC-to-PV host paths,
   numeric ownership and permissions. Save PV/PVC/StorageClass metadata into a
   protected staging directory outside the PVs. Confirm sufficient free disk
   and the availability of the encryption/decryption keys and off-host destination.
2. Quiesce **both** monitoring writers. Scale `deployment/monitoring-grafana`
   to zero and change **`prometheus/monitoring-prometheus.spec.replicas`** to zero.
   The Prometheus Operator owns its StatefulSet; scaling only the StatefulSet
   may be undone by reconciliation. Wait for the Grafana and Prometheus Pods
   and their containers to terminate before copying either volume.

   The following illustrates those future actions, not a command to run now:

   ```sh
   k3s kubectl -n monitoring scale deployment/monitoring-grafana --replicas=0
   k3s kubectl -n monitoring patch prometheus monitoring-prometheus --type=merge -p '{"spec":{"replicas":0}}'
   k3s kubectl -n monitoring get pods
   ```

3. With the data writers stopped, stop k3s on the server and confirm the service
   is inactive before copying its SQLite directory. Stopping k3s alone does not
   prove Grafana/Prometheus containers have stopped. Copy the entire control-plane
   and configuration set listed above. Preserve all database sidecar files still
   present; never combine a database with a WAL from another copy.
4. Archive each **PV root directory's contents**, separately. For Prometheus this
   includes the `prometheus-db/` level; do not accidentally create a second
   nested `prometheus-db/prometheus-db` directory during restoration. Preserve
   numeric UID/GID, modes, symlinks, ACLs and extended attributes, for example
   using GNU tar's `--numeric-owner --acls --xattrs` with root privileges. Record
   the source PV path and archive root convention in the backup manifest.
5. Restart k3s, wait for API readiness, restore the recorded desired replica counts
   (Prometheus CR and Grafana Deployment), and wait for both to become healthy.
   The datastore copy intentionally contains zero monitoring replicas from the
   quiesced point; retain the original counts in the recovery manifest. Resume
   services even if archive/off-host transfer fails; report that backup as incomplete.
6. Check archive readability and hashes. On a disposable extracted copy, perform
   SQLite integrity checks with suitable tooling; do not experiment on the live
   databases. Encrypt the recovery set, transfer it off the server, verify the
   destination copy/checksums and protect the decryption key independently. A
   plaintext root-only staging copy on the same VM is not disaster recovery.

These commands would need operational validation before automation; no backup
script, schedule, encryption tool or remote backup destination was installed.
Only declare a recovery set usable after its complete components are accessible
and an isolated recovery exercise has succeeded.

For future online Prometheus backup, its snapshot admin API would need controlled
enablement and validation, including head samples and off-host export. It is not
enabled or called here. A raw copy that omits head/WAL can lose recent samples;
neither that nor a provider crash-consistent disk snapshot is claimed equivalent
to the coordinated procedure. [Prometheus storage guidance](https://prometheus.io/docs/prometheus/latest/storage/)

## Restore the same cluster identity and PV bindings

This is an **unexecuted recovery procedure**, preferably rehearsed on an isolated
replacement VM first. It is not an instruction to overwrite the live assignment.

1. Select a complete recovery set, verify hashes and decrypt into protected staging.
   Confirm the matching token, encryption keys, SQLite data, both PV archives,
   configuration, versions and original replica counts are all present. Restore
   monitoring chart `90.1.2` and its recorded image versions before considering
   an upgrade; do not combine database schema/TSDB changes with recovery. Verify
   free space. Retain the current/recoverable state separately for rollback.
2. Fence the original failed server so it cannot return concurrently. Use the
   same k3s version and server hostname. On a replacement, install the binary and
   service **without starting them**. Check actual IP addresses, routing, TLS SANs,
   SSH source allowlist and peer configuration before reusing saved network files.
   Different addresses need a separately planned migration, not blind extraction.
3. Keep k3s and all monitoring writers stopped while restoring. A stopped k3s
   service alone is insufficient if old containers remain: explicitly quiesce
   them. Do not run uninstall scripts, delete PVCs, or use etcd snapshot/cluster-reset
   commands; this is SQLite recovery. Stage and preserve existing data before
   replacing it; never extract over an active datastore or active PV.
4. Restore the saved server directory, node identity and configuration to their
   recorded locations, retaining their ownership and restrictive credential
   permissions. The database and original token/Secrets keys must belong to the
   same recovery set. Restore the host service/configuration files deliberately;
   validate the firewall allowlist through the provider console before enabling it.
5. Restore each PV archive into the **original recorded hostPath**, on the node
   named by its PV affinity. With the full datastore restored, the original PVC,
   PV names and claim UIDs remain paired. Grafana's PV root contains `grafana.db`;
   Prometheus's PV root contains `prometheus-db/`. Preserve the archived numeric
   ownership: observed Grafana UID/GID 472:472 and Prometheus runtime UID/GID
   1000:2000. Its PV root was root:2000; do not recursively replace every owner
   with a guessed account. Missing directories/permissions can yield empty or
   unwritable monitoring instances rather than recovered data.
6. Start the server, wait for `/readyz`, and confirm the expected nodes and **original
   PVCs/PVs** are Bound. Reconnect the existing worker using its retained node
   identity and credentials. If rebuilding the worker, handle registration against
   the restored cluster deliberately; do not print join credentials or regenerate
   the server token. Restore Grafana's Deployment and Prometheus CR replica counts
   only after their data paths and bindings are correct.
7. Check app HTTP/HTTPS and `/healthz`, metrics API, monitoring PVCs, all 15 expected
   scrape targets, and Grafana login plus all six panels. Allow fresh Pod metrics
   to arrive. Check a historical Prometheus interval before the backup cutoff and
   a saved Grafana UI change/user: fresh healthy Pods alone do not prove historical
   data recovery. Check Secret decryption through actual workload use. Record
   elapsed recovery time, backup cutoff and lost data, then approve reopening access.

## Limits and untested parts

* **Delete policy / local disk:** deleting these PVCs may delete their host data.
  Chart uninstall, Namespace deletion and k3s uninstall are not backup operations.
  Two cluster nodes do not replicate these server-local monitoring volumes.
  [Local-path behavior](https://github.com/rancher/local-path-provisioner)
* **Fresh cluster differs:** applying manifests to a new empty datastore creates
  new PVC UIDs/paths. It does not automatically attach old directories or restore
  users, Secrets and history. Restoring only a PV without its database metadata
  requires a separate, explicit PV rebinding/data migration plan with writers
  stopped; that path is not automated or tested here.
* **Not one universal point in time:** components are quiesced sequentially. The
  recovery manifest must record per-component cutoffs and the common maintenance
  window. Prometheus history already removed by retention cannot be recovered
  from a later backup. An expired demo TLS certificate still needs renewal.
* **No demonstrated RPO/RTO:** no data backup, encrypted off-host transfer,
  decryption, integrity test or recovery drill was performed. There is no scheduled
  backup policy or verified recoverable copy in this hand-in. RPO would depend on
  the last complete tested backup; RTO is unmeasured.
* **Scope of verification:** only current storage metadata, files' existence,
  ownership/mounts, reclaim policy and configured snapshot API availability were
  inspected. No secret values or database rows were read, and no configuration
  was changed. This completes the backup/recovery **notes** bonus only.
