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
  core_internal_gateway_hostname    = var.core_internal_gateway_hostname
  db_internal_gateway_hostname      = var.db_internal_gateway_hostname
  llm_internal_gateway_hostname     = var.llm_internal_gateway_hostname
  llm_internal_jwt_audience         = var.llm_internal_jwt_audience
  secrets_internal_gateway_hostname = var.secrets_internal_gateway_hostname
  secrets_internal_jwt_audience     = var.secrets_internal_jwt_audience
  fub_webhook_sync_worker_url       = var.fub_webhook_sync_worker_url
  enable_core_dev_lab               = var.enable_core_dev_lab
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
