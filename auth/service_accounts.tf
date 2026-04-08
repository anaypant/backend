resource "google_service_account" "auth_backend" {
  project      = var.project_id
  account_id   = "acs-auth-backend"
  display_name = "ACS Auth backend (internal gateway + Cloud Functions)"
}

resource "google_project_iam_member" "auth_backend_firebaseauth_admin" {
  project = var.project_id
  role    = "roles/firebaseauth.admin"
  member  = "serviceAccount:${google_service_account.auth_backend.email}"
}
