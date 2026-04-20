# Note: These values are not used, instead the values need to be put into HCP Terraform workspace variables.

dev_project_id     = "acs-dev-ecb97"
staging_project_id = "NULL"
prod_project_id    = "dynamic-heading-492620-m0"

environment = "dev"
region      = "us-central1"

# After first apply: terraform output db_gateway_hostname — paste hostname or full https:// URL (normalized in main.tf).
db_internal_gateway_hostname = ""

# Firebase Console → Project settings → Your apps → Web API key (required for auth functions).
firebase_web_api_key = "NULL"

# -----------------------------------------------------------------------------
# LLM (module.llm → llm-complete Cloud Function env OPENROUTER_API_KEY).
# Set in HCP Terraform as a sensitive variable; leave empty locally to avoid committing secrets.
# -----------------------------------------------------------------------------
openrouter_api_key = ""

# Optional: set both to manage Google sign-in via Terraform; otherwise enable Google in Firebase Console.
google_oauth_client_id     = ""
google_oauth_client_secret = ""

# -----------------------------------------------------------------------------
# Follow Up Boss + integration bridge (module.integration → integration function env).
# Mirror these in HCP Terraform workspace variables; mark secrets as sensitive.
# -----------------------------------------------------------------------------

# FUB OAuth — from old-acs `nexus/config/oauth.py` (public FUB endpoints).
fub_oauth_authorize_url = "https://app.followupboss.com/oauth/authorize"
fub_oauth_token_url     = "https://app.followupboss.com/oauth/token"

# FUB OAuth app — from old-acs `backend/environments/dev/terraform.tfvars` (same FUB registration).
fub_oauth_client_id     = "6c5609333abf4da47803429eb33983699f39bd46350f1835ee324cd85fb2170f"
fub_oauth_client_secret = "3140050034a909822249032be525e5bb2e47b0ca4de0242cc7cf78e080fcf58f6ce8d69af0ecb68644c87dc8ed2ebb8c61ca05195ca1b3e0a9040a21eeeeb8a0272f6f3fae8b9d49c203ab059bd43849efea10e7087e3cd6c77ba401ffb9fc9bb11701be"

# X-System / X-System-Key — old-acs defaults (`list_fub_webhooks.py`, `create_fub_oauth_app.py`, CRM tools).
fub_system_name  = "acs-dev"
fub_x_system_key = "2b615f84728548771e7b4dd45277852e"

# After first apply: terraform output public_gateway_base_url — set this (and HCP) to that value exactly for zero drift (enforced on gateway).
acs_public_integration_base_url = ""

# If integration-bridge still cannot read acs-sec secrets (503 fub_credentials_unavailable), set this in HCP too:
#   terraform output -raw secrets_bridge_invoker_audience
# Paste the full https URL (no trailing slash). Leave empty to use the computed value from module.secrets.
# secrets_internal_jwt_audience_override = ""

#  generate (e.g. openssl rand -hex 32) and set in HCP as sensitive.
acs_oauth_state_secret = ""

# Same value in api + integration modules; openssl rand -hex 32. Empty = dev-only transparent OAuth callback proxy.
acs_callback_bridge_secret = ""
