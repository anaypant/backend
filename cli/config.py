"""
Session file management and token refresh for the ACS CLI.

Session is stored at ~/.acs-cli/session.json:
  {
    "base_url": "https://...",
    "id_token": "...",
    "refresh_token": "...",
    "expires_at": 1746000000,   # epoch seconds
    "firebase_api_key": "..."
  }
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

import requests

_SESSION_DIR = Path.home() / ".acs-cli"
_SESSION_FILE = _SESSION_DIR / "session.json"

# Refresh the token when it expires within this many seconds.
_REFRESH_BUFFER_SECS = 60


# ---------------------------------------------------------------------------
# Session file helpers
# ---------------------------------------------------------------------------

def _load() -> dict:
    if not _SESSION_FILE.exists():
        return {}
    try:
        return json.loads(_SESSION_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    _SESSION_DIR.mkdir(parents=True, exist_ok=True)
    _SESSION_FILE.write_text(json.dumps(data, indent=2))


def clear() -> None:
    """Remove the session file (logout)."""
    if _SESSION_FILE.exists():
        _SESSION_FILE.unlink()


def get_session() -> dict:
    """Return the current session dict (may be empty if not logged in)."""
    return _load()


def save_session(
    *,
    base_url: str,
    id_token: str,
    refresh_token: str,
    expires_in: int,
    firebase_api_key: str,
) -> None:
    """Persist a new session after login."""
    _save(
        {
            "base_url": base_url.rstrip("/"),
            "id_token": id_token,
            "refresh_token": refresh_token,
            "expires_at": int(time.time()) + int(expires_in),
            "firebase_api_key": firebase_api_key,
        }
    )


# ---------------------------------------------------------------------------
# Token access + silent refresh
# ---------------------------------------------------------------------------

class NotLoggedIn(RuntimeError):
    pass


def _refresh(session: dict) -> dict:
    """
    Exchange refresh_token for a new id_token via Firebase securetoken API.
    Returns the updated session dict (also persisted to disk).
    """
    api_key = session.get("firebase_api_key", "")
    if not api_key:
        raise NotLoggedIn(
            "No firebase_api_key in session — re-run `acs auth login --firebase-api-key KEY`."
        )
    url = f"https://securetoken.googleapis.com/v1/token?key={api_key}"
    resp = requests.post(
        url,
        json={"grant_type": "refresh_token", "refresh_token": session["refresh_token"]},
        timeout=15,
    )
    if not resp.ok:
        raise NotLoggedIn(
            f"Token refresh failed (HTTP {resp.status_code}): {resp.text[:200]}"
        )
    data = resp.json()
    updated = {
        **session,
        "id_token": data["id_token"],
        "refresh_token": data.get("refresh_token", session["refresh_token"]),
        "expires_at": int(time.time()) + int(data.get("expires_in", 3600)),
    }
    _save(updated)
    return updated


def get_token() -> str:
    """
    Return a valid Firebase ID token, refreshing silently if needed.
    Raises NotLoggedIn if no session exists.
    """
    session = _load()
    if not session.get("id_token"):
        raise NotLoggedIn("Not logged in. Run `acs auth login` first.")

    expires_at = session.get("expires_at", 0)
    if time.time() >= expires_at - _REFRESH_BUFFER_SECS:
        if not session.get("refresh_token"):
            raise NotLoggedIn("Token expired and no refresh_token stored. Run `acs auth login` again.")
        session = _refresh(session)

    return session["id_token"]


def get_base_url(override: Optional[str] = None) -> str:
    """Return base URL from override > session > ACS_API_URL env var."""
    if override:
        return override.rstrip("/")
    session = _load()
    if session.get("base_url"):
        return session["base_url"].rstrip("/")
    env = os.environ.get("ACS_API_URL", "").strip()
    if env:
        return env.rstrip("/")
    raise NotLoggedIn(
        "No base URL configured. Run `acs auth login --base-url URL` or set ACS_API_URL."
    )


def get_firebase_api_key(override: Optional[str] = None) -> str:
    """Return Firebase API key from override > session > FIREBASE_WEB_API_KEY env var."""
    if override:
        return override
    session = _load()
    if session.get("firebase_api_key"):
        return session["firebase_api_key"]
    env = os.environ.get("FIREBASE_WEB_API_KEY", "").strip()
    if env:
        return env
    return ""
