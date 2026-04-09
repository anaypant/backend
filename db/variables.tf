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
  type        = string
  default     = ""
  description = "acs-db-internal gateway hostname (no scheme). Set after first apply from output db_gateway_hostname to enable platform SA + X-ACS-Acting-Uid on read/upsert."
}
