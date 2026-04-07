# Global external Application Load Balancer (EXTERNAL_MANAGED) + serverless NEG → API Gateway.
# Cloud Armor is attached to the backend service (supported for serverless NEG + API Gateway).

resource "google_compute_security_policy" "public_api" {
  name    = "acs-public-api-armor"
  project = var.project_id

  # Per-client-IP throttle before the default allow. Tune count/interval for your traffic profile.
  rule {
    action   = "throttle"
    priority = 1000
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    rate_limit_options {
      conform_action = "allow"
      exceed_action  = "deny(429)"
      enforce_on_key = "IP"
      rate_limit_threshold {
        count        = 100
        interval_sec = 60
      }
    }
    description = "Simple per-IP limit: 100 requests per 60s, then HTTP 429."
  }

  rule {
    action   = "allow"
    priority = 2147483647
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    description = "Default allow (tighten with deny/rate rules as you iterate)."
  }
}

resource "google_compute_global_address" "public_api" {
  name    = "acs-public-api-lb-ip"
  project = var.project_id
}

resource "google_compute_region_network_endpoint_group" "public_gateway" {
  provider = google-beta

  name                  = "acs-public-api-gw-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.region
  project               = var.project_id

  serverless_deployment {
    platform = "apigateway.googleapis.com"
    resource = google_api_gateway_gateway.public.gateway_id
  }

  depends_on = [google_api_gateway_gateway.public]
}

resource "google_compute_backend_service" "public_api" {
  name                  = "acs-public-api-bs"
  project               = var.project_id
  load_balancing_scheme = "EXTERNAL_MANAGED"
  protocol              = "HTTPS"
  security_policy       = google_compute_security_policy.public_api.self_link

  backend {
    group = google_compute_region_network_endpoint_group.public_gateway.id
  }
}

resource "google_compute_url_map" "public_api" {
  name            = "acs-public-api-url-map"
  project         = var.project_id
  default_service = google_compute_backend_service.public_api.id
}

resource "google_compute_target_http_proxy" "public_api" {
  name    = "acs-public-api-http-proxy"
  project = var.project_id
  url_map = google_compute_url_map.public_api.id
}

resource "google_compute_global_forwarding_rule" "public_api_http" {
  name                  = "acs-public-api-http-fr"
  project               = var.project_id
  load_balancing_scheme = "EXTERNAL_MANAGED"
  target                = google_compute_target_http_proxy.public_api.id
  port_range            = "80"
  ip_address            = google_compute_global_address.public_api.id
  ip_protocol           = "TCP"
}
