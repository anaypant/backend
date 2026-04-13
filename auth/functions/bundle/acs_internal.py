"""Header names for auth → internal DB gateway calls."""

USER_AUTHORIZATION_HEADER = "X-ACS-User-Authorization"
USER_JWT_HEADER = USER_AUTHORIZATION_HEADER

# Google OIDC for Cloud Run / API Gateway invoker (not end-user auth).
GCP_INFRA_IDENTITY_HEADER = "X-GCP-Identity"
