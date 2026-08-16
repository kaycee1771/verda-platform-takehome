# Phase 1 Negative Quality-Gate Evidence

## Result

`make validate-negative`: **PASS**

| Deliberately invalid input | Expected control | Result |
|---|---|---|
| Malformed Terraform expression | `terraform fmt -check` returns non-zero | REJECTED |
| ConfigMap with schema-invalid `data` | Strict Kubernetes 1.35 Kubeconform | REJECTED |
| Unknown custom-resource API | Missing local CRD schema remains fatal | REJECTED |
| Broken PromQL alert expression | `promtool check rules` returns non-zero | REJECTED |
| Generated Ed25519 private key | Gitleaks directory scan with full redaction | REJECTED |
| Mismatched GitHub Action SHA | Workflow reference differs from `versions.lock.yaml` | REJECTED |

Fixtures are generated only under ignored `.local/negative-quality-gates/` and removed by an exit
trap. The private key never enters Git, committed evidence, or console output.

The ignored summary and suite transcript are regenerated and rehashed whenever the rejection
contract changes; committed evidence records outcomes rather than treating stale hashes as proof.
