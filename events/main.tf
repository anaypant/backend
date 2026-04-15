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

resource "google_pubsub_topic" "domain_events" {
  name = "acs-domain-events"
}

resource "google_pubsub_topic_iam_member" "platform_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.domain_events.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${var.platform_sa_email}"
}

module "functions" {
  source                          = "./functions"
  project_id                      = var.project_id
  region                          = var.region
  backend_service_account_email   = var.platform_sa_email
  pubsub_topic_id                 = google_pubsub_topic.domain_events.id
  events_internal_gateway_hostname = var.events_internal_gateway_hostname
}

module "api" {
  source = "./api"
  providers = {
    google      = google
    google-beta = google-beta
  }
  project_id                    = var.project_id
  region                        = var.region
  events_bridge_function        = module.functions.events_bridge_function
  backend_service_account_email = var.platform_sa_email
  depends_on                    = [module.functions]
}

output "events_gateway_hostname" {
  description = "POST https://<hostname>/events/v1/publish — platform OIDC."
  value       = module.api.gateway_hostname
}

output "events_gateway_audience" {
  description = "Google ID token audience for this gateway."
  value       = module.api.gateway_audience
}

output "domain_events_topic_id" {
  description = "Pub/Sub topic id for acs-domain-events (subscribe with separate subscriptions)."
  value       = google_pubsub_topic.domain_events.id
}
