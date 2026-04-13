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
  type = string
}

variable "core_internal_gateway_hostname" {
  type = string
}

variable "fub_oauth_authorize_url" {
  type    = string
  default = ""
}

variable "fub_oauth_token_url" {
  type    = string
  default = ""
}

variable "fub_oauth_client_id" {
  type    = string
  default = ""
}

variable "fub_oauth_client_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "fub_system_name" {
  type    = string
  default = "ACS"
}

variable "fub_x_system_key" {
  type      = string
  sensitive = true
  default   = ""
}

variable "acs_public_integration_base_url" {
  type    = string
  default = ""
}

variable "acs_oauth_state_secret" {
  type      = string
  sensitive = true
  default   = ""
}

variable "acs_callback_bridge_secret" {
  type        = string
  sensitive   = true
  default     = ""
  description = "Must match api module callback bridge; required when enforcing bridge token on oauth/callback."
}

variable "integration_oauth_browser_cors_origins" {
  type        = list(string)
  default     = ["https://oauth.automatedconsultancy.com"]
  description = "Origins allowed to call GET/OPTIONS oauth/start from a browser (public gateway CORS). Override or set [] to disable."
}

variable "secrets_internal_gateway_hostname" {
  type        = string
  description = "Internal secrets API Gateway hostname (no scheme) for tenant secret reads/writes via secrets-bridge."
}
