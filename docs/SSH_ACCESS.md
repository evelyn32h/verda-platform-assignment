# Management access change — closed

On 25 October 2026 the owner returned to the original Wi-Fi and then cancelled
the proposed `92.34.3.207/32 → TCP 22` access change. That new source was **never
validated by SSH**. The original authorized source remains `81.226.0.124/32`.

## Actual execution and closure

* Both original-source SSH preflights passed before staging.
* Both new grants were staged with 15-minute systemd rollback timers armed before
  changing policy. Only one tagged TCP 22 input rule per host was inserted; the
  matching persistent line and address registry were updated. All original input
  rules and the entire forward chain were preserved. Live `nft -c` checks passed.
* At cancellation both operations were PENDING and both timers were active.
  The original-source SSH connection was still working on both VMs.
* At approximately **15:57:16 UTC**, the frozen per-operation helper withdrew the
  tagged rule on each host, restored the exact pre-change persistent configuration
  and registry state, and verified all original input rules plus unchanged forward
  chains. Only then were the corresponding timers stopped. Both operations are
  ROLLED_BACK. The previously absent address-registry files were removed as part
  of restoring their original state.
* Fresh SSH to both VMs subsequently passed from `81.226.0.124`. The full read-only
  health review passed. No VM/service restart, other-port change, application
  redeployment or monitoring change was performed.

[Sanitized closure evidence](evidence/admin-access-withdrawal.json) and
[health evidence](evidence/delivery-health.json) are included. Timestamped raw
staging/inspection/closure output remains ignored under `.local/evidence/`;
root-only snapshots remain on the VMs as operation records, not data backups.

## Retained scripts and safeguards

[Remote helper](../scripts/remote/admin-access.py) and
[node-preparation script](../scripts/remote/prepare-node.sh) were synchronized
before staging, with prior script copies saved under root-only backup folders.
They are retained on both VMs. Node preparation was **not executed**. The generator
preserves approved existing sources and refuses overlapping pending operations;
it contains no hard-coded grant for the cancelled address. No whitelist action
is pending or scheduled.

[Local driver](../scripts/admin-access.py) exposes explicit staging/confirmation
commands for a future separately authorized change. It does nothing automatically.
Confirmation probes all requested VMs over fresh SSH before confirming either;
the remote helper requires the server-observed SSH source to equal the approved
/32 and checks policy hashes and original rules before stopping its own timer.
An expired or failed verification must be inspected through an existing authorized
management path. Do not rerun deployment to repair a management-network change.

Seven simulated-backend tests passed for narrow insertion, timer ordering,
rollback, source-bound confirmation, prefix validation and source preservation:

```powershell
python -m unittest discover -s tests -p test_admin_access.py -v
```

Live staging and withdrawal were verified on both VMs. New-Wi-Fi SSH and the
successful-confirmation path were not exercised live because the owner cancelled
that plan. No private key content was read or passphrase removed.
