variable "project_id" {
  type        = string
  description = "GCP project ID (from root locals.project_id)."
}

variable "region" {
  type        = string
  description = "Primary region for regional API resources (from root var.region)."
}

variable "db_internal_gateway_hostname" {
  type        = string
  description = "Hostname of the internal DB API Gateway (module.db), without https:// — used to proxy /db/* on the public gateway."
}

variable "auth_internal_gateway_hostname" {
  type        = string
  description = "Hostname of the internal Auth API Gateway (module.auth), without https:// — used to proxy /auth/* on the public gateway."
}

variable "integration_internal_gateway_hostname" {
  type        = string
  description = "Hostname of the internal Integration API Gateway without https:// — used to proxy /integrations/* on the public gateway."
}

variable "platform_service_account_email" {
  type        = string
  description = "Root google_service_account.platform.email — ESP backend identity for the public gateway."
}

# Must match output public_gateway_base_url (enforced on google_api_gateway_gateway.public). Empty skips check.
variable "acs_public_integration_base_url" {
  type        = string
  default     = ""
  description = "Expected public origin for /integrations/* (https://…, no trailing slash). Empty = do not validate (integration fn may infer host from requests)."
}
