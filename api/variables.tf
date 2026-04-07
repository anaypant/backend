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
