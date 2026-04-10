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
  source                          = "./functions"
  project_id                      = var.project_id
  region                          = var.region
  backend_service_account_email   = var.platform_sa_email
  db_internal_gateway_hostname    = var.db_internal_gateway_hostname
  core_internal_gateway_hostname  = var.core_internal_gateway_hostname
  fub_oauth_authorize_url         = var.fub_oauth_authorize_url
  fub_oauth_token_url             = var.fub_oauth_token_url
  fub_oauth_client_id             = var.fub_oauth_client_id
  fub_oauth_client_secret         = var.fub_oauth_client_secret
  fub_system_name                 = var.fub_system_name
  fub_x_system_key                = var.fub_x_system_key
  acs_public_integration_base_url = var.acs_public_integration_base_url
  acs_oauth_state_secret          = var.acs_oauth_state_secret
}

module "api" {
  source = "./api"
  providers = {
    google      = google
    google-beta = google-beta
  }
  project_id                    = var.project_id
  region                        = var.region
  bridge_function               = module.functions.bridge_function
  backend_service_account_email = var.platform_sa_email
  depends_on                    = [module.functions]
}

output "integration_gateway_hostname" {
  description = "Internal Integration API Gateway hostname (no scheme)."
  value       = module.api.gateway_hostname
}
