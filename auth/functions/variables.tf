variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "firebase_web_api_key" {
  type      = string
  sensitive = true
}

variable "db_internal_gateway_hostname" {
  type        = string
  description = "Hostname only (no https://) for internal DB API Gateway."
}

variable "backend_service_account_email" {
  type = string
}
