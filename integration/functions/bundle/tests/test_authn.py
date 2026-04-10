"""store.authn — multi-header Bearer resolution through API Gateway hops."""

from unittest.mock import patch

from store.authn import _unique_bearer_tokens, resolve_realtor_bearer


class _Req:
    def __init__(self, headers: dict[str, str]):
        self.headers = headers


def test_unique_bearer_tokens_order_and_dedupe():
    req = _Req(
        {
            "X-Firebase-Authorization": "Bearer a",
            "X-Forwarded-Authorization": "Bearer b",
            "Authorization": "Bearer a",
        }
    )
    assert _unique_bearer_tokens(req) == ["a", "b"]


def test_resolve_skips_oidc_like_first_token():
    req = _Req(
        {
            "X-Forwarded-Authorization": "Bearer oidc-from-hop-one",
            "Authorization": "Bearer firebase-id-token",
        }
    )

    def fake_verify(token: str):
        if token == "oidc-from-hop-one":
            return None, "invalid token"
        if token == "firebase-id-token":
            return {"uid": "u1", "role": "realtor"}, None
        return None, "invalid token"

    with patch("store.authn.verify_realtor", side_effect=fake_verify):
        decoded, err, used = resolve_realtor_bearer(req)
    assert err is None
    assert decoded == {"uid": "u1", "role": "realtor"}
    assert used == "firebase-id-token"


def test_resolve_forbidden_short_circuits():
    req = _Req({"Authorization": "Bearer t"})

    with patch("store.authn.verify_realtor", return_value=(None, "forbidden")):
        decoded, err, used = resolve_realtor_bearer(req)
    assert decoded is None
    assert err == "forbidden"
    assert used is None
