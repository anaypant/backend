"""Realtors|Internals collection names (align with db Firestore layout / db/main.tf)."""


def collection_for_role(role: str) -> str:
    if role == "realtor":
        return "Realtors"
    if role == "internal":
        return "Internals"
    raise ValueError("invalid role")
