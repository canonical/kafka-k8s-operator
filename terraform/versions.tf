terraform {
  required_version = ">= 0.14.0"

  required_providers {
    juju = {
      source  = "juju/juju"
      version = ">= 0.23.0"
    }
  }
}
