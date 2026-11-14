"""Readers for athlete profile facts."""
from __future__ import annotations

from typing import Any

CLINICAL_RESTRICTION_KEY = "clinical_restriction"
LEGACY_RESTRICTION_TEXT_KEY = "clinician_restriction"
LEGACY_RESTRICTION_FLAG_KEY = "clinical_restriction_active"
_EMPTY = frozenset({"", "none", "unknown"})


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return None if text.casefold() in _EMPTY else text


def clinical_restriction(facts: dict[str, Any] | None) -> str | None:
    facts = facts or {}
    for key in (CLINICAL_RESTRICTION_KEY, LEGACY_RESTRICTION_TEXT_KEY):
        if (text := _text(facts.get(key))) is not None:
            return text
    return "restricted" if facts.get(LEGACY_RESTRICTION_FLAG_KEY) else None
