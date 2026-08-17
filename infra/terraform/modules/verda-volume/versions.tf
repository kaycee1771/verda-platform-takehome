terraform {
  required_version = ">= 1.15.8, < 1.16.0"

  required_providers {
    verda = {
      source  = "verda-cloud/verda"
      version = "= 1.1.2"
    }
  }
}
