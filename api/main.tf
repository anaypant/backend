# Client-facing API: managed API Gateway behind a global external HTTP(S) LB + Cloud Armor.

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

data "google_project" "project" {
  project_id = var.project_id
}

locals {
  apigateway_mgmt_sa = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-apigateway-mgmt.iam.gserviceaccount.com"
}

resource "google_service_account" "api_backend" {
  project      = var.project_id
  account_id   = "acs-api-backend"
  display_name = "ACS API backend (client-facing gateway)"
}

# Public API Gateway (ESP) uses google_service_account.api_backend in gateway_config.backend_config.
# The API Gateway management SA must impersonate that SA or backend calls (e.g. proxy to internal
# gateways) fail with 401 / permission errors.
resource "google_service_account_iam_member" "apigateway_impersonate_backend" {
  service_account_id = google_service_account.api_backend.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.apigateway_mgmt_sa
}

output "id" {
  value = "api"
}


