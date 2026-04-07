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


module "auth" { source = "./auth" }
module "api" {
  source                       = "./api"
  project_id                   = local.project_id
  region                       = var.region
  db_internal_gateway_hostname = module.db.db_gateway_hostname
  providers = {
    google      = google
    google-beta = google-beta
  }
  depends_on = [google_project_service.gcp, module.db]
}
module "integrations" { source = "./integrations" }

output "stack" {
  value = {
    core         = module.core.id
    db           = module.db.id
    auth         = module.auth.id
    api          = module.api.id
    integrations = module.integrations.id
  }
}
