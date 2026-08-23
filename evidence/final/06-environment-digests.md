# Environment Digests

| Namespace | Ready replicas | Image |
|---|---:|---|
| demo-dev | 1/1 | `harbor.95-133-252-214.nip.io/platform-demo/platform-demo@sha256:1d48...289d` |
| demo-staging | 1/1 | same digest |
| demo-prod | 2/2 | same digest |

Public checks returned HTTP 204:

- `https://platform-dev.95-133-252-214.nip.io/healthz`
- `https://platform-staging.95-133-252-214.nip.io/healthz`
- `https://platform-prod.95-133-252-214.nip.io/healthz`

All six staging/production environment certificates were Ready.
