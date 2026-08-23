# Saved Phase 6 LogQL investigations

`demo-dev-logs.logql` is the baseline saved query required for Platform. It
returns every application stream in `demo-dev` without introducing request ID,
pod identity, path, or error text as an indexed label.

After a demonstrator emits structured JSON, operators may narrow the result by
structured metadata or parsed fields, for example:

```logql
{cluster="management", namespace="demo-dev", application="platform-demo"}
| json
| request_id="$request_id"
```

Grafana is the authenticated query surface. Loki itself has no public ingress.
