variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "platform_sa_email" {
  type        = string
  description = "ACS platform SA — gateway backend + function runtime (same as db/auth)."
}
