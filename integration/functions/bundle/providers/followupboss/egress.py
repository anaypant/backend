from providers.followupboss.client import FubClient
from store.profile_repo import load_fub_profile_by_connection_id
from store.secret_repo import get_secret


def _client_for_connection(connection_id: str) -> FubClient:
    _, fub = load_fub_profile_by_connection_id(connection_id)
    if not fub:
        return FubClient()
    auth = dict(fub.get("auth") or {})
    return FubClient(access_token_ref=auth.get("accessTokenRef"), api_key_ref=auth.get("apiKeyRef"))


def apply_outbound_actions(connection_id: str, actions: list[dict]) -> dict:
    client = _client_for_connection(connection_id)
    results: list[dict] = []
    for action in actions:
        if not isinstance(action, dict):
            results.append({"ok": False, "error": "invalid action"})
            continue
        name = action.get("name")
        payload = action.get("payload") if isinstance(action.get("payload"), dict) else {}
        if name == "upsertPerson":
            body, status = client.upsert_person(payload)
        elif name == "createNote":
            person_id = payload.get("personId")
            note_body = payload.get("body")
            if not isinstance(person_id, int) or not isinstance(note_body, str):
                results.append({"name": name, "ok": False, "error": "personId(int) and body(str) required"})
                continue
            body, status = client.create_note(person_id, note_body)
        elif name == "createTask":
            person_id = payload.get("personId")
            task_body = payload.get("body")
            if not isinstance(person_id, int) or not isinstance(task_body, str):
                results.append({"name": name, "ok": False, "error": "personId(int) and body(str) required"})
                continue
            body, status = client.create_task(person_id, task_body)
        else:
            results.append({"name": name, "ok": False, "error": "unsupported action"})
            continue

        results.append({"name": name, "ok": status < 400, "status": status, "detail": body})

    ok = all(r.get("ok") for r in results) if results else True
    return {"ok": ok, "results": results}
