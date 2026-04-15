# Internal Events API — POST /events/v1/publish → events-bridge (domain events to Pub/Sub).

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
  gateway_id = "acs-events-internal"

  health_path = {
    "/health" = {
      get = {
        summary     = "Placeholder health"
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

  events_backend = {
    address          = trimsuffix(var.events_bridge_function.url, "/")
    path_translation = "APPEND_PATH_TO_ADDRESS"
    protocol         = "h2"
    jwt_audience     = trimsuffix(var.events_bridge_function.url, "/")
  }

  events_paths = {
    "/events/v1/publish" = {
      post = {
        summary            = "Publish a domain event (CloudEvents-like envelope to Pub/Sub)"
        operationId        = "events_publish"
        consumes           = ["application/json"]
        produces           = ["application/json"]
        security           = []
        "x-google-backend" = local.events_backend
        responses = {
          "200" = { description = "OK" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
          "503" = { description = "Unavailable" }
        }
      }
    }
  }

  openapi_struct = {
    swagger = "2.0"
    info = {
      title   = "acs-events-internal"
      version = "1.0.0"
    }
    schemes = ["https"]
    paths   = merge(local.health_path, local.events_paths)
  }

  openapi_yaml = yamlencode(local.openapi_struct)
  api_config_revision = sha256(jsonencode({
    spec       = local.openapi_struct
    backend_sa = var.backend_service_account_email
  }))
}

resource "google_api_gateway_api" "internal" {
  provider = google-beta
  api_id   = local.gateway_id
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
  gateway_id = local.gateway_id

  depends_on = [google_api_gateway_api_config.internal]

  lifecycle {
    postcondition {
      condition = (
        startswith(self.default_hostname, "${local.gateway_id}-") &&
        endswith(self.default_hostname, ".gateway.dev")
      )
      error_message = "API Gateway default_hostname must match expected pattern."
    }
  }
}

output "gateway_hostname" {
  value = google_api_gateway_gateway.internal.default_hostname
}

output "gateway_audience" {
  value = "https://${google_api_gateway_gateway.internal.default_hostname}"
}
