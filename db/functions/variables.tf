variable "region" {
  type        = string
  description = "Region for Cloud Functions (2nd gen) and source bucket."
  default     = "us-central1"
}

variable "project_id" {
  type        = string
  description = "Project ID to deploy the functions to"
}

variable "backend_service_account_email" {
  type        = string
  description = "DB backend SA allowed to invoke these Cloud Run services (e.g. API Gateway identity)."
}

variable "db_internal_gateway_hostname" {
  type        = string
  description = "Hostname of acs-db-internal API Gateway (no scheme); used as Google ID token audience for platform callers."
  default     = ""
}
