output "id" {
  description = "Verda volume identifier."
  value       = verda_volume.this.id
  sensitive   = false
}

output "name" {
  description = "Deterministic volume name."
  value       = verda_volume.this.name
  sensitive   = false
}

output "size_gib" {
  description = "Provisioned volume capacity in GiB."
  value       = verda_volume.this.size
  sensitive   = false
}

output "attachment_instance_id" {
  description = "Instance currently reported by Verda for this volume."
  value       = verda_volume.this.instance_id
  sensitive   = false
}

output "deletion_protection" {
  description = "Effective lifecycle guard for the volume."
  value       = var.deletion_protection
  sensitive   = false
}
