variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "backend_service_account_email" {
  type = string
}

variable "secrets_internal_gateway_hostname" {
  type    = string
  default = ""
}

variable "secrets_internal_jwt_audience" {
  type    = string
  default = ""
}

variable "openrouter_api_key" {
  type      = string
  sensitive = true
  default   = ""
}
