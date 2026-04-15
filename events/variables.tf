variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "platform_sa_email" {
  type        = string
  description = "ACS platform service account (Cloud Functions + Pub/Sub publisher)."
}

variable "events_internal_gateway_hostname" {
  type        = string
  default     = ""
  description = "Hostname only for acs-events-internal (OIDC audience https://HOST). Empty until wired from root tfvars."
}
