terraform {
  required_version = ">= 1.5"
}

variable "project_ids" {
  type        = map(string)
  description = "GCP project ID per environment name"

  validation {
    condition     = length(var.project_ids) > 0
    error_message = "project_ids must not be empty."
  }
}

variable "environment" {
  type        = string
  description = "The environment to deploy the stack to"

  validation {
    condition     = var.environment != "" && contains(keys(var.project_ids), var.environment)
    error_message = "environment must be non-empty and a key in project_ids."
  }
}

locals {
  project_id = var.project_ids[var.environment]
}

module "core" { source = "./core" }
module "db" { source = "./db" }
module "auth" { source = "./auth" }
module "api" { source = "./api" }
module "integrations" { source = "./integations" }

output "stack" {
  value = {
    environment  = var.environment
    project_id   = local.project_id
    core         = module.core.id
    db           = module.db.id
    auth         = module.auth.id
    api          = module.api.id
    integrations = module.integrations.id
  }
}
