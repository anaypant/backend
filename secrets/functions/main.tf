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
  output_path = "${path.module}/.build/secrets-bridge.zip"
}

resource "google_storage_bucket" "gcf_source" {
  name                        = "${var.project_id}-secrets-fn"
  location                    = var.region
  uniform_bucket_level_access = true
}

resource "google_storage_bucket_object" "bundle" {
  name   = "secrets-bridge-${data.archive_file.bundle.output_md5}.zip"
  bucket = google_storage_bucket.gcf_source.name
  source = data.archive_file.bundle.output_path

  depends_on = [google_storage_bucket.gcf_source]
}

resource "google_cloudfunctions2_function" "bridge" {
  name     = "secrets-bridge"
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
      {
        GCP_PROJECT                        = var.project_id
        GOOGLE_CLOUD_PROJECT               = var.project_id
        ACS_PLATFORM_SERVICE_ACCOUNT_EMAIL = var.backend_service_account_email
      },
      var.secrets_internal_gateway_hostname != "" ? {
        ACS_SECRETS_GATEWAY_HOSTNAME = var.secrets_internal_gateway_hostname
      } : {},
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
