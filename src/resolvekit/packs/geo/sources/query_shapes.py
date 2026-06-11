"""Helpers for classifying geo query text shapes."""

from __future__ import annotations

import re

_WIKIDATA_PREFIX_PATTERN = re.compile(r"^wikidata:(q\d+)$", re.IGNORECASE)
_WIKIDATA_QID_PATTERN = re.compile(r"^q\d+$", re.IGNORECASE)
_SHORT_ALPHA_CODE_PATTERN = re.compile(r"^[a-z]{2,3}$")
_ISO_NUMERIC_PATTERN = re.compile(r"^\d{3}$")


def wikidata_lookup_values(raw_text: str, normalized_text: str) -> tuple[str, ...]:
    """Return normalized lookup values for wikidata-like queries."""
    raw = raw_text.strip()
    normalized = normalized_text.strip().lower()
    if not raw or not normalized:
        return ()

    qid_value: str | None = None
    if match := _WIKIDATA_PREFIX_PATTERN.fullmatch(normalized):
        qid_value = match.group(1).lower()
    elif _WIKIDATA_QID_PATTERN.fullmatch(normalized):
        qid_value = normalized

    if qid_value is None:
        return ()

    values = [qid_value]
    if len(qid_value) > 1:
        values.append(qid_value[1:])
    return tuple(dict.fromkeys(values))


def is_geo_code_like_query(raw_text: str, normalized_text: str) -> bool:
    """Return True for code-like query shapes that should bypass broad text search."""
    raw = raw_text.strip()
    normalized = normalized_text.strip().lower()
    if not raw or not normalized:
        return False

    no_spaces = " " not in normalized
    return bool(
        wikidata_lookup_values(raw, normalized)
        or ("/" in normalized and no_spaces)
        or (":" in normalized and no_spaces)
        or _SHORT_ALPHA_CODE_PATTERN.fullmatch(normalized)
        or _ISO_NUMERIC_PATTERN.fullmatch(normalized)
    )
