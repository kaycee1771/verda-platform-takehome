output "cluster_name" {
  description = "Logical management-cluster name."
  value       = "verda-mgmt"
  sensitive   = false
}

output "ssh_key_fingerprint" {
  description = "Provider-computed fingerprint of the registered Phase 2 SSH key."
  value       = verda_ssh_key.management.fingerprint
  sensitive   = false
}

output "node_names" {
  description = "Stable node hostnames."
  value       = module.management.node_names
  sensitive   = false
}

output "data_volume_names" {
  description = "Stable persistent volume names."
  value       = module.management.data_volume_names
  sensitive   = false
}

output "nodes" {
  description = "Machine-readable instance and attachment inventory."
  value       = module.management.nodes
  sensitive   = false
}

output "public_addresses" {
  description = "Public addresses keyed by stable hostname."
  value       = { for name, node in module.management.nodes : name => node.public_address }
  sensitive   = false
}

output "ansible_inventory" {
  description = "Canonical inventory model consumed by the generator."
  value = {
    all = {
      children = {
        management_servers = {
          hosts = {
            for name, node in module.management.nodes : name => {
              ansible_host         = node.public_address
              ansible_user         = "root"
              node_name            = name
              role                 = node.role
              internal_ip          = node.private_address
              wireguard_ip         = node.wireguard_address
              data_volume_id       = node.data_volume_id
              attached_device_id   = node.data_volume_id
              data_volume_size_gib = node.data_volume_size_gib
            }
          }
        }
        workload_servers = {
          hosts = {}
        }
        gpu_workers = {
          hosts = {}
        }
      }
    }
  }
  sensitive = false
}

output "infrastructure_summary" {
  description = "Human-readable, non-secret Stage A infrastructure summary."
  value = {
    cluster                   = "verda-mgmt"
    node_count                = length(module.management.node_names)
    data_volume_count         = length(module.management.data_volume_names)
    location                  = var.location
    instance_type             = var.instance_type
    os_image_id               = var.os_image_id
    provider_image_value      = var.provider_image_value
    root_volume_size_gib      = var.root_volume_size_gib
    data_volume_size_gib      = var.data_volume_size_gib
    preserve_data_volumes     = module.management.preserve_data_volumes
    startup_configuration     = "ssh-key-injection-only"
    resource_expiry_utc       = var.resource_expiry_utc
    provider_private_ip_field = "not-exposed-in-provider-1.1.2"
  }
  sensitive = false
}
