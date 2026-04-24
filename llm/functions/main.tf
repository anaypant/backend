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

data "archive_file" "fn" {
  type        = "zip"
  source_dir  = "${path.module}/runner"
  output_path = "${path.module}/.build/llm-complete.zip"
}

locals {
  llm_env_public = {
    BACKEND_SERVICE_ACCOUNT_EMAIL     = var.backend_service_account_email
    LLM_INTERNAL_JWT_AUDIENCE         = var.llm_internal_jwt_audience
    SECRETS_INTERNAL_GATEWAY_HOSTNAME = var.secrets_internal_gateway_hostname
    SECRETS_INTERNAL_JWT_AUDIENCE     = var.secrets_internal_jwt_audience
  }
  llm_env_secret = {
    OPENROUTER_API_KEY = var.openrouter_api_key
  }
}

resource "google_storage_bucket" "gcf_source" {
  name                        = "${var.project_id}-llm-fn"
  location                    = var.region
  uniform_bucket_level_access = true
}

resource "google_storage_bucket_object" "fn" {
  name   = "llm-complete-${data.archive_file.fn.output_md5}.zip"
  bucket = google_storage_bucket.gcf_source.name
  source = data.archive_file.fn.output_path

  depends_on = [google_storage_bucket.gcf_source]
}

resource "google_cloudfunctions2_function" "llm_complete" {
  name     = "llm-complete"
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
    max_instance_count = 10
    available_memory   = "512Mi"
    # Concurrency > 1 requires >= 1 vCPU on Cloud Run (default CPU at 512Mi is fractional).
    available_cpu                    = "1"
    timeout_seconds                  = 120
    ingress_settings                 = "ALLOW_ALL"
    max_instance_request_concurrency = 4
    service_account_email            = var.backend_service_account_email
    environment_variables            = merge(local.llm_env_public, local.llm_env_secret)
  }
}

resource "google_cloudfunctions2_function_iam_member" "platform_invoker" {
  project        = var.project_id
  location       = var.region
  cloud_function = google_cloudfunctions2_function.llm_complete.name
  role           = "roles/cloudfunctions.invoker"
  member         = "serviceAccount:${var.backend_service_account_email}"
}

resource "google_cloud_run_v2_service_iam_member" "platform_run_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloudfunctions2_function.llm_complete.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.backend_service_account_email}"
}

output "llm_complete_function" {
  value = {
    url  = google_cloudfunctions2_function.llm_complete.url
    name = google_cloudfunctions2_function.llm_complete.name
  }
}
