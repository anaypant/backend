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

# Glyde: AppointmentPreps — query by owner, ordered by createdAt DESC
resource "google_firestore_index" "glyde_appointment_preps_owner_created" {
  project    = var.project_id
  database   = var.firestore_database_id
  collection = "AppointmentPreps"

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

  depends_on = [google_firestore_index.lite_workflow_activity_owner_created]
}

# Glyde: Leads — query by owner + glydeScore (hot-leads filter)
resource "google_firestore_index" "glyde_leads_owner_score" {
  project    = var.project_id
  database   = var.firestore_database_id
  collection = "Leads"

  fields {
    field_path = "ownerUid"
    order      = "ASCENDING"
  }
  fields {
    field_path = "glydeScore"
    order      = "DESCENDING"
  }

  timeouts {
    create = "20m"
    delete = "10m"
  }

  depends_on = [google_firestore_index.glyde_appointment_preps_owner_created]
}

# Glyde: DripLog — query by owner, ordered by runAt DESC
resource "google_firestore_index" "glyde_drip_log_owner_run_at" {
  project    = var.project_id
  database   = var.firestore_database_id
  collection = "DripLog"

  fields {
    field_path = "ownerUid"
    order      = "ASCENDING"
  }
  fields {
    field_path = "runAt"
    order      = "DESCENDING"
  }

  timeouts {
    create = "20m"
    delete = "10m"
  }

  depends_on = [google_firestore_index.glyde_leads_owner_score]
}

# Glyde: AdCampaigns — query by owner, ordered by updatedAt DESC
resource "google_firestore_index" "glyde_ad_campaigns_owner_updated" {
  project    = var.project_id
  database   = var.firestore_database_id
  collection = "AdCampaigns"

  fields {
    field_path = "ownerUid"
    order      = "ASCENDING"
  }
  fields {
    field_path = "updatedAt"
    order      = "DESCENDING"
  }

  timeouts {
    create = "20m"
    delete = "10m"
  }

  depends_on = [google_firestore_index.glyde_drip_log_owner_run_at]
}

# Glyde: CommunicationLog — query by owner, ordered by createdAt DESC
resource "google_firestore_index" "glyde_communication_log_owner_created" {
  project    = var.project_id
  database   = var.firestore_database_id
  collection = "CommunicationLog"

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

  depends_on = [google_firestore_index.glyde_ad_campaigns_owner_updated]
}
