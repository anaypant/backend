variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "platform_sa_email" {
  type        = string
  description = "ACS platform SA — gateway backend + function runtime (same as db/auth)."
}

variable "db_internal_gateway_hostname" {
  type        = string
  description = "Internal DB API Gateway hostname (no scheme)."
}

variable "llm_internal_gateway_hostname" {
  type        = string
  description = "Internal LLM API Gateway hostname (no scheme)."
}

variable "llm_internal_jwt_audience" {
  type        = string
  description = "OIDC audience for calling llm-complete (Cloud Function URL, no trailing slash)."
}

variable "secrets_internal_gateway_hostname" {
  type        = string
  default     = ""
  description = "Internal secrets API Gateway hostname (no scheme)."
}

variable "secrets_internal_jwt_audience" {
  type        = string
  default     = ""
  description = "OIDC audience for secrets-bridge (Cloud Function URL)."
}
