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
        summary     = "Run ACS workflow (LangGraph)"
        operationId = "core_run"
        consumes    = ["application/json"]
        produces    = ["application/json"]
        security    = []
        "x-google-backend" = {
          address          = "${trimsuffix(var.core_run_function.url, "/")}/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
          jwt_audience     = trimsuffix(var.core_run_function.url, "/")
          # ESPv2 default is 15s; enrichment runs take up to 30s (web search + LLM).
          deadline = 120.0
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

    # Usage / billing stats — current-month enrichment cost summary for authenticated user.
    # Path preserved via APPEND_PATH_TO_ADDRESS so main.py can route on request.path.
    "/core/v1/usage" = {
      get = {
        summary     = "Current-month enrichment usage and budget summary"
        operationId = "core_v1_usage"
        produces    = ["application/json"]
        security    = []
        "x-google-backend" = {
          address          = trimsuffix(var.core_run_function.url, "/")
          path_translation = "APPEND_PATH_TO_ADDRESS"
          protocol         = "h2"
          jwt_audience     = trimsuffix(var.core_run_function.url, "/")
          deadline         = 30.0
        }
        responses = {
          "200" = { description = "OK" }
          "401" = { description = "Unauthorized" }
          "500" = { description = "Error" }
        }
      }
    }

    # Glyde Lab endpoints — path is preserved via APPEND_PATH_TO_ADDRESS so
    # main.py can route on request.path.  Streaming SSE is served from /lab/run.
    "/core/v1/lab/graphs" = {
      get = {
        summary     = "List all workflow graph topologies"
        operationId = "lab_graphs"
        produces    = ["application/json"]
        security    = []
        "x-google-backend" = {
          address          = trimsuffix(var.core_run_function.url, "/")
          path_translation = "APPEND_PATH_TO_ADDRESS"
          protocol         = "h2"
          jwt_audience     = trimsuffix(var.core_run_function.url, "/")
        }
        responses = {
          "200" = { description = "OK" }
          "500" = { description = "Error" }
        }
      }
    }

    "/core/v1/lab/graph/{workflow_id}" = {
      get = {
        summary     = "Get topology for a single workflow"
        operationId = "lab_graph"
        produces    = ["application/json"]
        security    = []
        parameters = [
          {
            name     = "workflow_id"
            in       = "path"
            required = true
            type     = "string"
          }
        ]
        "x-google-backend" = {
          address          = trimsuffix(var.core_run_function.url, "/")
          path_translation = "APPEND_PATH_TO_ADDRESS"
          protocol         = "h2"
          jwt_audience     = trimsuffix(var.core_run_function.url, "/")
        }
        responses = {
          "200" = { description = "OK" }
          "404" = { description = "Not found" }
          "500" = { description = "Error" }
        }
      }
    }

    "/core/v1/lab/run" = {
      post = {
        summary     = "SSE streaming workflow run for Glyde Lab"
        operationId = "lab_run"
        consumes    = ["application/json"]
        produces    = ["text/event-stream"]
        security    = []
        "x-google-backend" = {
          address          = trimsuffix(var.core_run_function.url, "/")
          path_translation = "APPEND_PATH_TO_ADDRESS"
          protocol         = "h2"
          jwt_audience     = trimsuffix(var.core_run_function.url, "/")
        }
        responses = {
          "200" = { description = "SSE stream" }
          "400" = { description = "Bad request" }
          "500" = { description = "Error" }
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
