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

# Default Firestore (Native). Collections below are documentation-only — Firestore
# creates a collection when the first document is written; Terraform has no resource
# for an empty collection.
locals {
  firestore_collections = [
    "Realtors",
    "People",        # Leads/Clients/Converted
    "Internals",     # Employees/Agents/Admin/etc.
    "Organizations", # Groups of Realtors

  ]
}

module "functions" {
  source                        = "./functions"
  project_id                    = var.project_id
  region                        = var.region
  backend_service_account_email = google_service_account.db_backend.email
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
  backend_service_account_email = google_service_account.db_backend.email
  backend_service_account_name  = google_service_account.db_backend.name
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
  description = "Internal DB API Gateway hostname (no scheme). POST https://<host>/db/read|upsert|delete|query."
  value       = module.api.gateway_hostname
}

