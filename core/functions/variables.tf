variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "backend_service_account_email" {
  type        = string
  description = "SA used as API Gateway backend identity and Cloud Run runtime (matches platform SA)."
}
