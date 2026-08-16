# Terraform

Terraform 1.15.8 and Verda provider 1.1.2 are pinned. Phase 1 contains only the read-only provider
discovery root retained from Phase 0 plus empty, owned module/environment boundaries. Resource
modules and state backends begin in Phase 2 after Cloud API credentials are supplied out of band.

The `object-storage` module is deliberately absent: the verified provider schema exposes no object
storage resource. Phase 5 must select and verify an approved S3-compatible fallback before adding it.
