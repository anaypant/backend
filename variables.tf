variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "db_internal_gateway_hostname" {
  type        = string
  default     = ""
  description = "Internal DB API Gateway host or full https URL; root module normalizes to hostname. When non-empty, must match output db_gateway_hostname (check in db module). Leave empty to use module.db output for integration only."
}

variable "secrets_internal_gateway_hostname" {
  type        = string
  default     = ""
  description = "Internal secrets API Gateway hostname (no scheme). When non-empty, must match terraform output secrets_gateway_hostname (plan check in secrets module)."
}

variable "secrets_internal_jwt_audience_override" {
  type        = string
  default     = ""
  description = "Optional. When set, used as SECRETS_INTERNAL_JWT_AUDIENCE on integration-bridge instead of module.secrets output (paste from: terraform output -raw secrets_bridge_invoker_audience). Must match that URL after trim/lowercase; plan fails otherwise (check block secrets_internal_jwt_audience_matches_secrets_bridge)."
}

variable "dev_project_id" {
  type = string
}

variable "staging_project_id" {
  type = string
}

variable "prod_project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "firebase_web_api_key" {
  type        = string
  sensitive   = true
  description = "Firebase Web API key for Identity Toolkit REST (auth Cloud Functions)."
}

variable "google_oauth_client_id" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Optional. Web client ID for Terraform-managed Google IdP on Identity Platform."
}

variable "google_oauth_client_secret" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Optional. OAuth client secret for Google IdP (pair with google_oauth_client_id)."
}

variable "fub_oauth_authorize_url" {
  type        = string
  default     = ""
  description = "Follow Up Boss OAuth authorize URL; required to build oauth/start authorizeUrl."
}

variable "fub_oauth_token_url" {
  type        = string
  default     = ""
  description = "Follow Up Boss OAuth token URL for code exchange and refresh."
}

variable "fub_oauth_client_id" {
  type        = string
  default     = ""
  description = "Follow Up Boss OAuth client id."
}

variable "fub_oauth_client_secret" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Follow Up Boss OAuth client secret."
}

variable "fub_system_name" {
  type        = string
  default     = "ACS"
  description = "X-System header used for FUB webhook management APIs."
}

variable "fub_x_system_key" {
  type        = string
  sensitive   = true
  default     = ""
  description = "X-System-Key used for FUB webhook signature validation."
}

variable "acs_public_integration_base_url" {
  type        = string
  default     = ""
  description = "Must match output public_gateway_base_url (validated against the public API Gateway). Empty = skip validation; integration function may infer host from requests."
}

variable "acs_oauth_state_secret" {
  type        = string
  sensitive   = true
  default     = ""
  description = "HMAC secret used to sign OAuth state."
}

variable "acs_callback_bridge_secret" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Shared HS256 secret for public callback-bridge → integration (X-ACS-Callback-Bridge-Token). Empty disables enforcement in integration (dev)."
}

variable "integration_oauth_browser_cors_origins" {
  type        = list(string)
  default     = ["https://oauth.automatedconsultancy.com"]
  description = "Browser origins allowed CORS on public GET/OPTIONS /integrations/followupboss/oauth/start. Set [] to disable; add http://localhost:3000 for local OAuth UI."
}
