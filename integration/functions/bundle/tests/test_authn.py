"""store.authn — gateway claims vs Bearer fallback."""

from unittest.mock import patch

from store.authn import resolve_realtor_bearer


class _Req:
    def __init__(self, headers: dict[str, str]):
        self.headers = headers


def test_gateway_user_info_realtor_ok():
    import base64
    import json

    payload = {"user_id": "u1", "role": "realtor"}
    b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    req = _Req({"X-Endpoint-API-UserInfo": b64})
    d, err, tok = resolve_realtor_bearer(req)
    assert err is None and tok is None and d["uid"] == "u1"


def test_gateway_user_info_forbidden():
    import base64
    import json

    payload = {"user_id": "u1", "role": "internal"}
    b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    req = _Req({"X-Endpoint-API-UserInfo": b64})
    d, err, tok = resolve_realtor_bearer(req)
    assert d is None and err == "forbidden" and tok is None


def test_fallback_authorization_first_then_legacy_user_header():
    req = _Req(
        {
            "X-ACS-User-Authorization": "Bearer firebase-token",
            "Authorization": "Bearer google-oidc",
        }
    )

    def fake_verify(token: str):
        if token == "firebase-token":
            return {"uid": "u1", "role": "realtor"}, None
        return None, "invalid token"

    with patch("store.authn.verify_realtor", side_effect=fake_verify):
        d, err, tok = resolve_realtor_bearer(req)
    assert err is None and d["uid"] == "u1" and tok == "firebase-token"


def test_fallback_authorization_only_browser():
    req = _Req({"Authorization": "Bearer firebase-only"})

    def fake_verify(token: str):
        if token == "firebase-only":
            return {"uid": "u1", "role": "realtor"}, None
        return None, "invalid token"

    with patch("store.authn.verify_realtor", side_effect=fake_verify):
        d, err, tok = resolve_realtor_bearer(req)
    assert err is None and d["uid"] == "u1" and tok == "firebase-only"
