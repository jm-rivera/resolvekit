"""Length-scaled edit-distance gate for SymSpell typo corrections.

Two edits in a short query rewrite too much of it to be a typo fix —
"paris" → "moris" (Mauritius) was surfacing as a candidate. Short queries
accept distance 1 only; longer queries keep the configured max distance.
"""

from __future__ import annotations

from resolvekit.core.store import EntityStore
from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource


class _FakeSuggestion:
    def __init__(self, term: str, distance: int) -> None:
        self.term = term
        self.distance = distance


class _NameStore(EntityStore):
    """Store stub: maps normalized names to entity ids."""

    def __init__(self, names: dict[str, list[str]]) -> None:
        self._names = names

    def get_entity(self, entity_id):
        return None

    def lookup_code(self, system, value_norm):
        return []

    def lookup_name_exact(self, value_norm, name_kinds=None):
        return self._names.get(value_norm, [])

    def search_fulltext(self, query_norm, fields=None, limit=10):
        return []

    def bulk_get_entities(self, entity_ids):
        return {}

    def search_prefix(self, query_norm, field, limit=10):
        return []


def _evidence_for(query: str, term: str, distance: int) -> list:
    source = GeoSymSpellSource()
    store = _NameStore({term: ["country/XXX"]})
    evidence, _rank = source._suggestions_to_evidence(
        [_FakeSuggestion(term, distance)],
        query,
        store,
        budget=10,
        start_rank=0,
    )
    return evidence


def test_short_query_rejects_distance_two() -> None:
    """'paris' must not correct to 'moris' — 2 edits in 5 chars."""
    assert _evidence_for("paris", "moris", 2) == []


def test_short_query_accepts_distance_one() -> None:
    assert _evidence_for("frnace", "france", 1) != []


def test_long_query_keeps_distance_two() -> None:
    assert _evidence_for("mauritis", "mauritius", 2) != []
