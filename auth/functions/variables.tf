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
  type = string
}

variable "backend_service_account_email" {
  type = string
}
