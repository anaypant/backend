"""store.authn — bearer extraction (ESP vs direct Run)."""

from store.authn import bearer_token


class _Req:
    def __init__(self, headers: dict[str, str]):
        self.headers = headers


def test_bearer_prefers_x_forwarded_over_authorization():
    """ESP sets Authorization to Google OIDC; original Firebase Bearer is in X-Forwarded-Authorization."""
    req = _Req(
        {
            "X-Forwarded-Authorization": "Bearer firebase-token",
            "Authorization": "Bearer google-oidc-token",
        }
    )
    assert bearer_token(req) == "firebase-token"


def test_bearer_falls_back_to_authorization():
    req = _Req({"Authorization": "Bearer direct-only"})
    assert bearer_token(req) == "direct-only"
