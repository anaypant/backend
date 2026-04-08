variable "project_id" {
  type        = string
  description = "GCP project ID where the gateway and Cloud Functions run."
}

variable "region" {
  type        = string
  description = "Region of the gateway and Cloud Functions (e.g. us-central1)."
}

variable "db_functions" {
  type = map(object({
    url  = string
    name = string
  }))
  description = "Map keyed read|upsert|delete|query with function HTTPS URL and Cloud Run service name."
}

variable "backend_service_account_email" {
  type        = string
  description = "Root platform SA email for API Gateway backend_config (signs requests to Cloud Run)."
}
