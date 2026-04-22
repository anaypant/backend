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

  # --- Stack dependency DAG (root = operator / HCP inputs; everything else flows via module outputs) ---
  # L0: GCP project APIs + platform SA (google_project_service, google_service_account.platform).
  # L1: Data plane — module.db (Firestore rules, internal DB gateway hostname output).
  # L2: Security + sidecars — module.secrets, module.auth, module.events (each consume L1 hostnames/outputs as wired below).
  # L3: LLM edge — module.llm (secrets hostname + JWT audience from secrets module).
  # L4: Core API — module.core (db + secrets + llm outputs only; no dependency on module.integration).
  # L5: Integration — module.integration (db + core gateway + events + secrets; publishes integration_bridge_function_url).
  #
  # Cross-cutting URLs: set only at root when Terraform cannot infer without a cycle.
  # Example: fub_webhook_sync_worker_url should equal terraform output integration_bridge_function_url
  # for Cloud Tasks + optional core-run INTEGRATION_BRIDGE_BASE_URL (core workflows that call integration).
  # FUB webhook person hydration is done in integration before POST /core/v1/run, so contact enrichment
  # does not require core to reach back into integration.

  # Accept hostname or full URL in tfvars/HCP; db + integration need hostname only (no cycle: no module.db ref).
  _db_gw_raw                              = trimspace(var.db_internal_gateway_hostname)
  _db_gw_after_https                      = local._db_gw_raw != "" && startswith(lower(local._db_gw_raw), "https://") ? trimspace(trim(substr(local._db_gw_raw, 8, length(local._db_gw_raw) - 8), "/")) : local._db_gw_raw
  _db_gw_after_http                       = local._db_gw_after_https != "" && startswith(lower(local._db_gw_after_https), "http://") ? trimspace(trim(substr(local._db_gw_after_https, 7, length(local._db_gw_after_https) - 7), "/")) : local._db_gw_after_https
  _db_gw_host_only                        = local._db_gw_after_http != "" ? split("/", local._db_gw_after_http)[0] : ""
  db_internal_gateway_hostname_normalized = local._db_gw_raw == "" ? "" : local._db_gw_host_only

  _ev_gw_raw         = trimspace(var.events_internal_gateway_hostname)
  _ev_gw_after_https = local._ev_gw_raw != "" && startswith(lower(local._ev_gw_raw), "https://") ? trimspace(trim(substr(local._ev_gw_raw, 8, length(local._ev_gw_raw) - 8), "/")) : local._ev_gw_raw
  _ev_gw_after_http  = local._ev_gw_after_https != "" && startswith(lower(local._ev_gw_after_https), "http://") ? trimspace(trim(substr(local._ev_gw_after_https, 7, length(local._ev_gw_after_https) - 7), "/")) : local._ev_gw_after_https
  _ev_gw_host_only   = local._ev_gw_after_http != "" ? split("/", local._ev_gw_after_http)[0] : ""
  events_internal_gateway_hostname_normalized = local._ev_gw_raw == "" ? "" : local._ev_gw_host_only

  # OIDC audience for calling secrets via the internal gateway must be the secrets-bridge function URL.
  _secrets_bridge_invoker_audience = nonsensitive(module.secrets.secrets_bridge_invoker_audience)
  secrets_internal_jwt_audience_effective = (
    trimspace(var.secrets_internal_jwt_audience_override) != ""
    ? trimspace(var.secrets_internal_jwt_audience_override)
    : local._secrets_bridge_invoker_audience
  )
  secrets_jwt_aud_norm_effective = lower(trimspace(trimsuffix(local.secrets_internal_jwt_audience_effective, "/")))
  secrets_jwt_aud_norm_bridge    = lower(trimspace(trimsuffix(local._secrets_bridge_invoker_audience, "/")))
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

module "events" {
  source                              = "./events"
  project_id                          = local.project_id
  region                              = var.region
  platform_sa_email                   = google_service_account.platform.email
  events_internal_gateway_hostname    = local.events_internal_gateway_hostname_normalized
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

module "llm" {
  source                            = "./llm"
  project_id                        = local.project_id
  region                            = var.region
  platform_sa_email                 = google_service_account.platform.email
  secrets_internal_gateway_hostname = nonsensitive(module.secrets.secrets_gateway_hostname)
  secrets_internal_jwt_audience     = local.secrets_internal_jwt_audience_effective
  openrouter_api_key                = var.openrouter_api_key
  providers = {
    google      = google
    google-beta = google-beta
  }
  depends_on = [google_project_service.gcp, google_service_account.platform, module.secrets]
}

module "core" {
  source                              = "./core"
  project_id                          = local.project_id
  region                              = var.region
  platform_sa_email                   = google_service_account.platform.email
  db_internal_gateway_hostname        = local.db_internal_gateway_hostname_normalized != "" ? local.db_internal_gateway_hostname_normalized : module.db.db_gateway_hostname
  llm_internal_gateway_hostname       = module.llm.llm_gateway_hostname
  llm_internal_jwt_audience           = module.llm.llm_function_url
  secrets_internal_gateway_hostname   = nonsensitive(module.secrets.secrets_gateway_hostname)
  secrets_internal_jwt_audience       = local.secrets_internal_jwt_audience_effective
  fub_webhook_sync_worker_url         = var.fub_webhook_sync_worker_url
  enable_core_dev_lab                 = var.enable_core_dev_lab
  providers = {
    google      = google
    google-beta = google-beta
  }
  depends_on = [
    google_project_service.gcp,
    google_service_account.platform,
    module.db,
    module.secrets,
    module.llm,
  ]
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
  acs_callback_bridge_secret             = var.acs_callback_bridge_secret
  integration_oauth_browser_cors_origins = var.integration_oauth_browser_cors_origins
  fub_webhook_sync_worker_url            = var.fub_webhook_sync_worker_url
  events_internal_gateway_hostname       = module.events.events_gateway_hostname
  # Nonsensitive: hostname is not secret; avoids Google provider "inconsistent sensitive" on
  # integration function env when this value is (known after apply) on first full stack apply.
  secrets_internal_gateway_hostname = nonsensitive(module.secrets.secrets_gateway_hostname)
  secrets_internal_jwt_audience     = local.secrets_internal_jwt_audience_effective
  providers = {
    google      = google
    google-beta = google-beta
  }
  depends_on = [google_project_service.gcp, module.db, module.core, module.events, module.secrets, google_service_account.platform]
}

output "integration_bridge_function_url" {
  description = "integration-bridge Cloud Function URL; set terraform variable fub_webhook_sync_worker_url to this (no trailing slash) to enable deferred FUB webhook sync."
  value       = module.integration.integration_bridge_function_url
}

output "events_gateway_hostname" {
  description = "Internal domain-events API Gateway hostname (no scheme); set events_internal_gateway_hostname to this."
  value       = module.events.events_gateway_hostname
}

output "llm_gateway_hostname" {
  description = "Internal LLM API Gateway hostname (no scheme); set on callers that invoke POST /llm/v1/complete."
  value       = module.llm.llm_gateway_hostname
}

output "llm_function_url" {
  description = "llm-complete Cloud Function URL (OIDC audience for LLM internal API)."
  value       = module.llm.llm_function_url
}

check "events_internal_gateway_hostname_matches_deployed" {
  assert {
    condition = (
      local.events_internal_gateway_hostname_normalized == "" ||
      lower(trim(local.events_internal_gateway_hostname_normalized, "/")) == lower(trim(module.events.events_gateway_hostname, "/"))
    )
    error_message = "events_internal_gateway_hostname must match module.events.events_gateway_hostname (terraform output events_gateway_hostname). Deployed: ${module.events.events_gateway_hostname}"
  }
}

check "secrets_internal_jwt_audience_matches_secrets_bridge" {
  assert {
    condition = local.secrets_jwt_aud_norm_effective == local.secrets_jwt_aud_norm_bridge
    error_message = join(" ", [
      "SECRETS_INTERNAL_JWT_AUDIENCE must match the deployed secrets-bridge Cloud Function URL.",
      "Use: terraform output -raw secrets_bridge_invoker_audience",
      "or clear secrets_internal_jwt_audience_override so Terraform uses that output.",
      "Compare (normalized):",
      "effective=${local.secrets_jwt_aud_norm_effective}",
      "bridge=${local.secrets_jwt_aud_norm_bridge}",
    ])
  }
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
  acs_callback_bridge_secret            = var.acs_callback_bridge_secret
  acs_oauth_state_secret                = var.acs_oauth_state_secret
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
