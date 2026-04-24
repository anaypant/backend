# Cloud Scheduler jobs for Glyde daily automations.
#
# Each job POSTs to the internal glyde scheduler route with a service-account OIDC token.
# The scheduler_trigger handler in providers/glyde/provider.py validates the token,
# then dispatches the appropriate workflow to core.
#
# NOTE: The scheduler iterates over all realtors who have the workflow enabled.
# For multi-tenant scale, replace with Pub/Sub fan-out (one message per realtor).
# For now, the scheduler payload carries a placeholder uid; the integration layer
# must expand this to per-realtor runs via the FUB connection registry.

locals {
  glyde_scheduler_url = "${module.api.gateway_hostname != "" ? "https://${module.api.gateway_hostname}" : "https://integration-placeholder.example.com"}/integrations/internal/glyde/scheduler"
}

resource "google_cloud_scheduler_job" "glyde_drip_daily" {
  project     = var.project_id
  region      = var.region
  name        = "glyde-drip-daily"
  description = "Glyde daily drip campaign run (birthdays, home anniversaries)."
  schedule    = "0 6 * * *"
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = local.glyde_scheduler_url
    body        = base64encode(jsonencode({ job = "glyde-drip-daily", uid = "__all_realtors__" }))

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = var.platform_sa_email
      audience              = local.glyde_scheduler_url
    }
  }

  depends_on = [module.api]
}

resource "google_cloud_scheduler_job" "glyde_hot_leads_daily" {
  project     = var.project_id
  region      = var.region
  name        = "glyde-hot-leads-daily"
  description = "Glyde daily hot-leads shortlist refresh."
  schedule    = "0 7 * * *"
  time_zone   = "UTC"

  http_target {
    http_method = "POST"
    uri         = local.glyde_scheduler_url
    body        = base64encode(jsonencode({ job = "glyde-hot-leads-daily", uid = "__all_realtors__" }))

    headers = {
      "Content-Type" = "application/json"
    }

    oidc_token {
      service_account_email = var.platform_sa_email
      audience              = local.glyde_scheduler_url
    }
  }

  depends_on = [module.api]
}
