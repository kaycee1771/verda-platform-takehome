variable "name" {
  description = "Deterministic hostname and resource name."
  type        = string

  validation {
    condition     = can(regex("^verda-(mgmt|workload)-server-[0-9]{2}$", var.name))
    error_message = "Instance names must follow verda-<cluster>-server-NN."
  }
}

variable "cluster" {
  description = "Logical cluster identifier."
  type        = string

  validation {
    condition     = contains(["verda-mgmt", "verda-workload"], var.cluster)
    error_message = "Cluster must be verda-mgmt or verda-workload."
  }
}

variable "role" {
  description = "Future Ansible and Kubernetes node role."
  type        = string

  validation {
    condition     = contains(["server", "agent"], var.role)
    error_message = "Role must be server or agent."
  }
}

variable "instance_type" {
  description = "Exact Verda CPU instance type."
  type        = string
}

variable "provider_image_value" {
  description = <<-EOT
    Canonical API image_type required for stable provider 1.1.2 readback. The
    calling root must prove its mapping to the immutable image ID before plan.
  EOT
  type        = string

  validation {
    condition     = var.provider_image_value == "ubuntu-24.04"
    error_message = "The provider transport value must remain ubuntu-24.04."
  }
}

variable "ssh_key_ids" {
  description = "Registered Verda SSH key identifiers."
  type        = set(string)

  validation {
    condition     = length(var.ssh_key_ids) > 0
    error_message = "At least one registered SSH key is required."
  }
}

variable "root_volume_size_gib" {
  description = "Instance-owned OS volume capacity in GiB."
  type        = number

  validation {
    condition     = var.root_volume_size_gib >= 80 && floor(var.root_volume_size_gib) == var.root_volume_size_gib
    error_message = "The Stage A root volume must be an integer of at least 80 GiB."
  }
}

variable "root_volume_name" {
  description = "Deterministic instance-owned OS volume name."
  type        = string
}

variable "data_volume_ids" {
  description = "Independently managed standard NVMe volumes to attach at create time."
  type        = list(string)

  validation {
    condition     = length(var.data_volume_ids) == 1
    error_message = "Each Stage A node must attach exactly one persistent data volume."
  }
}

variable "location" {
  description = "Exact Verda location code."
  type        = string
}

variable "startup_script_id" {
  description = "Optional provider-managed startup script; null preserves the Ansible boundary."
  type        = string
  default     = null
  nullable    = true
}

variable "resource_expiry_utc" {
  description = "Operator-owned expiry recorded in the immutable instance description."
  type        = string

  validation {
    condition     = can(formatdate("YYYY-MM-DD'T'hh:mm:ssZ", var.resource_expiry_utc))
    error_message = "resource_expiry_utc must be an RFC3339 timestamp."
  }
}
