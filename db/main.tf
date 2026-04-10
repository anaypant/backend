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

locals {
  firestore_collections = [
    "Realtors",
    "People",
    "Internals",
    "Organizations",
  ]
}

module "functions" {
  source                        = "./functions"
  project_id                    = var.project_id
  region                        = var.region
  backend_service_account_email = var.platform_sa_email
  db_internal_gateway_hostname  = var.db_internal_gateway_hostname
}

module "api" {
  source = "./api"
  providers = {
    google      = google
    google-beta = google-beta
  }
  project_id                    = var.project_id
  region                        = var.region
  db_functions                  = module.functions.db_functions
  backend_service_account_email = var.platform_sa_email
  depends_on                    = [module.functions]
}

# When set, must match the deployed gateway hostname (platform OIDC audience on db-read/db-upsert).
check "db_internal_gateway_hostname_matches_deployed" {
  assert {
    condition = (
      var.db_internal_gateway_hostname == "" ||
      lower(trim(var.db_internal_gateway_hostname, "/")) == lower(trim(module.api.gateway_hostname, "/"))
    )
    error_message = <<-EOT
      db_internal_gateway_hostname must equal the deployed internal DB gateway hostname (no scheme).
      Run: terraform output db_gateway_hostname
      Set the root variable to that exact value, or leave empty until you are ready to wire platform DB auth.
      Deployed gateway hostname: ${module.api.gateway_hostname}
    EOT
  }
}

resource "google_firestore_database" "default" {
  name        = "(default)"
  location_id = "us-central1"
  type        = "FIRESTORE_NATIVE"
}

output "id" {
  value = "db"
}

output "db_gateway_hostname" {
  description = "Internal DB API Gateway hostname (no scheme)."
  value       = module.api.gateway_hostname
}

output "db_gateway_audience" {
  description = "OIDC audience for platform calls to the internal DB gateway (https:// + db_gateway_hostname)."
  value       = module.api.gateway_audience
}

output "db_gateway_id" {
  description = "Fixed API Gateway id (hostname prefix acs-db-internal-...)."
  value       = module.api.gateway_id
}
