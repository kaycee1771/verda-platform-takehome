variable "name" {
  description = "Deterministic Verda volume name."
  type        = string

  validation {
    condition     = can(regex("^verda-[a-z0-9-]+-data-[0-9]{2}$", var.name))
    error_message = "Volume names must follow verda-<cluster>-data-NN."
  }
}

variable "size_gib" {
  description = "Provisioned volume capacity in GiB."
  type        = number

  validation {
    condition     = var.size_gib >= 50 && floor(var.size_gib) == var.size_gib
    error_message = "Data volume capacity must be an integer of at least 50 GiB."
  }
}

variable "location" {
  description = "Verda location code; it must match the consuming instance."
  type        = string

  validation {
    condition     = can(regex("^[A-Z]{3}-[0-9]{2}$", var.location))
    error_message = "Location must use a Verda code such as FIN-03."
  }
}

variable "volume_type" {
  description = "Provider-supported persistent block volume type."
  type        = string
  default     = "NVMe"

  validation {
    condition     = var.volume_type == "NVMe"
    error_message = "Provider 1.1.2 supports NVMe for this Stage A volume path."
  }
}

variable "deletion_protection" {
  description = <<-EOT
    Explicit lifecycle policy. Phase 2 permits only Terraform prevent_destroy;
    deleting data requires a reviewed source change and the guarded teardown path.
  EOT
  type        = string
  default     = "prevent_destroy"

  validation {
    condition     = var.deletion_protection == "prevent_destroy"
    error_message = "Stage A data volumes must use prevent_destroy."
  }
}
