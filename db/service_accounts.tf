# Single DB-layer backend identity; pass into submodules and attach roles per component.

resource "google_service_account" "db_backend" {
  project      = var.project_id
  account_id   = "acs-db-backend"
  display_name = "ACS DB backend (shared; IAM attached per submodule)"
}
