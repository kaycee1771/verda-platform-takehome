output "nodes" {
  description = "Node-specific outputs required by deterministic inventory generation."
  value = {
    for ordinal, node in var.nodes : "${var.cluster}-server-${ordinal}" => {
      id                     = module.node[ordinal].id
      name                   = module.node[ordinal].name
      public_address         = module.node[ordinal].public_address
      private_address        = module.node[ordinal].private_address
      wireguard_address      = try(node.wireguard_address, null)
      role                   = node.role
      attached_volume_ids    = module.node[ordinal].attached_volume_ids
      data_volume_id         = module.data_volume[ordinal].id
      data_volume_name       = module.data_volume[ordinal].name
      data_volume_size_gib   = module.data_volume[ordinal].size_gib
      attachment_instance_id = module.data_volume[ordinal].attachment_instance_id
      os_volume_id           = module.node[ordinal].os_volume_id
      status                 = module.node[ordinal].status
      compute_price_per_hour = module.node[ordinal].price_per_hour
    }
  }
  sensitive = false
}

output "node_names" {
  description = "Stable node names in lexical order."
  value       = sort([for ordinal in keys(var.nodes) : "${var.cluster}-server-${ordinal}"])
  sensitive   = false
}

output "data_volume_names" {
  description = "Stable persistent volume names in lexical order."
  value       = sort([for ordinal in keys(var.nodes) : "${var.cluster}-data-${ordinal}"])
  sensitive   = false
}

output "preserve_data_volumes" {
  description = "Explicit durable-volume lifecycle contract."
  value       = var.preserve_data_volumes
  sensitive   = false
}
