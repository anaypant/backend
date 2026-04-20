import base64
import os
import urllib.parse

from store.common import delete_json, get_json, post_form, post_json
from store.secret_repo import get_secret


class FubClient:
    def __init__(
        self,
        *,
        access_token_ref: str | None = None,
        api_key_ref: str | None = None,
        acting_uid: str | None = None,
        access_token_plain: str | None = None,
    ):
        self.base = "https://api.followupboss.com/v1"
        self.access_token_ref = access_token_ref
        self.api_key_ref = api_key_ref
        self.acting_uid = acting_uid
        self.access_token_plain = (access_token_plain or "").strip() or None
        self.system_name = (os.environ.get("FUB_SYSTEM_NAME") or "ACS").strip()

    def _headers(self) -> dict:
        headers = {
            "Content-Type": "application/json",
            "X-System": self.system_name,
        }
        token = self.access_token_plain or get_secret(self.access_token_ref or "", acting_uid=self.acting_uid)
        if token:
            headers["Authorization"] = f"Bearer {token}"
            return headers

        # TODO: Remove API-key fallback if OAuth bearer proves sufficient for all endpoints.
        api_key = get_secret(self.api_key_ref or "", acting_uid=self.acting_uid)
        if api_key:
            basic = base64.b64encode(f"{api_key}:".encode("utf-8")).decode("utf-8")
            headers["Authorization"] = f"Basic {basic}"
        return headers

    def exchange_code(self, code: str, redirect_uri: str, state: str) -> tuple[dict, int]:
        token_url = (os.environ.get("FUB_OAUTH_TOKEN_URL") or "").strip()
        client_id = (os.environ.get("FUB_OAUTH_CLIENT_ID") or "").strip()
        client_secret = (os.environ.get("FUB_OAUTH_CLIENT_SECRET") or "").strip()
        if not token_url or not client_id or not client_secret:
            return {
                "error": "oauth_token_exchange_not_configured",
                "todo": "Set FUB_OAUTH_TOKEN_URL, FUB_OAUTH_CLIENT_ID, FUB_OAUTH_CLIENT_SECRET",
            }, 501
        if not (state or "").strip():
            return {"error": "oauth_token_exchange_missing_state", "todo": "FUB token exchange requires state in form body"}, 400
        # FUB token endpoint: Basic Authorization (client_id:client_secret) plus grant params including state.
        # https://docs.followupboss.com/guides/oauth#step-3-exchanging-auth_code-for-tokens
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
        return post_form(
            token_url,
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "state": state.strip(),
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

    def list_people(
        self,
        *,
        limit: int = 100,
        offset: int | None = None,
        next_token: str | None = None,
    ) -> tuple[dict, int]:
        """
        GET /v1/people — paginated. Prefer ``next_token`` from ``_metadata.next`` when present.

        https://docs.followupboss.com/reference/people-get
        """
        lim = max(1, min(100, int(limit)))
        params: dict[str, str] = {"limit": str(lim)}
        if next_token and str(next_token).strip():
            params["next"] = str(next_token).strip()
        elif offset is not None:
            params["offset"] = str(max(0, int(offset)))
        q = urllib.parse.urlencode(params)
        return get_json(f"{self.base}/people?{q}", headers=self._headers(), timeout=90)

    def create_note(self, person_id: int, body: str) -> tuple[dict, int]:
        return post_json(f"{self.base}/notes", {"personId": person_id, "body": body}, headers=self._headers())

    def create_task(self, person_id: int, body: str) -> tuple[dict, int]:
        return post_json(f"{self.base}/tasks", {"personId": person_id, "body": body}, headers=self._headers())

    def upsert_person(self, payload: dict) -> tuple[dict, int]:
        return post_json(f"{self.base}/people", payload, headers=self._headers())
