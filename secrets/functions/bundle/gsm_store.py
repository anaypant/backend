"""Google Secret Manager — tenant secrets under deterministic ids."""

from __future__ import annotations

import os

from google.api_core import exceptions as gcp_exceptions
from google.cloud import secretmanager


def _project() -> str:
    return (os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()


def write_version(secret_id: str, value: str) -> str:
    project = _project()
    if not project:
        raise RuntimeError("GCP project not set")
    client = secretmanager.SecretManagerServiceClient()
    parent = f"projects/{project}"
    name = f"{parent}/secrets/{secret_id}"
    try:
        client.get_secret(request={"name": name})
    except gcp_exceptions.NotFound:
        client.create_secret(
            request={
                "parent": parent,
                "secret_id": secret_id,
                "secret": {"replication": {"automatic": {}}},
            }
        )
    client.add_secret_version(request={"parent": name, "payload": {"data": value.encode("utf-8")}})
    return name


def read_latest(secret_id: str) -> str | None:
    project = _project()
    if not project:
        return None
    client = secretmanager.SecretManagerServiceClient()
    path = f"projects/{project}/secrets/{secret_id}/versions/latest"
    try:
        resp = client.access_secret_version(request={"name": path})
        return resp.payload.data.decode("utf-8")
    except gcp_exceptions.NotFound:
        return None


def delete_secret(secret_id: str) -> bool:
    project = _project()
    if not project:
        return False
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project}/secrets/{secret_id}"
    try:
        client.delete_secret(request={"name": name})
        return True
    except gcp_exceptions.NotFound:
        return False
