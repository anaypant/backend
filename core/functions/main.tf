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
    available_memory                 = "256Mi"
    timeout_seconds                  = 120
    ingress_settings                 = "ALLOW_ALL"
    max_instance_request_concurrency = 1
    service_account_email            = var.backend_service_account_email
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
