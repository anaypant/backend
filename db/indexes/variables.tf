variable "project_id" {
  type        = string
  description = "GCP project id where Firestore is hosted."
}

variable "firestore_database_id" {
  type        = string
  description = "Firestore database id, e.g. (default) from google_firestore_database.name."
}
