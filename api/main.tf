# Client-facing API: managed API Gateway behind a global external HTTP(S) LB + Cloud Armor.
# Platform SA + IAM live in root platform.tf; gateway_config uses var.platform_service_account_email.

terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = ">= 5.0"
    }
  }
}

output "id" {
  value = "api"
}
