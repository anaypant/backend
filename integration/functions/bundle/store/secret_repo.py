import os
from typing import Any

from google.cloud import secretmanager

from store.authn import ensure_firebase


def _sm_enabled() -> bool:
    return (os.environ.get("ACS_USE_SECRET_MANAGER") or "1").strip() not in ("0", "false", "False")


def put_secret(reference_id: str, value: str) -> str:
    if not reference_id:
        raise ValueError("reference_id is required")
    if not isinstance(value, str) or not value:
        raise ValueError("value is required")

    if _sm_enabled():
        project = (os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
        if project:
            client = secretmanager.SecretManagerServiceClient()
            parent = f"projects/{project}"
            secret_name = f"acs-{reference_id}".replace("_", "-")
            secret_path = f"{parent}/secrets/{secret_name}"
            try:
                client.get_secret(request={"name": secret_path})
            except Exception:
                client.create_secret(
                    request={
                        "parent": parent,
                        "secret_id": secret_name,
                        "secret": {"replication": {"automatic": {}}},
                    }
                )
            client.add_secret_version(
                request={"parent": secret_path, "payload": {"data": value.encode("utf-8")}}
            )
            return f"sm://{secret_name}"

    # TODO: remove Firestore fallback once Secret Manager is guaranteed in all envs.
    ensure_firebase()
    from firebase_admin import firestore

    firestore.client().collection("IntegrationSecrets").document(reference_id).set({"value": value}, merge=True)
    return f"firestore://IntegrationSecrets/{reference_id}"


def get_secret(secret_ref: str) -> str | None:
    if not secret_ref:
        return None
    if secret_ref.startswith("env://"):
        return os.environ.get(secret_ref[len("env://") :])

    if secret_ref.startswith("sm://"):
        secret_name = secret_ref[len("sm://") :]
        project = (os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT") or "").strip()
        if not project:
            return None
        client = secretmanager.SecretManagerServiceClient()
        path = f"projects/{project}/secrets/{secret_name}/versions/latest"
        try:
            resp = client.access_secret_version(request={"name": path})
            return resp.payload.data.decode("utf-8")
        except Exception:
            return None

    if secret_ref.startswith("firestore://"):
        ensure_firebase()
        from firebase_admin import firestore

        parts = secret_ref[len("firestore://") :].split("/", 1)
        if len(parts) != 2:
            return None
        col, doc = parts
        snap = firestore.client().collection(col).document(doc).get()
        if not snap.exists:
            return None
        data: dict[str, Any] = snap.to_dict() or {}
        raw = data.get("value")
        return raw if isinstance(raw, str) else None
    return None
