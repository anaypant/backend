"""Secrets OIDC requires SECRETS_INTERNAL_JWT_AUDIENCE — no hostname fallback."""

import pytest

from store import gcp_identity


def test_id_token_for_secrets_gateway_errors_without_jwt_audience(monkeypatch):
    monkeypatch.delenv("SECRETS_INTERNAL_JWT_AUDIENCE", raising=False)
    monkeypatch.setenv(
        "SECRETS_INTERNAL_GATEWAY_HOSTNAME",
        "acs-secrets-internal-9l1ydz27.uc.gateway.dev",
    )
    with pytest.raises(gcp_identity.SecretsOidcConfigError) as exc_info:
        gcp_identity.id_token_for_secrets_gateway()
    assert exc_info.value.http_status == 503
    assert exc_info.value.payload["error"] == "secrets_oidc_audience_not_configured"
    assert exc_info.value.payload["phase"] == "secrets_platform_oidc"
    assert exc_info.value.payload.get("secretsInternalGatewayHostname")
