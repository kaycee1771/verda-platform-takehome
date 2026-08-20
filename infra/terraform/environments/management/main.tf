locals {
  nodes = {
    "01" = {
      role                = "server"
      instance_type       = "CPU.4V.16G"
      resource_expiry_utc = "2026-08-24T21:00:00Z"
    }
    "02" = {
      role                = "server"
      instance_type       = "CPU.4V.16G"
      resource_expiry_utc = "2026-08-24T21:00:00Z"
    }
    "03" = {
      role                = "server"
      instance_type       = "CPU.4V.16G"
      resource_expiry_utc = "2026-08-24T21:00:00Z"
    }
  }
}

check "management_node_lifecycle" {
  assert {
    condition = (
      keys(local.nodes) == ["01", "02", "03"] &&
      alltrue([
        for node in values(local.nodes) :
        contains(["CPU.4V.16G", "CPU.8V.32G"], node.instance_type) &&
        can(formatdate("YYYY-MM-DD'T'hh:mm:ssZ", node.resource_expiry_utc))
      ])
    )
    error_message = "Management lifecycle must contain exactly nodes 01-03 with a reviewed CPU shape and RFC3339 expiry."
  }
}

resource "verda_ssh_key" "management" {
  name       = "verda-mgmt-phase2"
  public_key = trimspace(file(var.ssh_public_key_path))
}

module "management" {
  source = "../../modules/verda-cluster"

  cluster               = "verda-mgmt"
  nodes                 = local.nodes
  provider_image_value  = var.provider_image_value
  ssh_key_ids           = [verda_ssh_key.management.id]
  root_volume_size_gib  = var.root_volume_size_gib
  data_volume_size_gib  = var.data_volume_size_gib
  location              = var.location
  startup_script_id     = null
  preserve_data_volumes = var.preserve_data_volumes
}
