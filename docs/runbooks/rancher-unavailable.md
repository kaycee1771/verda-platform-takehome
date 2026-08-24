# Rancher Unavailable

## Impact

The Rancher UI or API is unavailable for cluster inspection. Kubernetes and Argo CD continue to
operate independently. Use the protected direct kubeconfig for read-only diagnosis; do not rebuild
or replace the cluster because Rancher is unavailable.

## Detection

- `https://rancher.95-133-252-214.nip.io/ping` does not return `pong`.
- The `rancher` Deployment in `cattle-system` is not Available.
- The production Certificate is not Ready, or the public TLS handshake fails.

## Immediate checks

1. Confirm all three nodes are Ready and the Kubernetes API is healthy.
2. Check the Rancher Deployment, pods, Service, EndpointSlices, Ingress and Certificate.
3. Check recent Rancher and Traefik events and sanitized logs.
4. Distinguish service availability from local-user authentication. A `401` from
   `/v1-public/login` with `/ping` healthy is an authentication defect, not an outage.

## Diagnosis

- No ready endpoint: inspect scheduling, image pull, storage and readiness events.
- TLS failure: verify the exact hostname, Certificate, Secret metadata and Traefik route.
- HTTP 401 only: verify the local AuthConfig, user enabled state and assigned roles. Do not edit
  password hashes or salts directly.
- UI healthy but cluster missing: inspect Rancher cluster registration and agent status without
  changing registration tokens.

## Safe remediation

- Reconcile only the Git-owned Rancher Application through Argo CD.
- For a stuck pod, allow the Deployment controller to replace it after confirming cluster health.
- For evaluator login, use Rancher's supported password-change API from an already authenticated
  administrator session. If no such session exists, retain the short-lived read-only kubeconfig
  fallback and record the access exception.
- Never disable TLS verification, broaden RBAC, expose the Kubernetes API, or replace Rancher data.

## Escalation

Stop when recovery would require an upgrade, data migration, administrator credential reset without
a supported session, cluster recreation or a change outside the pinned release.

## Recovery validation

- Deployment Available and pod Ready.
- `/ping` returns `pong` through the public hostname with valid TLS.
- Rancher shows the local cluster Active.
- Evaluator login succeeds and can view, but not create, update or delete cluster resources.
- The direct read-only kubeconfig still works independently.

## Rollback

Revert only the reviewed Git change that caused the failure and let Argo CD reconcile it. Do not use
the upstream uninstall path or delete the `cattle-system` namespace. If authentication remains
broken after service recovery, leave the platform running and use the documented read-only
kubeconfig fallback.

## Related dashboards and queries

- Grafana platform overview dashboard.
- Prometheus `up` target for Rancher internal metrics.
- `kubectl -n cattle-system get deploy,pod,svc,endpointslice,ingress,certificate`.
