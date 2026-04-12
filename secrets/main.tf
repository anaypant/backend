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

module "functions" {
  source                        = "./functions"
  project_id                  = var.project_id
  region                      = var.region
  backend_service_account_email = var.platform_sa_email
}

module "api" {
  source = "./api"
  providers = {
    google      = google
    google-beta = google-beta
  }
  project_id                    = var.project_id
  region                        = var.region
  bridge_function               = module.functions.bridge_function
  backend_service_account_email = var.platform_sa_email
  depends_on                    = [module.functions]
}

check "secrets_internal_gateway_hostname_matches_deployed" {
  assert {
    condition = (
      var.secrets_internal_gateway_hostname == "" ||
      lower(trim(var.secrets_internal_gateway_hostname, "/")) == lower(trim(module.api.gateway_hostname, "/"))
    )
    error_message = <<-EOT
      secrets_internal_gateway_hostname must equal the deployed internal secrets gateway hostname (no scheme).
      Run: terraform output secrets_gateway_hostname
      Set the root variable to that exact value, or leave empty until wiring platform callers.
      Deployed gateway hostname: ${module.api.gateway_hostname}
    EOT
  }
}

output "secrets_gateway_hostname" {
  description = "Internal secrets API Gateway hostname (no scheme)."
  value       = nonsensitive(module.api.gateway_hostname)
}

output "secrets_gateway_audience" {
  description = "Google ID token audience for calls to the internal secrets gateway."
  value       = nonsensitive(module.api.gateway_audience)
}

output "secrets_gateway_id" {
  description = "Fixed API Gateway id for secrets internal API."
  value       = module.api.gateway_id
}
