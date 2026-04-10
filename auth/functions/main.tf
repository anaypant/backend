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
  function_keys = toset(["realtor_signup", "realtor_login", "internal_signup", "internal_login"])
}

data "archive_file" "bundle" {
  type        = "zip"
  source_dir  = "${path.module}/bundle"
  output_path = "${path.module}/.build/auth-bundle.zip"
}

resource "google_storage_bucket" "gcf_source" {
  name                        = "${var.project_id}-auth-fn"
  location                    = var.region
  uniform_bucket_level_access = true
}

resource "google_storage_bucket_object" "bundle" {
  name   = "auth-bundle-${data.archive_file.bundle.output_md5}.zip"
  bucket = google_storage_bucket.gcf_source.name
  source = data.archive_file.bundle.output_path

  depends_on = [google_storage_bucket.gcf_source]
}

resource "google_cloudfunctions2_function" "fn" {
  for_each = local.function_keys
  # Stable name: same as db/functions — in-place deploys; bundle identity is tracked on the GCS object name.
  name     = "auth-${replace(each.key, "_", "-")}"
  location = var.region

  build_config {
    runtime     = "python312"
    entry_point = each.key
    source {
      storage_source {
        bucket = google_storage_bucket.gcf_source.name
        object = google_storage_bucket_object.bundle.name
      }
    }
  }

  service_config {
    max_instance_count = 10
    available_memory   = "256Mi"
    timeout_seconds    = 60
    ingress_settings   = "ALLOW_ALL"
    # Default CPU for 256Mi is <1; Cloud Run rejects concurrency > 1 unless CPU >= 1.
    max_instance_request_concurrency = 1
    service_account_email            = var.backend_service_account_email
    environment_variables = {
      FIREBASE_WEB_API_KEY         = var.firebase_web_api_key
      DB_INTERNAL_GATEWAY_HOSTNAME = var.db_internal_gateway_hostname
    }
  }
}

# Gen2 runs on Cloud Run: grant both CF invoker and Run invoker on the underlying service.
resource "google_cloudfunctions2_function_iam_member" "platform_invoker" {
  for_each = local.function_keys

  project        = var.project_id
  location       = var.region
  cloud_function = google_cloudfunctions2_function.fn[each.key].name
  role           = "roles/cloudfunctions.invoker"
  member         = "serviceAccount:${var.backend_service_account_email}"
}

resource "google_cloud_run_v2_service_iam_member" "platform_run_invoker" {
  for_each = local.function_keys

  project  = var.project_id
  location = var.region
  name     = google_cloudfunctions2_function.fn[each.key].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.backend_service_account_email}"
}

output "auth_functions" {
  description = "URLs and names for internal API Gateway wiring."
  value = {
    for k, f in google_cloudfunctions2_function.fn : k => {
      url  = f.url
      name = f.name
    }
  }
}
