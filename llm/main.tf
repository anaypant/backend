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
  source                            = "./functions"
  project_id                        = var.project_id
  region                            = var.region
  backend_service_account_email     = var.platform_sa_email
  secrets_internal_gateway_hostname = var.secrets_internal_gateway_hostname
  secrets_internal_jwt_audience     = var.secrets_internal_jwt_audience
  openrouter_api_key                = var.openrouter_api_key
}

module "api" {
  source = "./api"
  providers = {
    google      = google
    google-beta = google-beta
  }
  project_id                    = var.project_id
  region                        = var.region
  llm_complete_function         = module.functions.llm_complete_function
  backend_service_account_email = var.platform_sa_email
  depends_on                    = [module.functions]
}

output "llm_gateway_hostname" {
  description = "Internal LLM API Gateway hostname (no scheme)."
  value       = module.api.gateway_hostname
}

output "llm_function_url" {
  description = "LLM Cloud Function URL; use as OIDC audience for callers."
  value       = module.functions.llm_complete_function.url
}
