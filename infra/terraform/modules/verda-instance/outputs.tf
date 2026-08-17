output "id" {
  description = "Verda instance identifier."
  value       = verda_instance.this.id
  sensitive   = false
}

output "name" {
  description = "Stable node hostname."
  value       = verda_instance.this.hostname
  sensitive   = false
}

output "public_address" {
  description = "Provider-assigned public address."
  value       = verda_instance.this.ip
  sensitive   = false
}

output "private_address" {
  description = "Private address; provider 1.1.2 exposes no such attribute."
  value       = null
  sensitive   = false
}

output "role" {
  description = "Future RKE2 role."
  value       = var.role
  sensitive   = false
}

output "attached_volume_ids" {
  description = "Persistent volume identifiers passed through existing_volumes."
  value       = var.data_volume_ids
  sensitive   = false
}

output "os_volume_id" {
  description = "Provider-created, instance-owned OS volume identifier."
  value       = verda_instance.this.os_volume_id
  sensitive   = false
}

output "status" {
  description = "Current Verda instance state."
  value       = verda_instance.this.status
  sensitive   = false
}

output "price_per_hour" {
  description = "Live provider-reported compute price in USD/hour."
  value       = verda_instance.this.price_per_hour
  sensitive   = false
}
