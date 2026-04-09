output "public_gateway_base_url" {
  description = "Public ACS API Gateway origin — set acs_public_integration_base_url and frontend NEXT_PUBLIC_API_BASE_URL to this (no trailing slash)."
  value       = module.api.public_gateway_base_url
}
