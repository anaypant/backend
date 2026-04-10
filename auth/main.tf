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
  source                        = "./functions"
  project_id                    = var.project_id
  region                        = var.region
  firebase_web_api_key          = var.firebase_web_api_key
  db_internal_gateway_hostname  = var.db_internal_gateway_hostname
  backend_service_account_email = var.platform_sa_email
}

module "api" {
  source = "./api"
  providers = {
    google      = google
    google-beta = google-beta
  }
  project_id                    = var.project_id
  region                        = var.region
  auth_functions                = module.functions.auth_functions
  backend_service_account_email = var.platform_sa_email
  depends_on                    = [module.functions]
}

output "id" {
  value = "auth"
}

output "auth_gateway_hostname" {
  description = "Internal Auth API Gateway hostname (no scheme)."
  value       = module.api.gateway_hostname
}
