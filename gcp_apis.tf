# Project API enablement (single place). Keep disable_on_destroy = false so tearing
# down one stack does not turn off APIs other workloads may still need.
resource "google_project_service" "gcp" {
  for_each = toset([
    "apigateway.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudfunctions.googleapis.com",
    "compute.googleapis.com",
    "firestore.googleapis.com",
    "identitytoolkit.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "run.googleapis.com",
    "servicecontrol.googleapis.com",
    "servicemanagement.googleapis.com",
    "securetoken.googleapis.com",
  ])
  project            = local.project_id
  service            = each.key
  disable_on_destroy = false
}
