variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "events_bridge_function" {
  type = object({
    url  = string
    name = string
  })
}

variable "backend_service_account_email" {
  type = string
}
