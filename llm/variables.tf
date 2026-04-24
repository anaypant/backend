variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "platform_sa_email" {
  type        = string
  description = "ACS platform SA — gateway backend + function runtime."
}

variable "llm_internal_jwt_audience" {
  type        = string
  default     = ""
  description = "OIDC audience for this service (= LLM Cloud Function URL). Used for in-handler OIDC verification. Bootstrap: leave empty on first deploy; set to llm_function_url output and redeploy."
}

variable "secrets_internal_gateway_hostname" {
  type        = string
  default     = ""
  description = "Internal secrets API Gateway hostname (no scheme)."
}

variable "secrets_internal_jwt_audience" {
  type        = string
  default     = ""
  description = "OIDC audience for secrets-bridge (Cloud Function URL, no trailing slash)."
}

variable "openrouter_api_key" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Optional. OpenRouter API key; when empty, openrouter provider returns an error unless request uses echo provider."
}
