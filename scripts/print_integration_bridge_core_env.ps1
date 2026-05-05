# Print tfvars-style lines for core-run integration bridge wiring.
# Run from backend/:  pwsh -File scripts/print_integration_bridge_core_env.ps1
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

$gw = terraform output -raw integration_gateway_hostname 2>$null
$cf = terraform output -raw integration_bridge_function_url 2>$null
$base = terraform output -raw integration_internal_base_url 2>$null

Write-Host "# --- Paste into root terraform.tfvars (or HCP variables) ---"
Write-Host "integration_internal_gateway_hostname = `"$gw`""
Write-Host "fub_webhook_sync_worker_url           = `"$cf`""
Write-Host "# --- Effective core-run env (Terraform sets these on apply) ---"
if ($base) { Write-Host "# INTEGRATION_BRIDGE_BASE_URL=$base" }
else { Write-Host "# INTEGRATION_BRIDGE_BASE_URL=https://$gw" }
Write-Host "# INTEGRATION_BRIDGE_OIDC_AUDIENCE=$cf"
Write-Host "# --- Cross-check: gcloud api-gateway gateways list ---"
if (Get-Command gcloud -ErrorAction SilentlyContinue) {
  $proj = $env:GOOGLE_CLOUD_PROJECT
  if (-not $proj) { $proj = (gcloud config get-value project 2>$null) }
  if ($proj) {
    gcloud api-gateway gateways list --project=$proj --format="table(name,defaultHostname,state)" 2>$null
  }
}
