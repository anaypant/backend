terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

data "archive_file" "bundle" {
  type        = "zip"
  source_dir  = "${path.module}/bundle"
  output_path = "${path.module}/.build/integration-bridge.zip"
}

# Public env must be nonsensitive so values learned at apply (e.g. secrets gateway hostname)
# do not trip "inconsistent values for sensitive attribute" on google_cloudfunctions2_function.
locals {
  integration_env_public = {
    DB_INTERNAL_GATEWAY_HOSTNAME      = var.db_internal_gateway_hostname
    CORE_INTERNAL_GATEWAY_HOSTNAME    = var.core_internal_gateway_hostname
    FUB_OAUTH_AUTHORIZE_URL           = var.fub_oauth_authorize_url
    FUB_OAUTH_TOKEN_URL               = var.fub_oauth_token_url
    FUB_OAUTH_CLIENT_ID               = var.fub_oauth_client_id
    FUB_SYSTEM_NAME                   = var.fub_system_name
    ACS_PUBLIC_INTEGRATION_BASE_URL   = var.acs_public_integration_base_url
    ACS_USE_SECRET_MANAGER            = "1"
    ACS_BROWSER_CORS_ORIGINS          = var.browser_cors_origins
    SECRETS_INTERNAL_GATEWAY_HOSTNAME = var.secrets_internal_gateway_hostname
    SECRETS_INTERNAL_JWT_AUDIENCE     = var.secrets_internal_jwt_audience
  }
  integration_env_secret = {
    FUB_OAUTH_CLIENT_SECRET       = var.fub_oauth_client_secret
    FUB_X_SYSTEM_KEY              = var.fub_x_system_key
    ACS_OAUTH_STATE_SECRET        = var.acs_oauth_state_secret
    ACS_CALLBACK_BRIDGE_SECRET   = var.acs_callback_bridge_secret
  }
}

resource "google_storage_bucket" "gcf_source" {
  name                        = "${var.project_id}-integration-fn"
  location                    = var.region
  uniform_bucket_level_access = true
}

resource "google_storage_bucket_object" "bundle" {
  name   = "integration-bridge-${data.archive_file.bundle.output_md5}.zip"
  bucket = google_storage_bucket.gcf_source.name
  source = data.archive_file.bundle.output_path

  depends_on = [google_storage_bucket.gcf_source]
}

resource "google_cloudfunctions2_function" "bridge" {
  name     = "integration-bridge"
  location = var.region

  build_config {
    runtime     = "python312"
    entry_point = "main"
    source {
      storage_source {
        bucket = google_storage_bucket.gcf_source.name
        object = google_storage_bucket_object.bundle.name
      }
    }
  }

  service_config {
    max_instance_count               = 10
    available_memory                 = "256Mi"
    timeout_seconds                  = 60
    ingress_settings                 = "ALLOW_ALL"
    max_instance_request_concurrency = 1
    service_account_email            = var.backend_service_account_email
    environment_variables = merge(
      nonsensitive(local.integration_env_public),
      local.integration_env_secret,
    )
  }
}

resource "google_cloudfunctions2_function_iam_member" "platform_invoker" {
  project        = var.project_id
  location       = var.region
  cloud_function = google_cloudfunctions2_function.bridge.name
  role           = "roles/cloudfunctions.invoker"
  member         = "serviceAccount:${var.backend_service_account_email}"
}

resource "google_cloud_run_v2_service_iam_member" "platform_run_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloudfunctions2_function.bridge.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.backend_service_account_email}"
}

output "bridge_function" {
  value = {
    url  = google_cloudfunctions2_function.bridge.url
    name = google_cloudfunctions2_function.bridge.name
  }
}
