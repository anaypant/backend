variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be one of: dev, staging, prod."
  }
}

variable "dev_project_id" {
  type = string
}

variable "staging_project_id" {
  type = string
}

variable "prod_project_id" {
  type = string
}

variable "region" {
  type = string
}
