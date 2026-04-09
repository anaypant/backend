import firebase_admin
from firebase_admin import auth

import acs_internal as acs


def ensure_firebase():
    if not firebase_admin._apps:
        firebase_admin.initialize_app()


def bearer_token(request) -> str | None:
    for h in (acs.USER_JWT_HEADER, "Authorization"):
        raw = request.headers.get(h) or ""
        parts = raw.split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1].strip()
            if token:
                return token
    return None


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
