variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "platform_sa_email" {
  type        = string
  description = "ACS platform SA — Gen2 execution identity + API Gateway backend_config."
}

variable "secrets_internal_gateway_hostname" {
  type        = string
  default     = ""
  description = "When non-empty, must equal deployed secrets internal gateway hostname (OIDC audience check on function)."
}
