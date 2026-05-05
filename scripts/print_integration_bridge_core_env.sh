#!/usr/bin/env bash
# Print tfvars-style lines for core-run integration bridge wiring.
# Run from backend/ after: terraform apply (integration + core modules deployed).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

GW="$(terraform output -raw integration_gateway_hostname 2>/dev/null || true)"
CF="$(terraform output -raw integration_bridge_function_url 2>/dev/null || true)"
BASE="$(terraform output -raw integration_internal_base_url 2>/dev/null || true)"

echo "# --- Paste into root terraform.tfvars (or HCP variables) ---"
echo "integration_internal_gateway_hostname = \"${GW}\""
echo "fub_webhook_sync_worker_url           = \"${CF}\""
echo "# --- Effective core-run env (Terraform sets these on apply) ---"
echo "# INTEGRATION_BRIDGE_BASE_URL=${BASE:-https://${GW}}"
echo "# INTEGRATION_BRIDGE_OIDC_AUDIENCE=${CF}"
echo "# --- Cross-check (optional): API Gateway hostnames in this project ---"
if command -v gcloud >/dev/null 2>&1; then
  PROJ="${GOOGLE_CLOUD_PROJECT:-$(gcloud config get-value project 2>/dev/null)}"
  if [[ -n "${PROJ}" ]]; then
    gcloud api-gateway gateways list --project="${PROJ}" --format='table(name,defaultHostname,state)' 2>/dev/null || true
  fi
else
  echo "# (install gcloud to list gateways; terraform output is authoritative)"
fi
