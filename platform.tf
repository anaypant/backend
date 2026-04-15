data "google_project" "project" {
  project_id = local.project_id
}

locals {
  _apigw_mgmt = "serviceAccount:service-${data.google_project.project.number}@gcp-sa-apigateway-mgmt.iam.gserviceaccount.com"
}

resource "google_service_account" "platform" {
  project      = local.project_id
  account_id   = "acs-platform"
  display_name = "ACS platform (gateways + Cloud Functions)"
  depends_on   = [google_project_service.gcp]
}

resource "google_project_iam_member" "platform_editor" {
  project    = local.project_id
  role       = "roles/editor"
  member     = "serviceAccount:${google_service_account.platform.email}"
  depends_on = [google_project_service.gcp]
}

resource "google_project_iam_member" "platform_firebase_auth" {
  project    = local.project_id
  role       = "roles/firebaseauth.admin"
  member     = "serviceAccount:${google_service_account.platform.email}"
  depends_on = [google_project_service.gcp]
}

# secrets-bridge (same SA) reads/writes tenant secrets in GSM; write_version idempotency calls access_secret_version.
# Explicit binding documents the requirement if roles/editor is removed or org policy narrows Editor.
resource "google_project_iam_member" "platform_secret_manager" {
  project    = local.project_id
  role       = "roles/secretmanager.admin"
  member     = "serviceAccount:${google_service_account.platform.email}"
  depends_on = [google_project_service.gcp]
}

resource "google_project_iam_member" "platform_run_invoker" {
  project    = local.project_id
  role       = "roles/run.invoker"
  member     = "serviceAccount:${google_service_account.platform.email}"
  depends_on = [google_project_service.gcp]
}

resource "google_service_account_iam_member" "platform_apigateway_token" {
  service_account_id = google_service_account.platform.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local._apigw_mgmt
  depends_on         = [google_project_service.gcp]
}
