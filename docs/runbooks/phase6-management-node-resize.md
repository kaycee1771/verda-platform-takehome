# Phase 6 Management-Node Serial Resize

## Status and scope

This controller is deliberately inert in Git. It permits only a serial
`CPU.4V.16G` to `CPU.8V.32G` replacement (or the exact reverse rollback) for
the three existing management servers. It does not create a cluster, change a
data volume, accept credentials as arguments, activate Phase 6 applications,
or authorize parallel replacement.

**No Phase 6 live resize is currently authorized.** The controller CLI exposes
only `validate-contract`; apply, recovery, and postflight advancement are not
registered commands. The protected Phase 2 apply target also fails before
opening state or invoking Terraform. The protected plan/output primitives and
the collector are preparatory code only. They must not be enabled until the
pinned-container recovery runner, canonical inventory/secret-descriptor
review, trusted collector bindings, quiesce workflow, and OS-lock/journal
integration have landed and received independent review.

The checked-in contract has `enabled=false`, `writes_allowed=false`, a null
integrated commit, and a null target expiry. Never edit it to create a
self-referential commit. For each node, create a protected external copy with
the exact already-integrated commit and reviewed target expiry. The controller
validates every other field and binds that external contract by SHA-256 in the
two-reviewer record.

## Preconditions

Before planning one node:

1. Hold the ignored Phase 6 single-writer lease. No other controller may write.
2. Confirm the authenticated `CPU.8V.32G` on-demand stock, exact price, current
   balance, review-window reserve, and target expiry.
3. Select a non-leader from nodes 02 and 03 first, the other second, and node 01
   last. Transfer etcd leadership before a selected-node plan if necessary.
4. Pass credential-free CI at the exact integrated commit.
5. Verify three Ready nodes, three healthy etcd members and quorum, Cilium
   health/connectivity, and all three Longhorn nodes/disks/volumes healthy with
   no degraded volume.
6. Create and verify an independent encrypted Terraform state backup, a current
   off-cluster etcd snapshot, and a real recovery point for any persistent data.
   Longhorn replication alone is not a backup.
7. Have an author and a distinct security/capacity reviewer approve the exact
   commit, contract hash, preflight hash, and saved-plan hash.

## Per-node desired state and plan

`infra/terraform/environments/management/main.tf` contains a checked-in
per-node lifecycle map. Initially all three nodes retain `CPU.4V.16G` and the
existing expiry. Make three protected commits, each changing only the selected
node's `instance_type` and `resource_expiry_utc`. Do not use `-target`,
`-replace`, a command-line shape override, or one global flavor/expiry change.

With the protected external state opened and initialized by the established
Phase 2 boundary, create an ordinary saved plan outside the repository:

```text
terraform -chdir=infra/terraform/environments/management plan \
  -input=false -lock-timeout=60s -detailed-exitcode -out=<external-node-plan>
```

The preparatory plan parser runs `terraform show -json` itself and
refuses unless the saved plan contains exactly one instance replacement at the
next serial address. The hostname, image, location, on-demand status, OS-volume
contract, SSH keys, startup-script attachment, and exact persistent data-volume
attachment must remain unchanged. The shape and expiry must make the exact
reviewed transition. Apply accepts only those same saved-plan bytes; never
regenerate a plan between review and apply.

The preparatory protected progress object is identity-free and uses this schema:

```json
{
  "schema_version": 1,
  "integrated_commit": "<exact-40-hex-commit>",
  "completed_resize_nodes": [],
  "completed_rollback_nodes": [],
  "generation": 0,
  "used_operation_ids": [],
  "in_flight_node": null,
  "in_flight_direction": null,
  "in_flight_operation_id": null,
  "in_flight_plan_sha256": null,
  "in_flight_recovery_sha256": null,
  "in_flight_started_at": null
}
```

Mark the exact node/direction in flight immediately after a successful saved
plan apply. Do not advance the completed prefix until recovery and postflight
both pass. Back up the updated Terraform state in a `finally` path.

## Replacement recovery and existing-cluster join

A replacement has a new OS disk, public endpoint, SSH host key, WireGuard key,
and RKE2 data directory. The persistent Longhorn data volume is preserved.
After apply and before starting RKE2:

1. Regenerate the three-node inventory from the partial Terraform state using
   `generate-resize-inventory.py`. The inventory, key, verified known-hosts
   file, and runtime variables remain outside Git. Strict host-key checking is
   mandatory; `accept-new` is refused by recovery admission.
2. Independently verify the replacement instance/shape and its new SSH host-key
   provenance, then rotate only that host's known-hosts entry.
3. Prove the two survivors are Ready and retain etcd quorum.
4. Recovery remains disabled. A future reviewed implementation must use the
   pinned Phase 4 container runner with read-only external key/token mounts,
   checked-in group vars, exact runtime vars, and the exact integrated commit;
   native host `ansible-playbook` is not an approved execution path.
5. The playbook bootstraps and hardens only the fresh host, remounts the
   preserved data volume, gathers every node-local WireGuard public key, and
   serially converges all three peer endpoints and firewall rules.
6. From the selected survivor it refuses unless exactly three etcd members
   exist and the stale node is not Ready, removes exactly that named stale
   member, proves the two-member quorum, and removes only the stale Kubernetes
   Node object.
7. The replacement always renders `server:` to an existing survivor. This is
   mandatory for node 01 as well; the empty primary/bootstrap configuration is
   permitted only for the original cluster creation.

Keep the lease after any recovery failure. Do not start another replacement.
Assess the exact rollback or repair while the two survivors retain quorum.

## Postflight and serial advance

Capture a fresh identity-free postflight bundle only after all of these pass:

- three Ready nodes and three healthy etcd members;
- API/quorum and selected-node non-leader safety;
- Cilium healthy on all nodes and connectivity passing;
- Longhorn has three Ready/schedulable nodes, no degraded volumes, and replica
  rebuild complete;
- hardened replacement access, all WireGuard peers converged, and the node
  joined the existing cluster;
- the replacement reports the exact reviewed shape; and
- an ordinary Terraform plan reports zero drift.

Postflight advancement remains disabled. A future reviewed implementation must
hash-bind the collector, operation nonce, plan, recovery receipt, journal
generation, and held OS lease, then atomically advance exactly one completed
prefix and clear the in-flight fields.

## Rollback

Rollback is another reviewed saved-plan replacement, never an imperative
provider resize. Change only one per-node lifecycle entry back to the exact
`CPU.4V.16G` source shape and original expiry. After a completed rollout,
rollback order is 01, 02, 03. An in-flight node that failed postflight may be
rolled back immediately while all other progress remains frozen. The same
backup, non-leader, review, lease, exact-plan, existing-cluster join, Cilium,
etcd, Longhorn rebuild, and zero-drift gates apply.

## Evidence boundary

Controller output contains only node ordinal, direction, coarse gate status,
and SHA-256 bindings. Terraform JSON, provider IDs, addresses, inventory,
known-hosts contents, kubeconfig, credentials, tokens, private keys, raw
Ansible output, and raw cluster output remain in protected ignored/external
storage. A failed command emits only a generic diagnostic and never copies raw
stdout/stderr into evidence.
