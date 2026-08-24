# Harbor

Argo CD reconciles the sealed credentials, PostgreSQL and pinned Harbor chart in dependency order.
Harbor stores the private `platform-demo` image and Trivy scan result. The evaluator account has
guest access to the project and cannot push or administer the registry.

Credentials remain outside Git. Persistent registry and database data use Longhorn-backed claims;
the documented backup procedure is required before destructive recovery.
