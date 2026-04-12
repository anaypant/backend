import os
from typing import Any

from google.cloud import secretmanager

from store.authn import ensure_firebase
from store.common import post_json_secrets_platform
from store import gcp_identity
from store.secrets_ref import scope_id_from_acs_sec_ref


def _sm_enabled() -> bool:
    return (os.environ.get("ACS_USE_SECRET_MANAGER") or "1").strip() not in ("0", "false", "False")


def _secrets_origin() -> str | None:
    h = gcp_identity.normalize_internal_gateway_hostname(os.environ.get("SECRETS_INTERNAL_GATEWAY_HOSTNAME") or "")
    return f"https://{h}" if h else None


def _legacy_reference_to_scope_key(reference_id: str) -> tuple[str, str] | None:
    if reference_id.startswith("fub-access-"):
        return reference_id[len("fub-access-") :], "integration/followupboss/access_token"
    if reference_id.startswith("fub-refresh-"):
        return reference_id[len("fub-refresh-") :], "integration/followupboss/refresh_token"
    return None


def put_secret(reference_id: str, value: str) -> str:
    if not reference_id:
        raise ValueError("reference_id is required")
    if not isinstance(value, str) or not value:
        raise ValueError("value is required")

    origin = _secrets_origin()
    mapped = _legacy_reference_to_scope_key(reference_id) if origin else None
    if origin and mapped:
        scope_id, key = mapped
        url = f"{origin.rstrip('/')}/secrets/v1/write"
        body, status = post_json_secrets_platform(
            url,
            {"scope": "realtor", "scopeId": scope_id, "key": key, "value": value},
            acting_uid=scope_id,
        )
        if status >= 400:
            raise RuntimeError(f"secrets write failed: {status} {body}")
        ref = body.get("ref")
        if isinstance(ref, str) and ref.startswith("acs-sec://"):
            return ref
        raise RuntimeError("secrets service did not return acs-sec ref")

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

            try:
                cur = client.access_secret_version(
                    request={"name": f"{secret_path}/versions/latest"}
                )
                if cur.payload.data.decode("utf-8") == value:
                    return f"sm://{secret_name}"
            except Exception:
                pass
            client.add_secret_version(
                request={"parent": secret_path, "payload": {"data": value.encode("utf-8")}}
            )
            return f"sm://{secret_name}"

    ensure_firebase()
    from firebase_admin import firestore

    firestore.client().collection("IntegrationSecrets").document(reference_id).set({"value": value}, merge=True)
    return f"firestore://IntegrationSecrets/{reference_id}"


def get_secret(secret_ref: str, *, acting_uid: str | None = None) -> str | None:
    if not secret_ref:
        return None
    if secret_ref.startswith("env://"):
        return os.environ.get(secret_ref[len("env://") :])

    if secret_ref.startswith("acs-sec://"):
        origin = _secrets_origin()
        if not origin:
            return None
        act = (acting_uid or "").strip() or scope_id_from_acs_sec_ref(secret_ref)
        if not act:
            return None
        url = f"{origin.rstrip('/')}/secrets/v1/read"
        body, status = post_json_secrets_platform(url, {"ref": secret_ref}, acting_uid=act)
        if status >= 400:
            return None
        raw = body.get("value")
        return raw if isinstance(raw, str) else None

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
        if col != "IntegrationSecrets":
            return None
        snap = firestore.client().collection(col).document(doc).get()
        if not snap.exists:
            return None
        data: dict[str, Any] = snap.to_dict() or {}
        raw = data.get("value")
        return raw if isinstance(raw, str) else None
    return None
