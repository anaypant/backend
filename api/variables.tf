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
