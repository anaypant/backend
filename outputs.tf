output "public_gateway_base_url" {
  description = "Public ACS API Gateway origin — set acs_public_integration_base_url and frontend NEXT_PUBLIC_API_BASE_URL to this (no trailing slash)."
  value       = module.api.public_gateway_base_url
}

output "db_gateway_hostname" {
  description = "Internal DB API Gateway hostname (no scheme). Set root variable db_internal_gateway_hostname to this after first deploy to enable platform DB calls from integration."
  value       = module.db.db_gateway_hostname
}

output "db_gateway_audience" {
  description = "OIDC audience (https://...) for platform identity tokens targeting the internal DB gateway."
  value       = module.db.db_gateway_audience
}

output "secrets_gateway_hostname" {
  description = "Internal secrets API Gateway hostname (no scheme). Set secrets_internal_gateway_hostname to this after first deploy for drift checks."
  value       = module.secrets.secrets_gateway_hostname
}

output "secrets_gateway_audience" {
  description = "OIDC audience for platform calls to the internal secrets gateway."
  value       = module.secrets.secrets_gateway_audience
}
