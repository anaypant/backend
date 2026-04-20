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

locals {
  _bridge_base = trimspace(var.fub_webhook_sync_worker_url)
  core_env_public = merge(
    {
      DB_INTERNAL_GATEWAY_HOSTNAME      = var.db_internal_gateway_hostname
      LLM_INTERNAL_GATEWAY_HOSTNAME     = var.llm_internal_gateway_hostname
      LLM_INTERNAL_JWT_AUDIENCE         = var.llm_internal_jwt_audience
      SECRETS_INTERNAL_GATEWAY_HOSTNAME = var.secrets_internal_gateway_hostname
      SECRETS_INTERNAL_JWT_AUDIENCE     = var.secrets_internal_jwt_audience
      BACKEND_SERVICE_ACCOUNT_EMAIL     = var.backend_service_account_email
    },
    local._bridge_base != "" ? { INTEGRATION_BRIDGE_BASE_URL = trimsuffix(local._bridge_base, "/") } : {},
  )
}

data "archive_file" "fn" {
  type        = "zip"
  source_dir  = "${path.module}/runner"
  output_path = "${path.module}/.build/core-runner.zip"
}

resource "google_storage_bucket" "gcf_source" {
  name                        = "${var.project_id}-core-fn"
  location                    = var.region
  uniform_bucket_level_access = true
}

resource "google_storage_bucket_object" "fn" {
  name   = "core-runner-${data.archive_file.fn.output_md5}.zip"
  bucket = google_storage_bucket.gcf_source.name
  source = data.archive_file.fn.output_path

  depends_on = [google_storage_bucket.gcf_source]
}

resource "google_cloudfunctions2_function" "core_run" {
  name     = "core-run"
  location = var.region

  build_config {
    runtime     = "python312"
    entry_point = "main"
    source {
      storage_source {
        bucket = google_storage_bucket.gcf_source.name
        object = google_storage_bucket_object.fn.name
      }
    }
  }

  service_config {
    max_instance_count               = 5
    available_memory                 = "512Mi"
    timeout_seconds                  = 120
    ingress_settings                 = "ALLOW_ALL"
    max_instance_request_concurrency = 1
    service_account_email            = var.backend_service_account_email
    environment_variables            = local.core_env_public
  }
}

resource "google_cloudfunctions2_function_iam_member" "platform_invoker" {
  project        = var.project_id
  location       = var.region
  cloud_function = google_cloudfunctions2_function.core_run.name
  role           = "roles/cloudfunctions.invoker"
  member         = "serviceAccount:${var.backend_service_account_email}"
}

resource "google_cloud_run_v2_service_iam_member" "platform_run_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloudfunctions2_function.core_run.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.backend_service_account_email}"
}

output "core_run_function" {
  value = {
    url  = google_cloudfunctions2_function.core_run.url
    name = google_cloudfunctions2_function.core_run.name
  }
}
