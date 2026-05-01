# Internal Integration API — routes match public proxy paths (backend SA + ESP same as db/auth/core).
#
# !! ROUTE PARITY RULE !!
# Every integration path in backend/api/gateway.tf that routes to integration_internal_base MUST
# have a matching entry in the integration_paths local below.  Omitting a path here causes the
# internal gateway to return 404 even though the public gateway correctly accepts the request.
# Run before every deploy:
#
#   python backend/scripts/check_routes.py
#
# See also: backend/scripts/README.md

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

  # ESPv2 default backend deadline is 15s; OAuth callback + webhook sync needs longer (matches public gateway + CF timeout).
  integration_backend = {
    address          = trimsuffix(var.bridge_function.url, "/")
    path_translation = "APPEND_PATH_TO_ADDRESS"
    protocol         = "h2"
    jwt_audience     = trimsuffix(var.bridge_function.url, "/")
    deadline         = 60.0
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
    "/integrations/webhooks/v1/{provider}" = {
      post = {
        summary            = "Integration webhooks v1 by provider"
        operationId        = "integrations_webhooks_v1_provider"
        consumes           = ["application/json"]
        produces           = ["application/json"]
        security           = []
        parameters = [
          {
            name     = "provider"
            in       = "path"
            required = true
            type     = "string"
          }
        ]
        "x-google-backend" = local.integration_backend
        responses = {
          "200" = { description = "OK" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
          "404" = { description = "Not found" }
          "405" = { description = "Method not allowed" }
          "501" = { description = "Not implemented" }
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
          "202" = { description = "Accepted — webhook sync enqueued" }
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
    "/integrations/followupboss/qa/unit_checks" = {
      post = {
        summary            = "Integration followupboss QA unit checks (Firebase JWT at bridge)"
        operationId        = "integrations_followupboss_qa_unit_checks"
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
    "/integrations/followupboss/people/list" = {
      post = {
        summary            = "Integration followupboss/people/list (FUB read-only page; workflows run in core)"
        operationId        = "integrations_followupboss_people_list"
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
    # ── FUB direct people / notes / tasks / tags / import (CLI + admin-center) ──
    "/integrations/followupboss/people/get" = {
      post = {
        summary            = "FUB get person by ID"
        operationId        = "integrations_followupboss_people_get"
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
          "502" = { description = "Bad gateway" }
        }
      }
    }
    "/integrations/followupboss/people/create" = {
      post = {
        summary            = "FUB create/upsert person"
        operationId        = "integrations_followupboss_people_create"
        consumes           = ["application/json"]
        produces           = ["application/json"]
        security           = []
        "x-google-backend" = local.integration_backend
        responses = {
          "200" = { description = "OK" }
          "201" = { description = "Created" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
          "502" = { description = "Bad gateway" }
        }
      }
    }
    "/integrations/followupboss/people/update" = {
      post = {
        summary            = "FUB update person fields"
        operationId        = "integrations_followupboss_people_update"
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
          "502" = { description = "Bad gateway" }
        }
      }
    }
    "/integrations/followupboss/people/stage" = {
      post = {
        summary            = "FUB set person pipeline stage"
        operationId        = "integrations_followupboss_people_stage"
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
          "502" = { description = "Bad gateway" }
        }
      }
    }
    "/integrations/followupboss/people/tags/add" = {
      post = {
        summary            = "FUB add tags to person"
        operationId        = "integrations_followupboss_people_tags_add"
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
          "502" = { description = "Bad gateway" }
        }
      }
    }
    "/integrations/followupboss/people/tags/remove" = {
      post = {
        summary            = "FUB remove tags from person"
        operationId        = "integrations_followupboss_people_tags_remove"
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
          "502" = { description = "Bad gateway" }
        }
      }
    }
    "/integrations/followupboss/notes/create" = {
      post = {
        summary            = "FUB create note for person"
        operationId        = "integrations_followupboss_notes_create"
        consumes           = ["application/json"]
        produces           = ["application/json"]
        security           = []
        "x-google-backend" = local.integration_backend
        responses = {
          "200" = { description = "OK" }
          "201" = { description = "Created" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
          "502" = { description = "Bad gateway" }
        }
      }
    }
    "/integrations/followupboss/tasks/create" = {
      post = {
        summary            = "FUB create task for person"
        operationId        = "integrations_followupboss_tasks_create"
        consumes           = ["application/json"]
        produces           = ["application/json"]
        security           = []
        "x-google-backend" = local.integration_backend
        responses = {
          "200" = { description = "OK" }
          "201" = { description = "Created" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
          "502" = { description = "Bad gateway" }
        }
      }
    }
    "/integrations/followupboss/import" = {
      post = {
        summary            = "FUB import people into Firestore (single or full sync)"
        operationId        = "integrations_followupboss_import"
        consumes           = ["application/json"]
        produces           = ["application/json"]
        security           = []
        "x-google-backend" = merge(local.integration_backend, { deadline = 300.0 })
        responses = {
          "200" = { description = "OK" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
          "404" = { description = "Not found" }
          "502" = { description = "Bad gateway" }
        }
      }
    }
    "/integrations/internal/state/from_providers" = {
      post = {
        summary            = "State bridge internal: from_providers (platform OIDC)"
        operationId        = "integrations_internal_state_from_providers"
        consumes           = ["application/json"]
        produces           = ["application/json"]
        security           = []
        "x-google-backend" = local.integration_backend
        responses = {
          "200" = { description = "OK" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
          "405" = { description = "Method not allowed" }
          "502" = { description = "Bad gateway" }
          "503" = { description = "Unavailable" }
        }
      }
    }
    "/integrations/internal/state/to_providers" = {
      post = {
        summary            = "State bridge internal: to_providers (platform OIDC)"
        operationId        = "integrations_internal_state_to_providers"
        consumes           = ["application/json"]
        produces           = ["application/json"]
        security           = []
        "x-google-backend" = local.integration_backend
        responses = {
          "200" = { description = "OK" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
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
