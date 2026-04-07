# Internal DB API — Google API Gateway in front of db read / upsert / delete / query Cloud Functions (Gen2 / Cloud Run).
# Backend SA is created in the parent db module; this module only binds API Gateway–specific IAM and gateway_config.

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

resource "google_service_account_iam_member" "apigateway_impersonate_backend" {
  service_account_id = var.backend_service_account_name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.apigateway_mgmt_sa
}

locals {
  health_path = {
    "/health" = {
      get = {
        summary     = "Placeholder health (not backed by db functions)"
        operationId = "health"
        produces    = ["application/json"]
        security    = []
        "x-google-backend" = {
          address          = "https://www.googleapis.com/discovery/v1/apis"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
        }
        responses = {
          "200" = { description = "OK" }
        }
      }
    }
  }

  db_paths = {
    for key, fn in var.db_functions : "/db/${key}" => {
      post = {
        summary     = "DB ${key} (proxied to Cloud Function)"
        operationId = "db_${key}"
        consumes    = ["application/json"]
        produces    = ["application/json"]
        security    = []
        "x-google-backend" = {
          # CONSTANT_ADDRESS sends all traffic to the function root (body and method preserved).
          address          = "${trimsuffix(fn.url, "/")}/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
        }
        responses = {
          "200" = { description = "OK" }
          "204" = { description = "No content" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
          "404" = { description = "Not found" }
          "500" = { description = "Error" }
          "503" = { description = "Unavailable" }
        }
      }
    }
  }

  openapi_struct = {
    swagger = "2.0"
    info = {
      title   = "acs-db-internal"
      version = "1.0.0"
    }
    schemes = ["https"]
    paths   = merge(local.health_path, local.db_paths)
  }

  openapi_yaml = yamlencode(local.openapi_struct)
}

resource "google_api_gateway_api" "internal" {
  provider = google-beta
  api_id   = "acs-db-internal"
}

resource "google_api_gateway_api_config" "internal" {
  provider = google-beta
  api      = google_api_gateway_api.internal.api_id
  # Immutable config revisions; hash ties this revision to the OpenAPI + function URLs.
  api_config_id = "cfg${substr(md5(local.openapi_yaml), 0, 14)}"

  openapi_documents {
    document {
      path     = "openapi.yaml"
      contents = base64encode(local.openapi_yaml)
    }
  }

  gateway_config {
    backend_config {
      google_service_account = var.backend_service_account_email
    }
  }

  depends_on = [google_service_account_iam_member.apigateway_impersonate_backend]

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_api_gateway_gateway" "internal" {
  provider   = google-beta
  region     = var.region
  api_config = google_api_gateway_api_config.internal.id
  gateway_id = "acs-db-internal"

  depends_on = [google_api_gateway_api_config.internal]
}

output "gateway_hostname" {
  description = "POST https://<hostname>/db/read|upsert|delete|query — same JSON bodies as calling each function URL."
  value       = google_api_gateway_gateway.internal.default_hostname
}
