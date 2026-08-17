# Verda instance module

This module owns compute and its 80 GiB instance-owned OS disk. A persistent
data volume is supplied via `existing_volumes`, as recommended for standard
NVMe by Verda provider 1.1.2. All provider attributes are replacement-only, so
the module avoids `create_before_destroy`: names and finite account capacity do
not guarantee that old and new nodes can coexist safely.

Provider 1.1.2 accepts the immutable image configuration UUID during create but
returns `image_type` during read, causing an inconsistent-result error. The
root therefore carries both values: the reviewed UUID remains in its contract
and summary output, while this leaf module receives only `ubuntu-24.04` for the
provider field. The calling live preflight must prove that exact slug-to-UUID
mapping before plan or apply. ADR 0012 records the runtime evidence and risk.

The Phase 2 startup boundary is deliberately narrow. Verda injects the SSH key;
no packages, firewall changes, WireGuard, storage formatting, or RKE2 setup run
here. Those operations remain owned by the later idempotent Ansible phase.
