module "data_volume" {
  source   = "../verda-volume"
  for_each = var.nodes

  name                = "${var.cluster}-data-${each.key}"
  size_gib            = var.data_volume_size_gib
  location            = var.location
  volume_type         = "NVMe"
  deletion_protection = var.preserve_data_volumes ? "prevent_destroy" : "unsupported"
}

module "node" {
  source   = "../verda-instance"
  for_each = var.nodes

  name                 = "${var.cluster}-server-${each.key}"
  cluster              = var.cluster
  role                 = each.value.role
  instance_type        = var.instance_type
  provider_image_value = var.provider_image_value
  ssh_key_ids          = var.ssh_key_ids
  root_volume_size_gib = var.root_volume_size_gib
  root_volume_name     = "${var.cluster}-os-${each.key}"
  data_volume_ids      = [module.data_volume[each.key].id]
  location             = var.location
  startup_script_id    = var.startup_script_id
  resource_expiry_utc  = var.resource_expiry_utc
}
