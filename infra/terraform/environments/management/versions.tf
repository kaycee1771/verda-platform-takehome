terraform {
  required_version = ">= 1.15.8, < 1.16.0"

  required_providers {
    verda = {
      source  = "verda-cloud/verda"
      version = "= 1.1.2"
    }
  }

  # The path is supplied during init and resolves outside the repository.
  # The local backend provides process-level locking, not multi-operator remote
  # locking; encrypted independent backup is handled by the Phase 2 wrapper.
  backend "local" {}
}

provider "verda" {}
