# Composite indexes for lite-frontend POST /db/query (ownerUid equality + orderBy).
# Without these, Firestore raises FAILED_PRECONDITION and the query handler returns 400.

resource "google_firestore_index" "lite_notifications_owner_created" {
  project    = var.project_id
  database   = var.firestore_database_id
  collection = "Notifications"

  fields {
    field_path = "ownerUid"
    order      = "ASCENDING"
  }
  fields {
    field_path = "createdAt"
    order      = "DESCENDING"
  }

  timeouts {
    create = "20m"
    delete = "10m"
  }
}

resource "google_firestore_index" "lite_appointments_owner_starts" {
  project    = var.project_id
  database   = var.firestore_database_id
  collection = "Appointments"

  fields {
    field_path = "ownerUid"
    order      = "ASCENDING"
  }
  fields {
    field_path = "startsAt"
    order      = "ASCENDING"
  }

  timeouts {
    create = "20m"
    delete = "10m"
  }

  depends_on = [google_firestore_index.lite_notifications_owner_created]
}

resource "google_firestore_index" "lite_workflow_activity_owner_created" {
  project    = var.project_id
  database   = var.firestore_database_id
  collection = "WorkflowActivity"

  fields {
    field_path = "ownerUid"
    order      = "ASCENDING"
  }
  fields {
    field_path = "createdAt"
    order      = "DESCENDING"
  }

  timeouts {
    create = "20m"
    delete = "10m"
  }

  depends_on = [google_firestore_index.lite_appointments_owner_starts]
}
