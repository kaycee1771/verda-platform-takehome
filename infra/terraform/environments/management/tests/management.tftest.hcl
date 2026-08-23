mock_provider "verda" {
  override_during = plan

  mock_resource "verda_ssh_key" {
    defaults = {
      id          = "mock-ssh-key-id"
      fingerprint = "SHA256:mock"
      created_at  = "2026-08-17T00:00:00Z"
    }
  }

  mock_resource "verda_volume" {
    defaults = {
      id          = "mock-volume-id"
      status      = "available"
      instance_id = null
      created_at  = "2026-08-17T00:00:00Z"
    }
  }

  mock_resource "verda_instance" {
    defaults = {
      id             = "mock-instance-id"
      ip             = "203.0.113.10"
      status         = "running"
      created_at     = "2026-08-17T00:00:00Z"
      os_name        = "Ubuntu 24.04"
      os_volume_id   = "mock-os-volume-id"
      price_per_hour = 0.0279
    }
  }
}

variables {
  ssh_public_key_path = "tests/fixtures/phase2.pub"
}

run "management_stage_a_contract" {
  command = plan

  assert {
    condition     = length(output.node_names) == 3
    error_message = "Stage A must plan exactly three management nodes."
  }

  assert {
    condition = output.node_names == tolist([
      "verda-mgmt-server-01",
      "verda-mgmt-server-02",
      "verda-mgmt-server-03",
    ])
    error_message = "Management node names are not deterministic."
  }

  assert {
    condition = output.data_volume_names == tolist([
      "verda-mgmt-data-01",
      "verda-mgmt-data-02",
      "verda-mgmt-data-03",
    ])
    error_message = "Management data-volume names are not deterministic."
  }

  assert {
    condition     = output.infrastructure_summary.location == "FIN-03"
    error_message = "The management root must retain FIN-03."
  }

  assert {
    condition = output.infrastructure_summary.node_lifecycle == {
      "01" = { instance_type = "CPU.4V.16G", resource_expiry_utc = "2026-08-24T21:00:00Z" }
      "02" = { instance_type = "CPU.4V.16G", resource_expiry_utc = "2026-08-24T21:00:00Z" }
      "03" = { instance_type = "CPU.8V.32G", resource_expiry_utc = "2026-08-27T21:00:00Z" }
    }
    error_message = "The reviewed Phase 6 node lifecycle map must retain the exact per-node shape and expiry."
  }

  assert {
    condition     = output.infrastructure_summary.os_image_id == "77edfb23-bb0d-41cc-a191-dccae45d96fd"
    error_message = "The immutable reviewed image configuration ID must remain pinned."
  }

  assert {
    condition     = output.infrastructure_summary.provider_image_value == "ubuntu-24.04"
    error_message = "The provider readback workaround must remain explicit."
  }

  assert {
    condition     = output.infrastructure_summary.preserve_data_volumes
    error_message = "Persistent data-volume preservation must remain enabled."
  }

  assert {
    condition     = length(output.ansible_inventory.all.children.management_servers.hosts) == 3
    error_message = "Machine-readable inventory must expose all three nodes."
  }
}
