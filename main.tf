terraform {
  required_version = ">= 1.5"
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

locals {
  project_id = {
    dev     = var.dev_project_id
    staging = var.staging_project_id
    prod    = var.prod_project_id
  }[var.environment]
}

provider "google" {
  project = local.project_id
  region  = var.region
}

provider "google-beta" {
  project = local.project_id
  region  = var.region
}

module "db" {
  source             = "./db"
  project_id         = local.project_id
  region             = var.region
  platform_sa_email = google_service_account.platform.email
  providers = {
    google      = google
    google-beta = google-beta
  }
  depends_on = [google_project_service.gcp, google_service_account.platform]
}

module "auth" {
  source                       = "./auth"
  project_id                   = local.project_id
  region                       = var.region
  firebase_web_api_key         = var.firebase_web_api_key
  google_oauth_client_id       = var.google_oauth_client_id
  google_oauth_client_secret   = var.google_oauth_client_secret
  db_internal_gateway_hostname = module.db.db_gateway_hostname
  platform_sa_email            = google_service_account.platform.email
  providers = {
    google      = google
    google-beta = google-beta
  }
  depends_on = [google_project_service.gcp, module.db, google_service_account.platform]
}

module "core" {
  source            = "./core"
  project_id        = local.project_id
  region            = var.region
  platform_sa_email = google_service_account.platform.email
  providers = {
    google      = google
    google-beta = google-beta
  }
  depends_on = [google_project_service.gcp, google_service_account.platform]
}

module "integration" {
  source                          = "./integration"
  project_id                      = local.project_id
  region                          = var.region
  platform_sa_email               = google_service_account.platform.email
  db_internal_gateway_hostname    = module.db.db_gateway_hostname
  core_internal_gateway_hostname  = module.core.core_gateway_hostname
  fub_oauth_authorize_url         = var.fub_oauth_authorize_url
  fub_oauth_token_url             = var.fub_oauth_token_url
  fub_oauth_client_id             = var.fub_oauth_client_id
  fub_oauth_client_secret         = var.fub_oauth_client_secret
  fub_system_name                 = var.fub_system_name
  fub_x_system_key                = var.fub_x_system_key
  acs_public_integration_base_url = var.acs_public_integration_base_url
  acs_oauth_state_secret          = var.acs_oauth_state_secret
  providers = {
    google      = google
    google-beta = google-beta
  }
  depends_on = [google_project_service.gcp, module.db, module.core, google_service_account.platform]
}

module "api" {
  source                               = "./api"
  project_id                           = local.project_id
  region                               = var.region
  db_internal_gateway_hostname         = module.db.db_gateway_hostname
  auth_internal_gateway_hostname       = module.auth.auth_gateway_hostname
  integration_internal_gateway_hostname = module.integration.integration_gateway_hostname
  platform_service_account_email       = google_service_account.platform.email
  acs_public_integration_base_url      = var.acs_public_integration_base_url
  providers = {
    google      = google
    google-beta = google-beta
  }
  depends_on = [
    google_project_service.gcp,
    module.db,
    module.auth,
    module.integration,
    google_service_account.platform
  ]
}
