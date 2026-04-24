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

variable "core_internal_gateway_hostname" {
  type        = string
  default     = ""
  description = "This service's own API gateway hostname (acs-core-internal, no scheme); used for in-handler OIDC verification. Bootstrap: leave empty on first deploy; set after gateway is created and redeploy."
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

variable "fub_webhook_sync_worker_url" {
  type        = string
  default     = ""
  description = "integration-bridge HTTPS origin (no trailing slash) → core-run INTEGRATION_BRIDGE_BASE_URL. Optional unless a core workflow calls integration (e.g. migration.from_providers, sync outbound). FUB webhooks hydrate CRM payloads in integration before invoking core."
}

variable "enable_core_dev_lab" {
  type        = bool
  default     = false
  description = "Sets ACS_ENABLE_DEV_LAB=1 on core-run for catalog + run_tool JSON API (see dev_lab_http.py)."
}
