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
  type        = string
  default     = ""
  description = "Hostname of the internal secrets API Gateway (no scheme). Sets ACS_SECRETS_GATEWAY_HOSTNAME so OIDC verification accepts tokens minted for https://{host}."
}
