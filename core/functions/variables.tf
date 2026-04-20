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
  description = "integration-bridge base URL for core-run internal FUB calls (optional)."
}
