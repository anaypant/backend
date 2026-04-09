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

output "public_gateway_base_url" {
  description = "Canonical public API origin (scheme + default_hostname). Use for acs_public_integration_base_url and client NEXT_PUBLIC_API_BASE_URL."
  value       = "https://${google_api_gateway_gateway.public.default_hostname}"
}
