terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 5.0"
    }
  }
}

module "functions" {
  source                         = "./functions"
  project_id                     = var.project_id
  region                         = var.region
  backend_service_account_email  = var.platform_sa_email
}

module "api" {
  source = "./api"
  providers = {
    google      = google
    google-beta = google-beta
  }
  project_id                    = var.project_id
  region                        = var.region
  core_run_function             = module.functions.core_run_function
  backend_service_account_email = var.platform_sa_email
  depends_on                    = [module.functions]
}

output "core_gateway_hostname" {
  description = "Internal Core API Gateway hostname (no scheme)."
  value       = module.api.gateway_hostname
}
