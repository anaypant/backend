variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "backend_service_account_email" {
  type        = string
  description = "SA used as API Gateway backend identity and Cloud Run runtime (matches platform SA)."
}

variable "core_internal_gateway_hostname" {
  type        = string
  description = "Hostname of this service's own API gateway (acs-core-internal); used for in-handler OIDC audience verification."
}

variable "db_internal_gateway_hostname" {
  type = string
}

variable "llm_internal_gateway_hostname" {
  type = string
}

variable "llm_internal_jwt_audience" {
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

variable "fub_webhook_sync_worker_url" {
  type        = string
  default     = ""
  description = "integration-bridge Cloud Function URL for OIDC; optional INTEGRATION_BRIDGE_BASE_URL when integration_internal_gateway_hostname is empty."
}

variable "integration_internal_gateway_hostname" {
  type        = string
  default     = ""
  description = "Internal integration API Gateway hostname (no scheme)."
}

variable "enable_core_dev_lab" {
  type        = bool
  default     = false
  description = "When true, sets ACS_ENABLE_DEV_LAB=1 on core-run."
}
