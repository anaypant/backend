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

# Functionality
module "core" { source = "./core" }


# Database (depends on APIs in gcp_apis.tf)
module "db" {
  source     = "./db"
  project_id = local.project_id
  region     = var.region
  providers = {
    google      = google
    google-beta = google-beta
  }
  depends_on = [google_project_service.gcp]
}


module "auth" {
  source                         = "./auth"
  project_id                     = local.project_id
  region                         = var.region
  firebase_web_api_key           = var.firebase_web_api_key
  google_oauth_client_id         = var.google_oauth_client_id
  google_oauth_client_secret     = var.google_oauth_client_secret
  db_internal_gateway_hostname   = module.db.db_gateway_hostname
  providers = {
    google      = google
    google-beta = google-beta
  }
  depends_on = [google_project_service.gcp, module.db]
}

module "api" {
  source                        = "./api"
  project_id                    = local.project_id
  region                        = var.region
  db_internal_gateway_hostname  = module.db.db_gateway_hostname
  auth_internal_gateway_hostname = module.auth.auth_gateway_hostname
  providers = {
    google      = google
    google-beta = google-beta
  }
  depends_on = [google_project_service.gcp, module.db, module.auth]
}

module "integrations" { source = "./integrations" }

