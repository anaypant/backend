variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "backend_service_account_email" {
  type = string
}

variable "db_internal_gateway_hostname" {
  type        = string
  description = "Hostname only (no scheme) for acs-db-internal gateway."
}

variable "core_internal_gateway_hostname" {
  type        = string
  description = "Hostname only (no scheme) for acs-core-internal gateway."
}

variable "fub_oauth_authorize_url" {
  type        = string
  description = "Follow Up Boss OAuth authorization URL (if OAuth flow is enabled)."
  default     = ""
}

variable "fub_oauth_token_url" {
  type        = string
  description = "Follow Up Boss OAuth token URL."
  default     = ""
}

variable "fub_oauth_client_id" {
  type        = string
  description = "Follow Up Boss OAuth client id."
  default     = ""
}

variable "fub_oauth_client_secret" {
  type        = string
  sensitive   = true
  description = "Follow Up Boss OAuth client secret."
  default     = ""
}

variable "fub_system_name" {
  type        = string
  description = "X-System header value for Follow Up Boss webhook management APIs."
  default     = "ACS"
}

variable "fub_x_system_key" {
  type        = string
  sensitive   = true
  description = "X-System-Key used to verify FUB webhook signatures."
  default     = ""
}

variable "acs_public_integration_base_url" {
  type        = string
  description = "Deterministic public base URL used to construct integration callback URLs."
  default     = ""
}

variable "acs_oauth_state_secret" {
  type        = string
  sensitive   = true
  description = "HMAC secret used to sign oauth state."
  default     = ""
}

variable "acs_callback_bridge_secret" {
  type        = string
  sensitive   = true
  description = "HS256 secret for verifying X-ACS-Callback-Bridge-Token on oauth/callback."
  default     = ""
}

variable "browser_cors_origins" {
  type        = string
  default     = ""
  description = "Comma-separated origins for browser CORS on GET/OPTIONS /integrations/followupboss/oauth/start (ACS_BROWSER_CORS_ORIGINS)."
}

variable "secrets_internal_gateway_hostname" {
  type        = string
  description = "Internal secrets API Gateway hostname (no scheme); SECRETS_INTERNAL_GATEWAY_HOSTNAME on the bridge."
}

variable "secrets_internal_jwt_audience" {
  type        = string
  description = "OIDC audience for secrets internal API (secrets-bridge URL); SECRETS_INTERNAL_JWT_AUDIENCE on the bridge."
}

variable "fub_webhook_sync_worker_url" {
  type        = string
  default     = ""
  description = <<-EOT
    HTTPS origin of integration-bridge (Cloud Run / Functions Gen2 URL), no trailing slash.
    Required for deferred FUB webhook registration via Cloud Tasks. Use module output bridge_function.url
    after the first deploy, then set this and re-apply. Leave empty to run webhook sync inline during OAuth.
  EOT
}

variable "events_internal_gateway_hostname" {
  type        = string
  description = "acs-events-internal gateway hostname (no scheme); EVENTS_INTERNAL_GATEWAY_HOSTNAME on integration-bridge."
}
