# Verda cluster composition module

This module composes exactly three node modules and three independently owned
data-volume modules. It intentionally exposes every node-specific value needed
by Ansible instead of hiding the infrastructure behind a cluster abstraction.

`preserve_data_volumes` is explicit and must remain `true` in Phase 2. The
underlying provider has no cloud-native delete-protection field, while Terraform
lifecycle directives accept only literal values. The child volume module
therefore protects only durable data volumes with literal `prevent_destroy`.
