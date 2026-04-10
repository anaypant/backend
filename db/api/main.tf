# Internal DB API — Google API Gateway in front of db Cloud Functions (Gen2 / Cloud Run).
# ACS contract: POST /db/{read|upsert|delete|query} + JSON body; in-project callers must send
# the end-user Firebase ID in header acs_internal.USER_JWT_HEADER (Authorization is SA OIDC from ESP).

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
  # Stable API + gateway identifiers. default_hostname is then
  # "{gateway_id}-{service_uid}.{region_code}.gateway.dev" (service_uid assigned by GCP for this gateway).
  gateway_id = "acs-db-internal"

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
          address          = "${trimsuffix(fn.url, "/")}/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
          jwt_audience     = trimsuffix(fn.url, "/")
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
  # Deterministic id: spec + backend SA (gateway_config); avoids md5(yaml) drift and short-hash collisions.
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
      error_message = "API Gateway default_hostname must be {gateway_id}-*.*.gateway.dev so platform OIDC audience https://HOST stays predictable; verify GCP API Gateway behavior if this fails."
    }
  }
}

output "gateway_hostname" {
  description = "POST https://<hostname>/db/read|upsert|delete|query — same JSON bodies as calling each function URL."
  value       = google_api_gateway_gateway.internal.default_hostname
}

output "gateway_audience" {
  description = "Google ID token audience for calls to this gateway (https:// + gateway_hostname). Must match ACS_DB_GATEWAY_HOSTNAME-derived audience on db-read/db-upsert."
  value       = "https://${google_api_gateway_gateway.internal.default_hostname}"
}

output "gateway_id" {
  description = "Fixed gateway id; hostname always starts with this prefix."
  value       = local.gateway_id
}
