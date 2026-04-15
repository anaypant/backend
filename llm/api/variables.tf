variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "llm_complete_function" {
  type = object({
    url  = string
    name = string
  })
}

variable "backend_service_account_email" {
  type = string
}
