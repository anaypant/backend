variable "project_id" {
  type        = string
  description = "GCP project ID where the gateway and Cloud Functions run."
}

variable "region" {
  type        = string
  description = "Region of the gateway and Cloud Functions (e.g. us-central1)."
}

variable "auth_functions" {
  type = map(object({
    url  = string
    name = string
  }))
  description = "Map keyed realtor_signup|realtor_login|internal_signup|internal_login with function HTTPS URL and Cloud Run service name."
}

variable "backend_service_account_email" {
  type        = string
  description = "Auth backend SA email for API Gateway backend_config (signs requests to Cloud Run)."
}

variable "backend_service_account_name" {
  type        = string
  description = "Fully qualified SA resource name for IAM bindings (e.g. projects/.../serviceAccounts/...)."
}
