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
  functions = toset(["read", "upsert", "delete", "query"])
}

data "archive_file" "fn" {
  for_each    = local.functions
  type        = "zip"
  source_dir  = "${path.module}/${each.key}"
  output_path = "${path.module}/.build/${each.key}.zip"
}

resource "google_storage_bucket" "gcf_source" {
  # Project IDs are globally unique; no random suffix needed for a stable bucket name.
  name                        = "${var.project_id}-db-fn"
  location                    = var.region
  uniform_bucket_level_access = true
}

resource "google_storage_bucket_object" "fn" {
  for_each = local.functions
  name     = "${each.key}-${data.archive_file.fn[each.key].output_md5}.zip"
  bucket   = google_storage_bucket.gcf_source.name
  source   = data.archive_file.fn[each.key].output_path

  depends_on = [google_storage_bucket.gcf_source]
}

resource "google_cloudfunctions2_function" "fn" {
  for_each = local.functions
  # Stable name: deploys update the same Cloud Run service in place. MD5 on the bucket object only avoids stale source zips.
  name     = "db-${each.key}"
  location = var.region

  build_config {
    runtime     = "python312"
    entry_point = "main"
    source {
      storage_source {
        bucket = google_storage_bucket.gcf_source.name
        object = google_storage_bucket_object.fn[each.key].name
      }
    }
  }

  service_config {
    max_instance_count               = 5
    available_memory                 = "256Mi"
    timeout_seconds                  = 60
    ingress_settings                 = "ALLOW_ALL"
    max_instance_request_concurrency = 1
    environment_variables = merge(
      {},
      contains(["read", "upsert"], each.key) && var.db_internal_gateway_hostname != "" ? {
        ACS_PLATFORM_SERVICE_ACCOUNT_EMAIL = var.backend_service_account_email
        ACS_DB_GATEWAY_HOSTNAME            = var.db_internal_gateway_hostname
      } : {}
    )
  }
}

resource "google_cloudfunctions2_function_iam_member" "platform_invoker" {
  for_each = local.functions

  project        = var.project_id
  location       = var.region
  cloud_function = google_cloudfunctions2_function.fn[each.key].name
  role           = "roles/cloudfunctions.invoker"
  member         = "serviceAccount:${var.backend_service_account_email}"
}

resource "google_cloud_run_v2_service_iam_member" "platform_run_invoker" {
  for_each = local.functions

  project  = var.project_id
  location = var.region
  name     = google_cloudfunctions2_function.fn[each.key].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.backend_service_account_email}"
}

output "db_functions" {
  description = "URLs and Cloud Run service names for API Gateway wiring."
  value = {
    for k, f in google_cloudfunctions2_function.fn : k => {
      url  = f.url
      name = f.name
    }
  }
}

data "google_project" "current" {
  project_id = var.project_id
}

# Gen2 functions use the default Compute Engine SA unless service_config.service_account_email is set.
resource "google_project_iam_member" "gcf_firestore_user" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${data.google_project.current.number}-compute@developer.gserviceaccount.com"
}
