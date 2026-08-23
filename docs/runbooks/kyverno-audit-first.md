# Kyverno Audit-first operation

## Impact

Kyverno Phase 6 records policy violations without denying workloads. A
controller outage degrades admission reporting and background scans but must
not block platform recovery while `forceFailurePolicyIgnore` is enabled.

## Detection

- One of the admission replicas is unavailable.
- Background or reports controller is unavailable.
- A Kyverno metrics Service is missing or its ServiceMonitor target is down.
- Policy reports contain new failures in `demo-dev`, `demo-staging`, or
  `demo-prod`.
- An exception reaches its review-by date.

## Immediate checks

1. Verify all expected Kyverno Applications are Healthy and Synced.
2. Verify two admission replicas and one background and reports replica.
3. Inspect controller conditions and sanitized warning events.
4. Query PolicyReports by policy, rule, namespace, and result. Do not dump
   Secrets or admission payloads.
5. Confirm every ClusterPolicy still has `validationFailureAction: Audit`,
   `background: true`, and `failurePolicy: Ignore`.

## Exception review

Reject an exception unless it identifies an exact policy and rule, namespace,
kind, resource name, service account, immutable image digest, owner, reason,
and review-by date. Wildcards and platform-namespace exclusions are not valid
substitutes for compatibility work.

Remove expired or unused exceptions through Git. The review-by annotation is
not automatic expiry, so the owner must prove the review occurred.

## Safe remediation

- Correct incompatible desired state in Git and allow Argo CD to reconcile.
- Revert a bad policy commit rather than editing the live ClusterPolicy.
- Scale only within the capacity worksheet and preserve two admission replicas
  when one-node-loss capacity admits them.
- Keep the cleanup controller disabled until a reviewed CleanupPolicy exists.

## Recovery validation

- All controllers are Ready and metrics targets are up.
- Background scans produce current reports.
- Known compliant fixtures pass and deliberately non-compliant fixtures appear
  as Audit violations without admission denial.
- No policy is in Enforce mode and no broad exception exists.

## Escalation

Phase 12 owns any move to enforcement. Do not change failure policy or
validation action during Phase 6 incident response.
