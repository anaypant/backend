"""DB internal API via platform OIDC + acting uid."""

from __future__ import annotations

import os

from clients import gcp_identity
from clients.http_exec import post_json_platform_acting


def db_origin() -> str:
    host = gcp_identity.normalize_internal_gateway_hostname(os.environ.get("DB_INTERNAL_GATEWAY_HOSTNAME") or "")
    if not host:
        raise RuntimeError("DB_INTERNAL_GATEWAY_HOSTNAME is not set")
    return f"https://{host}"


def upsert_merge(path: str, data: dict, *, acting_uid: str, timeout: int = 60) -> tuple[dict, int]:
    token = gcp_identity.id_token_for_db_gateway()
    url = db_origin().rstrip("/") + "/db/upsert/"
    return post_json_platform_acting(
        url,
        {"path": path, "data": data, "merge": True},
        acting_uid=acting_uid,
        bearer=token,
        timeout=timeout,
    )


def read_document(path: str, *, acting_uid: str, timeout: int = 60) -> tuple[dict, int]:
    token = gcp_identity.id_token_for_db_gateway()
    url = db_origin().rstrip("/") + "/db/read/"
    return post_json_platform_acting(
        url,
        {"path": path},
        acting_uid=acting_uid,
        bearer=token,
        timeout=timeout,
    )


def query_collection(
    path: str,
    filters: list,
    *,
    acting_uid: str,
    limit: int = 25,
    timeout: int = 60,
) -> tuple[dict, int]:
    token = gcp_identity.id_token_for_db_gateway()
    url = db_origin().rstrip("/") + "/db/query/"
    payload: dict = {"path": path, "filters": filters, "limit": limit}
    return post_json_platform_acting(
        url,
        payload,
        acting_uid=acting_uid,
        bearer=token,
        timeout=timeout,
    )
