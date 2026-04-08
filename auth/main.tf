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

# Identity Platform is enabled via identitytoolkit.googleapis.com in gcp_apis.tf.
# Do not manage google_identity_platform_* here: creating them fails when Firebase/IdP
# was already turned on (400/409). Configure Google sign-in in Firebase Console; optional
# google_oauth_* root variables remain for documentation or external tooling.

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
