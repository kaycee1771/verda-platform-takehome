terraform {
  required_version = ">= 1.5.0, < 2.0.0"

  required_providers {
    verda = {
      source  = "verda-cloud/verda"
      version = "= 1.1.2"
    }
  }
}

provider "verda" {}
