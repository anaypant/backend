# Public API Gateway — /health plus /db/* proxied to the internal DB API Gateway (same paths and JSON bodies).

locals {
  db_internal_base = "https://${trimsuffix(var.db_internal_gateway_hostname, "/")}"

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
      local.db_proxy_paths
    )
  }
  openapi_yaml = yamlencode(local.openapi_struct)
}

resource "google_api_gateway_api" "public" {
  provider = google-beta
  api_id   = "acs-public"
}

resource "google_api_gateway_api_config" "public" {
  provider      = google-beta
  api           = google_api_gateway_api.public.api_id
  api_config_id = "cfg${substr(md5(local.openapi_yaml), 0, 14)}"

  openapi_documents {
    document {
      path     = "openapi.yaml"
      contents = base64encode(local.openapi_yaml)
    }
  }

  gateway_config {
    backend_config {
      google_service_account = google_service_account.api_backend.email
    }
  }

  depends_on = [google_service_account_iam_member.apigateway_impersonate_backend]

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
