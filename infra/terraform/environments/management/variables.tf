variable "ssh_public_key_path" {
  description = "Absolute path to the dedicated Phase 2 OpenSSH public key."
  type        = string

  validation {
    condition     = fileexists(var.ssh_public_key_path)
    error_message = "ssh_public_key_path must identify a readable public-key file outside Git."
  }
}

variable "location" {
  description = "Verified Verda location. A change requires a reviewed discovery update."
  type        = string
  default     = "FIN-03"

  validation {
    condition     = var.location == "FIN-03"
    error_message = "Phase 0 selected FIN-03; change the reviewed architecture before changing location."
  }
}

variable "instance_type" {
  description = "Verified Verda CPU flavor."
  type        = string
  default     = "CPU.4V.16G"

  validation {
    condition     = var.instance_type == "CPU.4V.16G"
    error_message = "Phase 0 selected CPU.4V.16G; a different flavor requires a reviewed decision."
  }
}

variable "os_image_id" {
  description = "Pinned Ubuntu 24.04 Minimal configuration identifier."
  type        = string
  default     = "77edfb23-bb0d-41cc-a191-dccae45d96fd"

  validation {
    condition     = var.os_image_id == "77edfb23-bb0d-41cc-a191-dccae45d96fd"
    error_message = "The reviewed Ubuntu 24.04 Minimal image ID must remain pinned."
  }
}

variable "provider_image_value" {
  description = <<-EOT
    Provider 1.1.2 readback-stable image_type. Live preflight proves it maps to
    the pinned immutable os_image_id before every plan and apply.
  EOT
  type        = string
  default     = "ubuntu-24.04"

  validation {
    condition     = var.provider_image_value == "ubuntu-24.04"
    error_message = "The documented provider workaround permits only ubuntu-24.04."
  }
}

variable "root_volume_size_gib" {
  description = "Instance-owned OS volume capacity."
  type        = number
  default     = 80

  validation {
    condition     = var.root_volume_size_gib == 80
    error_message = "The reviewed Stage A root volume size is exactly 80 GiB."
  }
}

variable "data_volume_size_gib" {
  description = "Independent persistent volume capacity per node."
  type        = number
  default     = 100

  validation {
    condition     = var.data_volume_size_gib == 100
    error_message = "The reviewed Stage A data volume size is exactly 100 GiB."
  }
}

variable "preserve_data_volumes" {
  description = "Explicit Phase 2 durable-volume preservation contract."
  type        = bool
  default     = true

  validation {
    condition     = var.preserve_data_volumes
    error_message = "Phase 2 requires preserve_data_volumes=true."
  }
}

variable "resource_expiry_utc" {
  description = "Seven-day Stage A expiry recorded in instance descriptions and the cost ledger."
  type        = string
  default     = "2026-08-24T21:00:00Z"

  validation {
    condition     = can(formatdate("YYYY-MM-DD'T'hh:mm:ssZ", var.resource_expiry_utc))
    error_message = "resource_expiry_utc must be RFC3339."
  }
}
