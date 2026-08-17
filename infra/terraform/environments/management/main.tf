locals {
  nodes = {
    "01" = {
      role = "server"
    }
    "02" = {
      role = "server"
    }
    "03" = {
      role = "server"
    }
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
  instance_type         = var.instance_type
  provider_image_value  = var.provider_image_value
  ssh_key_ids           = [verda_ssh_key.management.id]
  root_volume_size_gib  = var.root_volume_size_gib
  data_volume_size_gib  = var.data_volume_size_gib
  location              = var.location
  startup_script_id     = null
  preserve_data_volumes = var.preserve_data_volumes
  resource_expiry_utc   = var.resource_expiry_utc
}
