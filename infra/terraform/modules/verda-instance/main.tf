resource "verda_instance" "this" {
  instance_type = var.instance_type
  image         = var.provider_image_value
  hostname      = var.name
  description   = "${var.cluster} ${var.role}; owner=platform; expires=${var.resource_expiry_utc}"
  location      = var.location
  is_spot       = false

  ssh_key_ids       = var.ssh_key_ids
  startup_script_id = var.startup_script_id
  existing_volumes  = var.data_volume_ids

  os_volume = {
    name = var.root_volume_name
    size = var.root_volume_size_gib
    type = "NVMe"
  }
}
