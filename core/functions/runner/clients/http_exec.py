from __future__ import annotations

import json
import urllib.error
import urllib.request


def post_json_with_bearer(url: str, payload: dict, *, bearer: str, timeout: int = 60) -> tuple[dict, int]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {bearer}",
        },
    )
    return _exec(req, timeout=timeout)


def post_json_platform_acting(
    url: str,
    payload: dict,
    *,
    acting_uid: str,
    bearer: str,
    timeout: int = 60,
) -> tuple[dict, int]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {bearer}",
            "X-ACS-Acting-Uid": acting_uid,
            "X-ACS-Platform-Authorization": f"Bearer {bearer}",
        },
    )
    return _exec(req, timeout=timeout)


def _exec(req: urllib.request.Request, *, timeout: int) -> tuple[dict, int]:
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            if not raw:
                return {}, resp.status
            try:
                return json.loads(raw), resp.status
            except json.JSONDecodeError:
                return {"raw": raw}, resp.status
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return json.loads(raw), e.code
        except json.JSONDecodeError:
            return {"error": raw or "upstream error"}, e.code
