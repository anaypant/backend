# Public API Gateway — /health plus /db/* proxied to the internal DB API Gateway (same paths and JSON bodies).

locals {
  db_internal_base           = "https://${trimsuffix(var.db_internal_gateway_hostname, "/")}"
  auth_internal_base         = "https://${trimsuffix(var.auth_internal_gateway_hostname, "/")}"
  integration_internal_base  = "https://${trimsuffix(var.integration_internal_gateway_hostname, "/")}"

  db_proxy_paths = {
    for key in ["read", "upsert", "delete", "query"] : "/db/${key}" => {
      post = {
        summary     = "DB ${key} (proxied to internal DB gateway)"
        operationId = "db_${key}"
        consumes    = ["application/json"]
        produces    = ["application/json"]
        security    = []
        "x-google-backend" = {
          address          = "${local.db_internal_base}/db/${key}/"
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

  auth_proxy_paths = {
    for path in [
      "/auth/realtor/signup",
      "/auth/realtor/login",
      "/auth/internal/signup",
      "/auth/internal/login",
      ] : path => {
      post = {
        summary     = "Auth ${trimprefix(path, "/auth/")} (proxied to internal auth gateway)"
        operationId = replace(replace(path, "/auth/", "auth_"), "/", "_")
        consumes    = ["application/json"]
        produces    = ["application/json"]
        security    = []
        "x-google-backend" = {
          address          = "${local.auth_internal_base}${path}/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
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

  integration_proxy_paths = {
    "/integrations/webhooks/followupboss" = {
      post = {
        summary     = "Integration webhooks/followupboss (proxied to internal integration gateway)"
        operationId = "integrations_webhooks_followupboss"
        consumes    = ["application/json"]
        produces    = ["application/json"]
        security    = []
        "x-google-backend" = {
          address          = "${local.integration_internal_base}/integrations/webhooks/followupboss/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
        }
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
      get = {
        summary     = "Integration followupboss/oauth/start (proxied to internal integration gateway)"
        operationId = "integrations_followupboss_oauth_start"
        produces    = ["application/json"]
        security    = []
        "x-google-backend" = {
          address          = "${local.integration_internal_base}/integrations/followupboss/oauth/start/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
        }
        responses = {
          "200" = { description = "OK" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
          "404" = { description = "Not found" }
          "405" = { description = "Method not allowed" }
          "501" = { description = "Not implemented" }
          "503" = { description = "Unavailable" }
        }
      }
    }
    "/integrations/followupboss/oauth/callback" = {
      get = {
        summary     = "Integration followupboss/oauth/callback (proxied to internal integration gateway)"
        operationId = "integrations_followupboss_oauth_callback"
        produces    = ["application/json"]
        security    = []
        "x-google-backend" = {
          address          = "${local.integration_internal_base}/integrations/followupboss/oauth/callback/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
        }
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
        summary     = "Integration followupboss/refresh (proxied to internal integration gateway)"
        operationId = "integrations_followupboss_refresh"
        consumes    = ["application/json"]
        produces    = ["application/json"]
        security    = []
        "x-google-backend" = {
          address          = "${local.integration_internal_base}/integrations/followupboss/refresh/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
        }
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
        summary     = "Integration followupboss/resync_webhooks (proxied to internal integration gateway)"
        operationId = "integrations_followupboss_resync_webhooks"
        consumes    = ["application/json"]
        produces    = ["application/json"]
        security    = []
        "x-google-backend" = {
          address          = "${local.integration_internal_base}/integrations/followupboss/resync_webhooks/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
        }
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
        summary     = "Integration followupboss/disconnect (proxied to internal integration gateway)"
        operationId = "integrations_followupboss_disconnect"
        consumes    = ["application/json"]
        produces    = ["application/json"]
        security    = []
        "x-google-backend" = {
          address          = "${local.integration_internal_base}/integrations/followupboss/disconnect/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
        }
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
      title   = "acs-public"
      version = "1.0.0"
    }
    schemes = ["https"]
    paths = merge(
      {
        "/health" = {
          get = {
            summary     = "Health check"
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
      },
      local.db_proxy_paths,
      local.auth_proxy_paths,
      local.integration_proxy_paths
    )
  }
  openapi_yaml = yamlencode(local.openapi_struct)
  api_config_revision = sha256(jsonencode({
    spec       = local.openapi_struct
    backend_sa = var.platform_service_account_email
  }))
}

resource "google_api_gateway_api" "public" {
  provider = google-beta
  api_id   = "acs-public"
}

resource "google_api_gateway_api_config" "public" {
  provider      = google-beta
  api           = google_api_gateway_api.public.api_id
  api_config_id = "cfg${substr(local.api_config_revision, 0, 32)}"

  openapi_documents {
    document {
      path     = "openapi.yaml"
      contents = base64encode(local.openapi_yaml)
    }
  }

  gateway_config {
    backend_config {
      google_service_account = var.platform_service_account_email
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_api_gateway_gateway" "public" {
  provider   = google-beta
  region     = var.region
  api_config = google_api_gateway_api_config.public.id
  gateway_id = "acs-public"

  depends_on = [google_api_gateway_api_config.public]
}
