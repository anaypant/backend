"""Re-export webhook → workflow resolution (table-driven)."""

from __future__ import annotations

from dispatcher.webhook_workflow_map import resolve_default_workflow_id

__all__ = ["resolve_default_workflow_id"]
