# Phase 4 Live Preflight

Rechecked successfully on 2026-08-19 immediately before the staged RKE2 installation. Values that
identify resources, endpoints, or the operator are intentionally omitted.

## Read-only account observations

- PASS: exactly three intended management instances are visible and running in FIN-03.
- PASS: the three instances have unique public endpoints and retain the selected CPU shape and
  Ubuntu 24.04 Minimal OS volumes.
- PASS: the console reports a positive balance, approximately 20 days of runway, and the expected
  rounded Stage A hourly burn.
- PASS: the Cloud API credential remained external and process-only.
- PASS: Terraform reported zero resource drift and the encrypted state plus independent encrypted
  backup passed their recovery checks.
- PASS: no Verda create, update, power, transfer, or delete action was invoked.

## Host and access boundary

- PASS: the explicitly authorized rollback-protected allowlist reconciliation retained exact
  administrator sources and restored fresh strict-host-key access to every server.
- PASS: pinned identities, named administration, all six WireGuard peer paths, handshakes, data
  mounts, firewall service, time, and Phase 3 host controls passed on all three servers.
- PASS: the live controller and node route comparison found no cluster-CIDR overlap.
- PASS: the preflight reconciled exactly three instances and six volumes at the established
  `$0.23165/hour` infrastructure run rate.

The prior changed-source blocker was resolved through the authorized timed-rollback workflow, not a
broad public exception. The exact source CIDRs remain external runtime inputs and are not recorded
here. No cloud resource was created, replaced, resized, powered, or deleted during Phase 4.
