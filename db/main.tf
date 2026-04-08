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
