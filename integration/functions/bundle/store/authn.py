import firebase_admin
from firebase_admin import auth

import acs_internal as acs


def ensure_firebase():
    if not firebase_admin._apps:
        firebase_admin.initialize_app()


def _bearer_from_header_value(raw: str) -> str | None:
    parts = (raw or "").split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        t = parts[1].strip()
        return t or None
    return None


def _unique_bearer_tokens(request) -> list[str]:
    """Ordered Bearer values from headers that may carry the client JWT through API Gateway hops."""
    out: list[str] = []
    seen: set[str] = set()
    for h in (acs.USER_JWT_HEADER, "X-Forwarded-Authorization", "Authorization"):
        t = _bearer_from_header_value(request.headers.get(h) or "")
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def verify_realtor(id_token: str) -> tuple[dict | None, str | None]:
    ensure_firebase()
    try:
        decoded = auth.verify_id_token(id_token, check_revoked=True)
    except auth.InvalidIdTokenError:
        return None, "invalid token"
    except auth.ExpiredIdTokenError:
        return None, "token expired"
    except auth.RevokedIdTokenError:
        return None, "token revoked"
    if decoded.get("role") != "realtor":
        return None, "forbidden"
    return decoded, None


def resolve_realtor_bearer(request) -> tuple[dict | None, str | None, str | None]:
    """
    Resolve and verify the realtor Firebase ID token.

    Public ESP → internal ESP → Cloud Run can leave Google OIDC in Authorization and
    X-Forwarded-Authorization; try each distinct Bearer until verify_realtor succeeds.

    Returns (decoded_claims, error, id_token) — id_token is set only on success.
    """
    tokens = _unique_bearer_tokens(request)
    if not tokens:
        return None, "missing bearer token", None
    last_invalid: str | None = None
    for token in tokens:
        decoded, err = verify_realtor(token)
        if decoded is not None:
            return decoded, None, token
        if err in ("forbidden", "token expired", "token revoked"):
            return None, err, None
        last_invalid = err
    return None, last_invalid or "invalid token", None
