"""Follow Up Boss ↔ ACS mapping (inbound canonical lives in ``schema``; outbound helpers here)."""

from providers.followupboss.mapping.outbound import acs_outbound_action_to_fub_request

__all__ = ["acs_outbound_action_to_fub_request"]
