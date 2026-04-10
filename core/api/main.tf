# Internal Core API — POST /core/v1/run → core Cloud Function (same ESP / SA pattern as db/auth).

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
  health_path = {
    "/health" = {
      get = {
        summary     = "Placeholder health (not backed by core function)"
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

  core_paths = {
    "/core/v1/run" = {
      post = {
        summary     = "Run ACS workflow (stub)"
        operationId = "core_run"
        consumes    = ["application/json"]
        produces    = ["application/json"]
        security    = []
        "x-google-backend" = {
          address          = "${trimsuffix(var.core_run_function.url, "/")}/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
          jwt_audience     = trimsuffix(var.core_run_function.url, "/")
        }
        responses = {
          "200" = { description = "OK" }
          "400" = { description = "Bad request" }
          "405" = { description = "Method not allowed" }
          "500" = { description = "Error" }
          "503" = { description = "Unavailable" }
        }
      }
    }
  }

  openapi_struct = {
    swagger = "2.0"
    info = {
      title   = "acs-core-internal"
      version = "1.0.0"
    }
    schemes = ["https"]
    paths   = merge(local.health_path, local.core_paths)
  }

  openapi_yaml = yamlencode(local.openapi_struct)
  api_config_revision = sha256(jsonencode({
    spec       = local.openapi_struct
    backend_sa = var.backend_service_account_email
  }))
}

resource "google_api_gateway_api" "internal" {
  provider = google-beta
  api_id   = "acs-core-internal"
}

resource "google_api_gateway_api_config" "internal" {
  provider      = google-beta
  api           = google_api_gateway_api.internal.api_id
  api_config_id = "cfg${substr(local.api_config_revision, 0, 32)}"

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

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_api_gateway_gateway" "internal" {
  provider   = google-beta
  region     = var.region
  api_config = google_api_gateway_api_config.internal.id
  gateway_id = "acs-core-internal"

  depends_on = [google_api_gateway_api_config.internal]
}

output "gateway_hostname" {
  description = "POST https://<host>/core/v1/run — internal only."
  value       = google_api_gateway_gateway.internal.default_hostname
}
