variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "dev_project_id" {
  type = string
}

variable "staging_project_id" {
  type = string
}

variable "prod_project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "firebase_web_api_key" {
  type        = string
  sensitive   = true
  description = "Firebase Web API key for Identity Toolkit REST (auth Cloud Functions)."
}

variable "google_oauth_client_id" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Optional. Web client ID for Terraform-managed Google IdP on Identity Platform."
}

variable "google_oauth_client_secret" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Optional. OAuth client secret for Google IdP (pair with google_oauth_client_id)."
}
