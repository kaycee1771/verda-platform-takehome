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

Fixtures are generated only under ignored `.local/negative-quality-gates/` and removed by an exit
trap. The private key never enters Git, committed evidence, or console output.

The ignored summary is 154 bytes with SHA-256
`88a772b7b9849294a0f616dea014cbee017aea48b4231423d25a522abd8d9742`.
The final negative-suite log is 360 bytes with SHA-256
`9513470aacfd9e45d3cb652b2f5dc6918c94863df00637d27974d32c27c15dea`.
