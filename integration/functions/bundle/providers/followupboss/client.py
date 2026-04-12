import base64
import os

from store.common import delete_json, get_json, post_form, post_json
from store.secret_repo import get_secret


class FubClient:
    def __init__(self, *, access_token_ref: str | None = None, api_key_ref: str | None = None):
        self.base = "https://api.followupboss.com/v1"
        self.access_token_ref = access_token_ref
        self.api_key_ref = api_key_ref
        self.system_name = (os.environ.get("FUB_SYSTEM_NAME") or "ACS").strip()

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "X-System": self.system_name,
        }
        token = get_secret(self.access_token_ref or "")
        if token:
            headers["Authorization"] = f"Bearer {token}"
            return headers

        # TODO: Remove API-key fallback if OAuth bearer proves sufficient for all endpoints.
        api_key = get_secret(self.api_key_ref or "")
        if api_key:
            basic = base64.b64encode(f"{api_key}:".encode("utf-8")).decode("utf-8")
            headers["Authorization"] = f"Basic {basic}"
        return headers

    def exchange_code(self, code: str, redirect_uri: str) -> tuple[dict, int]:
        token_url = (os.environ.get("FUB_OAUTH_TOKEN_URL") or "").strip()
        client_id = (os.environ.get("FUB_OAUTH_CLIENT_ID") or "").strip()
        client_secret = (os.environ.get("FUB_OAUTH_CLIENT_SECRET") or "").strip()
        if not token_url or not client_id or not client_secret:
            return {
                "error": "oauth_token_exchange_not_configured",
                "todo": "Set FUB_OAUTH_TOKEN_URL, FUB_OAUTH_CLIENT_ID, FUB_OAUTH_CLIENT_SECRET",
            }, 501
        # FUB token endpoint requires Basic Authorization (client_id:client_secret), not body secrets alone.
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
        return post_form(
            token_url,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {basic}",
            },
            timeout=30,
        )

    def refresh_token(self, refresh_token: str) -> tuple[dict, int]:
        token_url = (os.environ.get("FUB_OAUTH_TOKEN_URL") or "").strip()
        client_id = (os.environ.get("FUB_OAUTH_CLIENT_ID") or "").strip()
        client_secret = (os.environ.get("FUB_OAUTH_CLIENT_SECRET") or "").strip()
        if not token_url or not client_id or not client_secret:
            return {"error": "oauth_refresh_not_configured"}, 501
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
        return post_form(
            token_url,
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            },
            headers={
                "Accept": "application/json",
                "Authorization": f"Basic {basic}",
            },
            timeout=30,
        )

    def list_webhooks(self) -> tuple[dict, int]:
        return get_json(f"{self.base}/webhooks", headers=self._headers(), timeout=30)

    def create_webhook(self, event: str, url: str) -> tuple[dict, int]:
        return post_json(
            f"{self.base}/webhooks",
            {"event": event, "url": url},
            headers=self._headers(),
            timeout=30,
        )

    def delete_webhook(self, webhook_id: int | str) -> tuple[dict, int]:
        return delete_json(f"{self.base}/webhooks/{webhook_id}", headers=self._headers(), timeout=30)

    def get_by_uri(self, uri: str) -> tuple[dict, int]:
        return get_json(uri, headers=self._headers(), timeout=30)

    def create_note(self, person_id: int, body: str) -> tuple[dict, int]:
        return post_json(f"{self.base}/notes", {"personId": person_id, "body": body}, headers=self._headers())

    def create_task(self, person_id: int, body: str) -> tuple[dict, int]:
        return post_json(f"{self.base}/tasks", {"personId": person_id, "body": body}, headers=self._headers())

    def upsert_person(self, payload: dict) -> tuple[dict, int]:
        return post_json(f"{self.base}/people", payload, headers=self._headers())
