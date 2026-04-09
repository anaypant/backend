variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "core_run_function" {
  type = object({
    url  = string
    name = string
  })
}

variable "backend_service_account_email" {
  type = string
}
