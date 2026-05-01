"""
Lead lane policy — active vs nurture for intel cost routing and automation.

PM v1: ``glydeQuarantined`` remains drip-only; lane is separate. Default lane is ``active``.
Auto mode is configured via ``GlydeSettings.leadLaneAutoMode`` or env ``ACS_LEAD_LANE_AUTO``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

Lane = Literal["active", "nurture"]
AutoMode = Literal["off", "shadow", "advisory", "on"]


@dataclass(frozen=True)
class LaneDecision:
    lane: Lane
    reason_codes: list[str]
    reason_human: str
    skip_auto_write: bool


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_lead_lane_auto_mode(glyde_settings: dict[str, Any] | None) -> AutoMode:
    raw = (glyde_settings or {}).get("leadLaneAutoMode")
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raw = os.environ.get("ACS_LEAD_LANE_AUTO", "off")
    m = str(raw).strip().lower()
    if m in ("off", "shadow", "advisory", "on"):
        return m  # type: ignore[return-value]
    return "off"


def _days_since_iso(date_str: str | None) -> int | None:
    if not date_str or not isinstance(date_str, str):
        return None
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - dt.astimezone(timezone.utc)
        return max(0, int(delta.total_seconds() // 86400))
    except (ValueError, TypeError):
        return None


def compute_lane(
    lead_doc: dict[str, Any],
    glyde_settings: dict[str, Any] | None,
    realtor_profile: dict[str, Any] | None,
) -> LaneDecision:
    """
    Pure policy: given the flattened Firestore ``Leads/{id}`` document ``data`` map,
    return the lane ACS should use for nurture gating. Does not read settings for rules
    beyond auto-mode resolution (callers use ``resolve_lead_lane_auto_mode`` separately).

    ``lead_doc`` should include nested ``lead`` when present, plus Glyde fields at top level.
    """
    _ = glyde_settings
    _ = realtor_profile

    if bool(lead_doc.get("glydeLaneUserPinned")):
        cur = str(lead_doc.get("glydeLeadLane") or "active").lower()
        lane: Lane = cur if cur in ("active", "nurture") else "active"
        return LaneDecision(
            lane=lane,
            reason_codes=["user_pinned"],
            reason_human="Lane is user-pinned; automation does not change it.",
            skip_auto_write=True,
        )

    if bool(lead_doc.get("glydeIsHot")):
        return LaneDecision(
            lane="active",
            reason_codes=["hot_lead"],
            reason_human="Hot lead; stays in active lane.",
            skip_auto_write=False,
        )

    score = lead_doc.get("glydeScore")
    score_int: int | None
    try:
        score_int = int(score) if score is not None and str(score).strip() != "" else None
    except (TypeError, ValueError):
        score_int = None

    inner = lead_doc.get("lead") if isinstance(lead_doc.get("lead"), dict) else {}
    last_touch = (
        inner.get("lastContacted")
        or inner.get("lastActivityAt")
        or lead_doc.get("glydeScoreUpdatedAt")
    )
    days = _days_since_iso(str(last_touch) if last_touch is not None else None)

    if score_int is not None and score_int < 20:
        return LaneDecision(
            lane="nurture",
            reason_codes=["very_low_score"],
            reason_human="Very low Glyde score; nurture lane.",
            skip_auto_write=False,
        )

    if score_int is not None and score_int < 35 and days is not None and days > 45:
        return LaneDecision(
            lane="nurture",
            reason_codes=["low_score", "stale_touch"],
            reason_human="Low score and no recent engagement; nurture lane.",
            skip_auto_write=False,
        )

    emails = inner.get("emails") or []
    phones = inner.get("phones") or []
    if not emails and not phones and (score_int is None or score_int < 45):
        return LaneDecision(
            lane="nurture",
            reason_codes=["sparse_contact"],
            reason_human="Sparse contact data; nurture lane.",
            skip_auto_write=False,
        )

    return LaneDecision(
        lane="active",
        reason_codes=["default_active"],
        reason_human="Active lane by default policy.",
        skip_auto_write=False,
    )


def legacy_migration_merge_fields(lead_data: dict[str, Any]) -> dict[str, Any] | None:
    """
    One-time backfill: if ``glydeLeadLane`` is missing, return merge fields.

    - ``glydeQuarantined`` → ``nurture`` (does not clear quarantine).
    - Else → ``active``.
    """
    cur = str(lead_data.get("glydeLeadLane") or "").strip().lower()
    if cur in ("active", "nurture"):
        return None
    now = _iso_now()
    if bool(lead_data.get("glydeQuarantined")):
        return {
            "glydeLeadLane": "nurture",
            "glydeLaneUpdatedAt": now,
            "glydeLaneReason": "Migrated: previously drip-quarantined; mapped to nurture lane.",
            "glydeLaneReasonCodes": ["migration_from_glydeQuarantined"],
            "glydeLaneSource": "migration",
        }
    return {
        "glydeLeadLane": "active",
        "glydeLaneUpdatedAt": now,
        "glydeLaneReason": "Migrated: default active lane.",
        "glydeLaneReasonCodes": ["migration_default_active"],
        "glydeLaneSource": "migration",
    }
