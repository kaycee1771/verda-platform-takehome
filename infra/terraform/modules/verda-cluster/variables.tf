variable "cluster" {
  description = "Deterministic cluster identifier used as the resource-name prefix."
  type        = string

  validation {
    condition     = contains(["verda-mgmt", "verda-workload"], var.cluster)
    error_message = "Cluster must be verda-mgmt or verda-workload."
  }
}

variable "nodes" {
  description = "Three-node topology keyed by two-digit ordinal."
  type = map(object({
    role                = string
    wireguard_address   = optional(string)
    instance_type       = string
    resource_expiry_utc = string
  }))

  validation {
    condition     = length(var.nodes) == 3
    error_message = "A cluster must contain exactly three nodes."
  }

  validation {
    condition     = alltrue([for ordinal in keys(var.nodes) : can(regex("^[0-9]{2}$", ordinal))])
    error_message = "Node keys must be two-digit ordinals."
  }

  validation {
    condition = alltrue([
      for node in values(var.nodes) : length(trimspace(node.instance_type)) > 0
    ])
    error_message = "Every node lifecycle entry must carry a non-empty instance type."
  }

  validation {
    condition = alltrue([
      for node in values(var.nodes) : can(formatdate("YYYY-MM-DD'T'hh:mm:ssZ", node.resource_expiry_utc))
    ])
    error_message = "Every node lifecycle entry must carry an RFC3339 expiry."
  }
}

variable "provider_image_value" {
  description = "Provider-stable API image_type verified by the calling root."
  type        = string
}

variable "ssh_key_ids" {
  description = "Registered SSH key identifiers attached to every node."
  type        = set(string)
}

variable "root_volume_size_gib" {
  description = "Instance-owned OS volume capacity."
  type        = number
}

variable "data_volume_size_gib" {
  description = "Independent persistent volume capacity per node."
  type        = number
}

variable "location" {
  description = "Single Verda failure domain for instances and volumes."
  type        = string
}

variable "startup_script_id" {
  description = "Optional startup script; null preserves the Ansible boundary."
  type        = string
  default     = null
  nullable    = true
}

variable "preserve_data_volumes" {
  description = <<-EOT
    Explicit Stage A durability contract. Terraform lifecycle rules are literal,
    so Phase 2 accepts true only; data deletion requires a reviewed source change.
  EOT
  type        = bool
  default     = true

  validation {
    condition     = var.preserve_data_volumes
    error_message = "Phase 2 requires preserve_data_volumes=true."
  }
}
