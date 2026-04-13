# Internal Integration API — routes match public proxy paths (backend SA + ESP same as db/auth/core).

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
        summary     = "Placeholder health (not backed by integration function)"
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

  integration_backend = {
    address          = trimsuffix(var.bridge_function.url, "/")
    path_translation = "APPEND_PATH_TO_ADDRESS"
    protocol         = "h2"
    jwt_audience     = trimsuffix(var.bridge_function.url, "/")
  }

  integration_paths = {
    "/integrations/webhooks/followupboss" = {
      post = {
        summary            = "Integration webhooks/followupboss"
        operationId        = "integrations_webhooks_followupboss"
        consumes           = ["application/json"]
        produces           = ["application/json"]
        security           = []
        "x-google-backend" = local.integration_backend
        responses = {
          "200" = { description = "OK" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
          "404" = { description = "Not found" }
          "405" = { description = "Method not allowed" }
          "502" = { description = "Bad gateway" }
          "503" = { description = "Unavailable" }
        }
      }
    }
    "/integrations/followupboss/status" = {
      options = {
        summary            = "CORS preflight for connection status"
        operationId        = "integrations_followupboss_status_options"
        consumes           = ["text/plain"]
        produces           = ["text/plain"]
        security           = []
        "x-google-backend" = local.integration_backend
        responses = {
          "204" = { description = "No content" }
          "403" = { description = "Forbidden" }
        }
      }
      get = {
        summary            = "Integration followupboss/status (connection flags)"
        operationId        = "integrations_followupboss_status"
        produces           = ["application/json"]
        security           = []
        "x-google-backend" = local.integration_backend
        responses = {
          "200" = { description = "OK" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
          "404" = { description = "Not found" }
          "405" = { description = "Method not allowed" }
          "502" = { description = "Bad gateway" }
          "503" = { description = "Unavailable" }
        }
      }
    }
    "/integrations/followupboss/oauth/start" = {
      options = {
        summary            = "CORS preflight for oauth/start"
        operationId        = "integrations_followupboss_oauth_start_options"
        consumes           = ["text/plain"]
        produces           = ["text/plain"]
        security           = []
        "x-google-backend" = local.integration_backend
        responses = {
          "204" = { description = "No content" }
          "403" = { description = "Forbidden" }
        }
      }
      get = {
        summary            = "Integration followupboss/oauth/start"
        operationId        = "integrations_followupboss_oauth_start"
        produces           = ["application/json"]
        security           = []
        "x-google-backend" = local.integration_backend
        responses = {
          "200" = { description = "OK" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
          "404" = { description = "Not found" }
          "405" = { description = "Method not allowed" }
          "409" = { description = "Conflict (e.g. already connected)" }
          "501" = { description = "Not implemented" }
          "503" = { description = "Unavailable" }
        }
      }
    }
    "/integrations/followupboss/oauth/callback" = {
      get = {
        summary            = "Integration followupboss/oauth/callback"
        operationId        = "integrations_followupboss_oauth_callback"
        produces           = ["application/json"]
        security           = []
        "x-google-backend" = local.integration_backend
        responses = {
          "200" = { description = "OK" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "404" = { description = "Not found" }
          "405" = { description = "Method not allowed" }
          "503" = { description = "Unavailable" }
        }
      }
    }
    "/integrations/followupboss/refresh" = {
      post = {
        summary            = "Integration followupboss/refresh"
        operationId        = "integrations_followupboss_refresh"
        consumes           = ["application/json"]
        produces           = ["application/json"]
        security           = []
        "x-google-backend" = local.integration_backend
        responses = {
          "200" = { description = "OK" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
          "404" = { description = "Not found" }
          "405" = { description = "Method not allowed" }
          "502" = { description = "Bad gateway" }
          "503" = { description = "Unavailable" }
        }
      }
    }
    "/integrations/followupboss/resync_webhooks" = {
      post = {
        summary            = "Integration followupboss/resync_webhooks"
        operationId        = "integrations_followupboss_resync_webhooks"
        consumes           = ["application/json"]
        produces           = ["application/json"]
        security           = []
        "x-google-backend" = local.integration_backend
        responses = {
          "200" = { description = "OK" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
          "404" = { description = "Not found" }
          "405" = { description = "Method not allowed" }
          "502" = { description = "Bad gateway" }
          "503" = { description = "Unavailable" }
        }
      }
    }
    "/integrations/followupboss/webhooks" = {
      get = {
        summary            = "Integration followupboss/webhooks"
        operationId        = "integrations_followupboss_webhooks_list"
        produces           = ["application/json"]
        security           = []
        "x-google-backend" = local.integration_backend
        responses = {
          "200" = { description = "OK" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
          "404" = { description = "Not found" }
          "405" = { description = "Method not allowed" }
          "502" = { description = "Bad gateway" }
          "503" = { description = "Unavailable" }
        }
      }
    }
    "/integrations/followupboss/webhook_test" = {
      post = {
        summary            = "Integration followupboss/webhook_test"
        operationId        = "integrations_followupboss_webhook_test"
        consumes           = ["application/json"]
        produces           = ["application/json"]
        security           = []
        "x-google-backend" = local.integration_backend
        responses = {
          "200" = { description = "OK" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
          "404" = { description = "Not found" }
          "405" = { description = "Method not allowed" }
          "502" = { description = "Bad gateway" }
          "503" = { description = "Unavailable" }
        }
      }
    }
    "/integrations/followupboss/disconnect" = {
      post = {
        summary            = "Integration followupboss/disconnect"
        operationId        = "integrations_followupboss_disconnect"
        consumes           = ["application/json"]
        produces           = ["application/json"]
        security           = []
        "x-google-backend" = local.integration_backend
        responses = {
          "200" = { description = "OK" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
          "404" = { description = "Not found" }
          "405" = { description = "Method not allowed" }
          "502" = { description = "Bad gateway" }
          "503" = { description = "Unavailable" }
        }
      }
    }
  }

  openapi_struct = {
    swagger = "2.0"
    info = {
      title   = "acs-integration-internal"
      version = "1.0.0"
    }
    schemes = ["https"]
    paths   = merge(local.health_path, local.integration_paths)
  }

  openapi_yaml = yamlencode(local.openapi_struct)
  api_config_revision = sha256(jsonencode({
    spec       = local.openapi_struct
    backend_sa = var.backend_service_account_email
  }))
}

resource "google_api_gateway_api" "internal" {
  provider = google-beta
  api_id   = "acs-integration-internal"
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
  gateway_id = "acs-integration-internal"

  depends_on = [google_api_gateway_api_config.internal]
}

output "gateway_hostname" {
  description = "Integration internal gateway (proxy same paths on public API)."
  value       = google_api_gateway_gateway.internal.default_hostname
}
