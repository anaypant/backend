variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "backend_service_account_email" {
  type = string
}

variable "pubsub_topic_id" {
  type        = string
  description = "Full Pub/Sub topic id (projects/.../topics/acs-domain-events)."
}

variable "events_internal_gateway_hostname" {
  type        = string
  default     = ""
  description = "Hostname for OIDC audience (https://HOST); optional on first deploy."
}
