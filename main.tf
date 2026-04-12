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

  # Accept hostname or full URL in tfvars/HCP; db + integration need hostname only (no cycle: no module.db ref).
  _db_gw_raw                              = trimspace(var.db_internal_gateway_hostname)
  _db_gw_after_https                      = local._db_gw_raw != "" && startswith(lower(local._db_gw_raw), "https://") ? trimspace(trim(substr(local._db_gw_raw, 8, length(local._db_gw_raw) - 8), "/")) : local._db_gw_raw
  _db_gw_after_http                       = local._db_gw_after_https != "" && startswith(lower(local._db_gw_after_https), "http://") ? trimspace(trim(substr(local._db_gw_after_https, 7, length(local._db_gw_after_https) - 7), "/")) : local._db_gw_after_https
  _db_gw_host_only                        = local._db_gw_after_http != "" ? split("/", local._db_gw_after_http)[0] : ""
  db_internal_gateway_hostname_normalized = local._db_gw_raw == "" ? "" : local._db_gw_host_only
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
  source                       = "./db"
  project_id                   = local.project_id
  region                       = var.region
  platform_sa_email            = google_service_account.platform.email
  db_internal_gateway_hostname = local.db_internal_gateway_hostname_normalized
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

module "secrets" {
  source                              = "./secrets"
  project_id                          = local.project_id
  region                              = var.region
  platform_sa_email                   = google_service_account.platform.email
  secrets_internal_gateway_hostname   = var.secrets_internal_gateway_hostname
  providers = {
    google      = google
    google-beta = google-beta
  }
  depends_on = [google_project_service.gcp, google_service_account.platform]
}

module "integration" {
  source                                 = "./integration"
  project_id                             = local.project_id
  region                                 = var.region
  platform_sa_email                      = google_service_account.platform.email
  db_internal_gateway_hostname           = local.db_internal_gateway_hostname_normalized != "" ? local.db_internal_gateway_hostname_normalized : module.db.db_gateway_hostname
  core_internal_gateway_hostname         = module.core.core_gateway_hostname
  fub_oauth_authorize_url                = var.fub_oauth_authorize_url
  fub_oauth_token_url                    = var.fub_oauth_token_url
  fub_oauth_client_id                    = var.fub_oauth_client_id
  fub_oauth_client_secret                = var.fub_oauth_client_secret
  fub_system_name                        = var.fub_system_name
  fub_x_system_key                       = var.fub_x_system_key
  acs_public_integration_base_url        = var.acs_public_integration_base_url
  acs_oauth_state_secret                 = var.acs_oauth_state_secret
  integration_oauth_browser_cors_origins = var.integration_oauth_browser_cors_origins
  # Nonsensitive: hostname is not secret; avoids Google provider "inconsistent sensitive" on
  # integration function env when this value is (known after apply) on first full stack apply.
  secrets_internal_gateway_hostname = nonsensitive(module.secrets.secrets_gateway_hostname)
  providers = {
    google      = google
    google-beta = google-beta
  }
  depends_on = [google_project_service.gcp, module.db, module.core, module.secrets, google_service_account.platform]
}

module "api" {
  source                                = "./api"
  project_id                            = local.project_id
  region                                = var.region
  db_internal_gateway_hostname          = module.db.db_gateway_hostname
  auth_internal_gateway_hostname        = module.auth.auth_gateway_hostname
  integration_internal_gateway_hostname = module.integration.integration_gateway_hostname
  platform_service_account_email        = google_service_account.platform.email
  acs_public_integration_base_url       = var.acs_public_integration_base_url
  providers = {
    google      = google
    google-beta = google-beta
  }
  depends_on = [
    google_project_service.gcp,
    module.db,
    module.auth,
    module.integration,
    module.secrets,
    google_service_account.platform
  ]
}
