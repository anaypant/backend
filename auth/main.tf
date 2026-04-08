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

# Identity Platform baseline (email/password is available once Identity Toolkit API is enabled).
resource "google_identity_platform_config" "default" {
  provider = google-beta
  project  = var.project_id
}

# Google provider (optional Terraform wiring). If client_id/secret are empty, enable Google in Firebase Console.
resource "google_identity_platform_default_supported_idp_config" "google" {
  count = (
    var.google_oauth_client_id != "" && var.google_oauth_client_secret != ""
  ) ? 1 : 0

  provider      = google-beta
  project       = var.project_id
  idp_id        = "google.com"
  enabled       = true
  client_id     = var.google_oauth_client_id
  client_secret = var.google_oauth_client_secret
}

module "functions" {
  source                         = "./functions"
  project_id                     = var.project_id
  region                         = var.region
  firebase_web_api_key           = var.firebase_web_api_key
  db_internal_gateway_hostname   = var.db_internal_gateway_hostname
  backend_service_account_email  = google_service_account.auth_backend.email

  depends_on = [
    google_project_iam_member.auth_backend_firebaseauth_admin,
  ]
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
  backend_service_account_email = google_service_account.auth_backend.email
  backend_service_account_name  = google_service_account.auth_backend.name

  depends_on = [module.functions]
}

output "id" {
  value = "auth"
}

output "auth_gateway_hostname" {
  description = "Internal Auth API Gateway hostname (no scheme). POST https://<host>/auth/..."
  value       = module.api.gateway_hostname
}
