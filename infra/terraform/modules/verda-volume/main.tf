resource "verda_volume" "this" {
  name     = var.name
  size     = var.size_gib
  type     = var.volume_type
  location = var.location

  # Terraform lifecycle directives require literal values. Protection is
  # deliberately limited to durable data volumes, not compute or OS disks.
  lifecycle {
    prevent_destroy = true
  }
}
