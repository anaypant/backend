"""
Curated deterministic checks for core units. Used by pytest (indirectly via imports) and
``POST /core/v1/run`` with ``__ACS_DEV_LAB__: "run_unit_checks"``.
"""

from __future__ import annotations

from typing import Any, Callable

CheckFn = Callable[[], dict[str, Any]]


def _check_normalize_fub_uri_path() -> dict[str, Any]:
    from workflows import normalize_integration_payload

    acs = {
        "source": {"provider": "followupboss", "event_type": "peopleCreated"},
        "payload": {"event": "peopleCreated", "uri": "https://api.followupboss.com/v1/people/42"},
    }
    n = normalize_integration_payload.normalize_contact(acs)
    if n.get("person_id") != 42:
        return {"id": "normalize_integration_payload.fub_uri_path", "ok": False, "detail": f"bad person_id {n!r}"}
    return {"id": "normalize_integration_payload.fub_uri_path", "ok": True, "detail": ""}


def _check_normalize_fub_query_uri() -> dict[str, Any]:
    from workflows import normalize_integration_payload

    acs = {
        "source": {"provider": "followupboss", "event_type": "peopleCreated"},
        "payload": {"event": "peopleCreated", "uri": "https://api.followupboss.com/v1/people?id=99"},
    }
    n = normalize_integration_payload.normalize_contact(acs)
    if n.get("person_id") != 99:
        return {"id": "normalize_integration_payload.fub_query_uri", "ok": False, "detail": f"bad {n!r}"}
    return {"id": "normalize_integration_payload.fub_query_uri", "ok": True, "detail": ""}


def _check_workflow_registry_has_contact_enrichment() -> dict[str, Any]:
    from workflows import registry as wf_registry

    if not wf_registry.is_registered("contact.enrichment_v1"):
        return {"id": "workflow_registry.contact_enrichment_v1", "ok": False, "detail": "missing registration"}
    return {"id": "workflow_registry.contact_enrichment_v1", "ok": True, "detail": ""}


def _check_execution_policy_default() -> dict[str, Any]:
    from state.execution_policy import get_execution_policy

    acs: dict[str, Any] = {"metadata": {}}
    p = get_execution_policy(acs)
    if "volatile_external_allowed" not in p:
        return {"id": "execution_policy.default_keys", "ok": False, "detail": f"missing keys in {p!r}"}
    return {"id": "execution_policy.default_keys", "ok": True, "detail": ""}


_CHECKS: list[tuple[str, CheckFn]] = [
    ("normalize_integration_payload.fub_uri_path", _check_normalize_fub_uri_path),
    ("normalize_integration_payload.fub_query_uri", _check_normalize_fub_query_uri),
    ("workflow_registry.contact_enrichment_v1", _check_workflow_registry_has_contact_enrichment),
    ("execution_policy.default_keys", _check_execution_policy_default),
]


def run_all_unit_checks() -> dict[str, Any]:
    """Run all registered checks; never raises (failures become ``ok: false`` rows)."""
    results: list[dict[str, Any]] = []
    for cid, fn in _CHECKS:
        try:
            r = fn()
            if r.get("id") != cid:
                r = {"id": cid, "ok": False, "detail": f"check returned wrong id: {r!r}"}
            results.append(r)
        except Exception as e:
            results.append({"id": cid, "ok": False, "detail": str(e)[:800]})
    passed = sum(1 for r in results if r.get("ok") is True)
    failed = len(results) - passed
    return {
        "results": results,
        "summary": {"passed": passed, "failed": failed, "total": len(results)},
        "ok": failed == 0,
    }
