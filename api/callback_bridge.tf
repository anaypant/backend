# Public API callback bridge — validates OAuth state at the edge, forwards to internal integration with
# X-ACS-Callback-Bridge-Token (HS256) when ACS_CALLBACK_BRIDGE_SECRET is set.

data "archive_file" "callback_bridge" {
  type        = "zip"
  source_dir  = "${path.module}/functions/callback_bridge"
  output_path = "${path.module}/.build/callback-bridge.zip"
}

resource "google_storage_bucket" "callback_bridge_gcf" {
  name                        = "${var.project_id}-api-callback-bridge"
  location                    = var.region
  uniform_bucket_level_access = true
}

resource "google_storage_bucket_object" "callback_bridge_bundle" {
  name   = "callback-bridge-${data.archive_file.callback_bridge.output_md5}.zip"
  bucket = google_storage_bucket.callback_bridge_gcf.name
  source = data.archive_file.callback_bridge.output_path

  depends_on = [google_storage_bucket.callback_bridge_gcf]
}

resource "google_cloudfunctions2_function" "callback_bridge" {
  name     = "acs-callback-bridge"
  location = var.region

  build_config {
    runtime     = "python312"
    entry_point = "main"
    source {
      storage_source {
        bucket = google_storage_bucket.callback_bridge_gcf.name
        object = google_storage_bucket_object.callback_bridge_bundle.name
      }
    }
  }

  service_config {
    max_instance_count               = 10
    available_memory                 = "256Mi"
    # Concurrency > 1 requires >= 1 vCPU on Cloud Run (default CPU at 256Mi is fractional).
    available_cpu                    = "1"
    timeout_seconds                  = 60
    ingress_settings                 = "ALLOW_ALL"
    max_instance_request_concurrency = 4
    service_account_email            = var.platform_service_account_email
    environment_variables = {
      INTEGRATION_INTERNAL_GATEWAY_HOSTNAME = trimsuffix(trimprefix(var.integration_internal_gateway_hostname, "https://"), "/")
      ACS_CALLBACK_BRIDGE_SECRET            = var.acs_callback_bridge_secret
      ACS_OAUTH_STATE_SECRET                = var.acs_oauth_state_secret
    }
  }
}

resource "google_cloudfunctions2_function_iam_member" "callback_bridge_platform_invoker" {
  project        = var.project_id
  location       = var.region
  cloud_function = google_cloudfunctions2_function.callback_bridge.name
  role           = "roles/cloudfunctions.invoker"
  member         = "serviceAccount:${var.platform_service_account_email}"
}

resource "google_cloud_run_v2_service_iam_member" "callback_bridge_platform_run_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloudfunctions2_function.callback_bridge.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.platform_service_account_email}"
}
