# Kyverno exception contract

No active exception is required by the Phase 6 baseline. An exception is
admitted only when all placeholders in `policy-exception.yaml.tmpl` are
replaced from a reviewed change and the resulting file is added explicitly to
a kustomization.

Every exception must name one policy and rule, one namespace, one resource
kind and name, one service account, and one immutable image digest. It also
requires an accountable owner, concrete reason, and review-by date. Wildcard
namespaces, service accounts, resources, policies, rules, and mutable image
references are prohibited.

The review-by annotation is an operational review gate, not automatic expiry.
The owner removes the exception by that date or submits a new reviewed change
with evidence justifying a bounded extension.
