# Verda persistent volume module

This module owns one standard `NVMe` volume independently from compute. Its
`prevent_destroy` lifecycle rule is intentionally literal: Terraform processes
lifecycle rules before variables, so a dynamic protection toggle would be
misleading. Only durable data volumes receive the rule.

Provider 1.1.2 recommends attaching standard NVMe volumes through an instance's
`existing_volumes` argument. That creates a clean ownership boundary: replacing
compute does not ask the Verda API to delete the separately managed data volume.
Deleting data requires a reviewed change to this module plus the two-part
destructive confirmation documented in the teardown runbook.
