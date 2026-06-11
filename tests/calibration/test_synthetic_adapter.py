"""Tests for the synthetic perturbation free functions."""

from __future__ import annotations

import random

import pytest

from resolvekit.calibration.adapters.synthetic import (
    _drop_word,
    _reorder_words,
    _truncate_word,
    synthetic_generate_geo_pairs,
    synthetic_generate_org_pairs,
)
from resolvekit.core.model.entity import EntityRecord, NameRecord
from tests.conftest import MockEntityStore


def _make_store(
    entities: dict[str, str], aliases: dict[str, list[str]] | None = None
) -> MockEntityStore:
    """Helper: build a MockEntityStore from {entity_id: canonical_name}."""
    aliases = aliases or {}
    records: dict[str, EntityRecord] = {}
    for eid, cname in entities.items():
        name_records = [
            NameRecord(value=a, value_norm=a.lower(), kind="alias")
            for a in aliases.get(eid, [])
        ]
        records[eid] = EntityRecord(
            entity_id=eid,
            entity_type="geo.country",
            canonical_name=cname,
            canonical_name_norm=cname.lower(),
            names=name_records,
        )
    return MockEntityStore(entities=records)


# ---------------------------------------------------------------------------
# Word-level function unit tests
# ---------------------------------------------------------------------------


class TestDropWord:
    def test_removes_one_word(self):
        rng = random.Random(42)
        result = _drop_word("Republic of Korea", rng)
        assert result != "Republic of Korea"
        assert len(result.split()) == 2

    def test_unchanged_for_short_name(self):
        rng = random.Random(42)
        assert _drop_word("France", rng) == "France"
        assert _drop_word("New Zealand", rng) == "New Zealand"


class TestReorderWords:
    def test_reorders(self):
        random.Random(0)
        # With enough words, at least one seed should reorder
        name = "United States of America"
        results = {_reorder_words(name, random.Random(s)) for s in range(20)}
        assert len(results) > 1  # at least one reordering differs

    def test_unchanged_for_single_word(self):
        rng = random.Random(42)
        assert _reorder_words("France", rng) == "France"


class TestTruncateWord:
    def test_truncates_long_word(self):
        rng = random.Random(42)
        result = _truncate_word("International Organization", rng)
        words = result.split()
        assert any(len(w) <= 4 for w in words)

    def test_unchanged_when_all_words_short(self):
        rng = random.Random(42)
        assert _truncate_word("A B C D", rng) == "A B C D"


# ---------------------------------------------------------------------------
# Geo adapter integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
def geo_store() -> MockEntityStore:
    return _make_store(
        {
            "country/USA": "United States of America",
            "country/GBR": "United Kingdom",
            "country/FRA": "France",
            "country/KOR": "Republic of Korea",
            "country/DEU": "Federal Republic of Germany",
        },
        aliases={
            "country/USA": ["USA", "US", "America"],
        },
    )


@pytest.fixture
def org_store() -> MockEntityStore:
    return _make_store(
        {
            "org/WB": "World Bank",
            "org/UNICEF": "United Nations Children's Fund",
            "org/WHO": "World Health Organization",
        }
    )


class TestSyntheticGeoGeneratePairs:
    def test_generates_examples(self, geo_store: MockEntityStore):
        examples = synthetic_generate_geo_pairs(store=geo_store, seed=42)
        assert len(examples) > 0
        for ex in examples:
            assert ex.source_adapter == "synthetic"
            assert ex.domain == "geo"
            assert ex.raw_score is None
            assert ex.label is None
            assert ex.expected_entity_id in geo_store.all_entity_ids()

    def test_query_text_differs_from_canonical(self, geo_store: MockEntityStore):
        examples = synthetic_generate_geo_pairs(store=geo_store, seed=42)
        entities = geo_store.bulk_get_entities(list(geo_store.all_entity_ids()))
        for ex in examples:
            canonical = entities[ex.expected_entity_id].canonical_name
            assert ex.query_text != canonical

    def test_limit(self, geo_store: MockEntityStore):
        examples = synthetic_generate_geo_pairs(store=geo_store, seed=42, limit=5)
        assert len(examples) <= 5

    def test_reproducibility(self, geo_store: MockEntityStore):
        a = synthetic_generate_geo_pairs(store=geo_store, seed=99)
        b = synthetic_generate_geo_pairs(store=geo_store, seed=99)
        assert [e.query_text for e in a] == [e.query_text for e in b]

    def test_different_seed_different_output(self, geo_store: MockEntityStore):
        a = synthetic_generate_geo_pairs(store=geo_store, seed=1)
        b = synthetic_generate_geo_pairs(store=geo_store, seed=2)
        assert [e.query_text for e in a] != [e.query_text for e in b]

    def test_empty_store(self):
        store = _make_store({})
        assert synthetic_generate_geo_pairs(store=store, seed=42) == []

    def test_short_names(self):
        store = _make_store({"country/X": "X"})
        # Single-char name filtered out in _build_entity_frame
        assert synthetic_generate_geo_pairs(store=store, seed=42) == []

    def test_skips_existing_alias(self):
        """If a perturbation accidentally produces an existing alias, skip it."""
        store = _make_store(
            {"country/USA": "United States of America"},
            aliases={"country/USA": ["america"]},
        )
        examples = synthetic_generate_geo_pairs(store=store, seed=42)
        query_texts_lower = {ex.query_text.lower() for ex in examples}
        assert "america" not in query_texts_lower

    def test_accepts_cache_dir(self, geo_store: MockEntityStore):
        # cache_dir is accepted but unused by synthetic
        examples = synthetic_generate_geo_pairs(
            store=geo_store, seed=42, cache_dir="/tmp/test"
        )
        assert len(examples) > 0


class TestSyntheticOrgGeneratePairs:
    def test_generates_examples(self, org_store: MockEntityStore):
        examples = synthetic_generate_org_pairs(store=org_store, seed=42)
        assert len(examples) > 0
        for ex in examples:
            assert ex.source_adapter == "synthetic"
            assert ex.domain == "org"

    def test_name_and_domain(self):
        store = _make_store({"org/WB": "World Bank"})
        examples = synthetic_generate_org_pairs(store=store, seed=42)
        for ex in examples:
            assert ex.source_adapter == "synthetic"
            assert ex.domain == "org"
