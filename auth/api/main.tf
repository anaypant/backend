# Internal Auth API — Google API Gateway in front of auth Cloud Functions (Gen2 / Cloud Run).
# Platform SA + IAM (TokenCreator, run.invoker) are in root platform.tf.

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
  auth_route_paths = {
    realtor_signup  = "/auth/realtor/signup"
    realtor_login   = "/auth/realtor/login"
    internal_signup = "/auth/internal/signup"
    internal_login  = "/auth/internal/login"
  }

  health_path = {
    "/health" = {
      get = {
        summary     = "Placeholder health (not backed by auth functions)"
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

  auth_paths = {
    for key, fn in var.auth_functions : local.auth_route_paths[key] => {
      post = {
        summary     = "Auth ${key} (proxied to Cloud Function)"
        operationId = "auth_${key}"
        consumes    = ["application/json"]
        produces    = ["application/json"]
        security    = []
        "x-google-backend" = {
          address          = "${trimsuffix(fn.url, "/")}/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
          # Required for Gen2 (Cloud Run): token audience must match or Cloud Run returns 401.
          jwt_audience = trimsuffix(fn.url, "/")
        }
        responses = {
          "200" = { description = "OK" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
          "404" = { description = "Not found" }
          "409" = { description = "Conflict" }
          "500" = { description = "Error" }
          "503" = { description = "Unavailable" }
        }
      }
    }
  }

  openapi_struct = {
    swagger = "2.0"
    info = {
      title   = "acs-auth-internal"
      version = "1.0.0"
    }
    schemes = ["https"]
    paths   = merge(local.health_path, local.auth_paths)
  }

  openapi_yaml = yamlencode(local.openapi_struct)
  api_config_revision = sha256(jsonencode({
    spec       = local.openapi_struct
    backend_sa = var.backend_service_account_email
  }))
}

resource "google_api_gateway_api" "internal" {
  provider = google-beta
  api_id   = "acs-auth-internal"
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
  gateway_id = "acs-auth-internal"

  depends_on = [google_api_gateway_api_config.internal]
}

output "gateway_hostname" {
  description = "POST https://<hostname>/auth/realtor/signup|login, /auth/internal/signup|login — same JSON bodies as calling each function URL."
  value       = google_api_gateway_gateway.internal.default_hostname
}
