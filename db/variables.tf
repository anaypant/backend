variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "platform_sa_email" {
  type = string
}

variable "db_internal_gateway_hostname" {
  type        = string
  default     = ""
  description = "Internal DB gateway hostname (no scheme). When non-empty, must equal output db_gateway_hostname (plan check). OIDC audience is https://HOST."
}
