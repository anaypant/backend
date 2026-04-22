# Public API Gateway — /health, /db/*, /auth/*, /integrations/*, POST /core/v1/run — proxied to internal gateways.
#
# Secured routes: Authorization: Bearer <Firebase ID token>. ESP validates JWT and forwards claims as
# X-Endpoint-API-UserInfo; backends verify Firebase or trust UserInfo when set by ESP (acs_internal).
#
# `parameters` + `schema` enable request validation at the gateway so malformed bodies fail with 400
# before traffic reaches Cloud Functions (per OpenAPI 2 / API Gateway behavior).

locals {
  db_internal_base          = "https://${trimsuffix(var.db_internal_gateway_hostname, "/")}"
  auth_internal_base        = "https://${trimsuffix(var.auth_internal_gateway_hostname, "/")}"
  integration_internal_base = "https://${trimsuffix(var.integration_internal_gateway_hostname, "/")}"
  core_internal_base        = "https://${trimsuffix(var.core_internal_gateway_hostname, "/")}"

  # ESPv2 defaults to a 15s backend deadline; OAuth + FUB webhook sync exceeds it (504 response_timeout).
  # Align with integration / callback_bridge Cloud Functions (timeout_seconds = 60).
  integration_upstream_deadline = 60.0

  # Core runner Cloud Function timeout is 120s; keep ESP deadline in range.
  core_upstream_deadline = 120.0

  # Routes where OpenAPI `security` is empty: no Firebase / application JWT required at the public edge.
  # Keep in sync with `paths` below (operations using security: []).
  public_routes_no_application_jwt = [
    "GET /health",
    "POST /auth/realtor/signup",
    "POST /auth/realtor/login",
    "POST /auth/internal/signup",
    "POST /auth/internal/login",
    "POST /integrations/webhooks/followupboss",
    "GET /integrations/followupboss/oauth/start",
    "OPTIONS /integrations/followupboss/oauth/start",
    "OPTIONS /integrations/followupboss/status",
    "GET /integrations/followupboss/oauth/callback",
  ]

  # Firebase Auth JWT validated at public ESP; payload forwarded as X-Endpoint-API-UserInfo to backends.
  firebase_security_definitions = {
    firebase = {
      authorizationUrl   = ""
      flow               = "implicit"
      type               = "oauth2"
      x-google-issuer    = "https://securetoken.google.com/${var.project_id}"
      x-google-jwks_uri  = "https://www.googleapis.com/service_accounts/v1/metadata/x509/securetoken@system.gserviceaccount.com"
      x-google-audiences = var.project_id
    }
  }
  firebase_sec = [{ firebase = [] }]

  db_body_read = {
    name     = "body"
    in       = "body"
    required = true
    schema = {
      type     = "object"
      required = ["path"]
      properties = {
        path = { type = "string" }
      }
    }
  }

  db_body_upsert = {
    name     = "body"
    in       = "body"
    required = true
    schema = {
      type     = "object"
      required = ["path", "data"]
      properties = {
        path  = { type = "string" }
        data  = { type = "object" }
        merge = { type = "boolean" }
      }
    }
  }

  db_body_delete = {
    name     = "body"
    in       = "body"
    required = true
    schema = {
      type     = "object"
      required = ["path"]
      properties = {
        path = { type = "string" }
      }
    }
  }

  db_body_query = {
    name     = "body"
    in       = "body"
    required = true
    schema = {
      type     = "object"
      required = ["path"]
      properties = {
        path            = { type = "string" }
        filters         = { type = "array" }
        orderBy         = { type = "array" }
        limit           = { type = "integer" }
        pageToken       = { type = "string" }
        collectionGroup = { type = "boolean" }
      }
    }
  }

  auth_body_nonempty = {
    name     = "body"
    in       = "body"
    required = true
    schema = {
      type                 = "object"
      minProperties        = 1
      additionalProperties = true
    }
  }

  integration_json_object_body = {
    name     = "body"
    in       = "body"
    required = true
    schema = {
      type                 = "object"
      additionalProperties = true
    }
  }

  webhook_ingress_parameters = [
    {
      name     = "connectionId"
      in       = "query"
      required = true
      type     = "string"
    },
    local.integration_json_object_body,
  ]

  db_proxy_paths = {
    "/db/read" = {
      post = {
        summary     = "DB read (proxied to internal DB gateway)"
        operationId = "db_read"
        consumes    = ["application/json"]
        produces    = ["application/json"]
        parameters  = [local.db_body_read]
        security    = local.firebase_sec
        "x-google-backend" = {
          address          = "${local.db_internal_base}/db/read/"
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
    "/db/upsert" = {
      post = {
        summary     = "DB upsert (proxied to internal DB gateway)"
        operationId = "db_upsert"
        consumes    = ["application/json"]
        produces    = ["application/json"]
        parameters  = [local.db_body_upsert]
        security    = local.firebase_sec
        "x-google-backend" = {
          address          = "${local.db_internal_base}/db/upsert/"
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
    "/db/delete" = {
      post = {
        summary     = "DB delete (proxied to internal DB gateway)"
        operationId = "db_delete"
        consumes    = ["application/json"]
        produces    = ["application/json"]
        parameters  = [local.db_body_delete]
        security    = local.firebase_sec
        "x-google-backend" = {
          address          = "${local.db_internal_base}/db/delete/"
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
    "/db/query" = {
      post = {
        summary     = "DB query (proxied to internal DB gateway)"
        operationId = "db_query"
        consumes    = ["application/json"]
        produces    = ["application/json"]
        parameters  = [local.db_body_query]
        security    = local.firebase_sec
        "x-google-backend" = {
          address          = "${local.db_internal_base}/db/query/"
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
        parameters  = [local.auth_body_nonempty]
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
          deadline         = local.integration_upstream_deadline
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
    "/integrations/followupboss/status" = {
      options = {
        summary     = "CORS preflight for followupboss/status (browser integration UI)"
        operationId = "integrations_followupboss_status_options"
        consumes    = ["text/plain"]
        produces    = ["text/plain"]
        security    = []
        "x-google-backend" = {
          address          = "${local.integration_internal_base}/integrations/followupboss/status/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
          deadline         = local.integration_upstream_deadline
        }
        responses = {
          "204" = { description = "No content" }
          "403" = { description = "Forbidden" }
        }
      }
      get = {
        summary     = "Integration followupboss/status (proxied to internal integration gateway)"
        operationId = "integrations_followupboss_status"
        produces    = ["application/json"]
        security    = local.firebase_sec
        "x-google-backend" = {
          address          = "${local.integration_internal_base}/integrations/followupboss/status/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
          deadline         = local.integration_upstream_deadline
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
      options = {
        summary     = "CORS preflight for oauth/start (browser OAuth SPA; no Firebase on OPTIONS)"
        operationId = "integrations_followupboss_oauth_start_options"
        consumes    = ["text/plain"]
        produces    = ["text/plain"]
        security    = []
        "x-google-backend" = {
          address          = "${local.integration_internal_base}/integrations/followupboss/oauth/start/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
          deadline         = local.integration_upstream_deadline
        }
        responses = {
          "204" = { description = "No content" }
          "403" = { description = "Forbidden" }
        }
      }
      get = {
        summary     = "Integration followupboss/oauth/start (proxied to internal integration gateway)"
        operationId = "integrations_followupboss_oauth_start"
        produces    = ["application/json"]
        # No gateway Firebase check: ESP 401s omit CORS headers, so browser SPAs see a bogus CORS block.
        # JWT is still required and verified inside integration-bridge (same pattern as oauth/callback).
        security = []
        "x-google-backend" = {
          address          = "${local.integration_internal_base}/integrations/followupboss/oauth/start/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
          deadline         = local.integration_upstream_deadline
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
        summary     = "FUB OAuth callback (public callback-bridge validates state, then internal integration)"
        operationId = "integrations_followupboss_oauth_callback"
        produces    = ["application/json"]
        security    = []
        "x-google-backend" = {
          address          = "${trimsuffix(google_cloudfunctions2_function.callback_bridge.url, "/")}/"
          path_translation = "APPEND_PATH_TO_ADDRESS"
          protocol         = "h2"
          jwt_audience     = trimsuffix(google_cloudfunctions2_function.callback_bridge.url, "/")
          deadline         = local.integration_upstream_deadline
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
        security    = local.firebase_sec
        "x-google-backend" = {
          address          = "${local.integration_internal_base}/integrations/followupboss/refresh/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
          deadline         = local.integration_upstream_deadline
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
        security    = local.firebase_sec
        "x-google-backend" = {
          address          = "${local.integration_internal_base}/integrations/followupboss/resync_webhooks/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
          deadline         = local.integration_upstream_deadline
        }
        responses = {
          "200" = { description = "OK" }
          "202" = { description = "Accepted — webhook sync enqueued (Cloud Tasks)" }
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
        summary     = "Integration followupboss/webhooks list (proxied to internal integration gateway)"
        operationId = "integrations_followupboss_webhooks_list"
        produces    = ["application/json"]
        security    = local.firebase_sec
        "x-google-backend" = {
          address          = "${local.integration_internal_base}/integrations/followupboss/webhooks/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
          deadline         = local.integration_upstream_deadline
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
    "/integrations/followupboss/webhook_test" = {
      post = {
        summary     = "Integration followupboss/webhook_test (proxied to internal integration gateway)"
        operationId = "integrations_followupboss_webhook_test"
        consumes    = ["application/json"]
        produces    = ["application/json"]
        security    = local.firebase_sec
        "x-google-backend" = {
          address          = "${local.integration_internal_base}/integrations/followupboss/webhook_test/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
          deadline         = local.integration_upstream_deadline
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
        security    = local.firebase_sec
        "x-google-backend" = {
          address          = "${local.integration_internal_base}/integrations/followupboss/disconnect/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
          deadline         = local.integration_upstream_deadline
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

  core_proxy_paths = {
    "/core/v1/run" = {
      post = {
        summary     = "Core workflow run (proxied to internal core API gateway)"
        operationId = "core_v1_run"
        consumes    = ["application/json"]
        produces    = ["application/json"]
        parameters  = [local.integration_json_object_body]
        security    = local.firebase_sec
        "x-google-backend" = {
          address          = "${local.core_internal_base}/core/v1/run/"
          path_translation = "CONSTANT_ADDRESS"
          protocol         = "h2"
          deadline         = local.core_upstream_deadline
        }
        responses = {
          "200" = { description = "OK" }
          "400" = { description = "Bad request" }
          "401" = { description = "Unauthorized" }
          "403" = { description = "Forbidden" }
          "404" = { description = "Not found" }
          "405" = { description = "Method not allowed" }
          "500" = { description = "Error" }
          "503" = { description = "Unavailable" }
        }
      }
    }
  }

  openapi_struct = {
    swagger             = "2.0"
    securityDefinitions = local.firebase_security_definitions
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
      local.integration_proxy_paths,
      local.core_proxy_paths
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

  depends_on = [google_cloudfunctions2_function.callback_bridge]

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

  lifecycle {
    postcondition {
      condition = (
        var.acs_public_integration_base_url == "" ||
        trim(var.acs_public_integration_base_url, "/") == "https://${self.default_hostname}"
      )
      error_message = "acs_public_integration_base_url must be empty or exactly https://${self.default_hostname} (single source: match output public_gateway_base_url)."
    }
  }
}
