"""Characterization tests for benchmarks.build.synthetic.build().

Pure-Python and offline — no network or download mocking needed. Pins behavior
for a fixed seed with a small mock store.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from benchmarks.build.sources.synthetic import build

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_store(entities: dict[str, str]) -> MagicMock:
    """Build a minimal mock EntityStore from {entity_id: canonical_name}."""
    from resolvekit.core.model.entity import EntityRecord

    records: dict[str, EntityRecord] = {
        eid: EntityRecord(
            entity_id=eid,
            entity_type="geo.country",
            canonical_name=cname,
            canonical_name_norm=cname.lower(),
            names=[],
        )
        for eid, cname in entities.items()
    }

    store = MagicMock()
    store.all_entity_ids.return_value = set(records.keys())
    store.bulk_get_entities.side_effect = lambda ids: {
        eid: records[eid] for eid in ids if eid in records
    }
    return store


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_build_returns_benchmark_rows() -> None:
    """build() returns Query objects with correct fixed fields."""
    store = _make_mock_store(
        {
            "country/USA": "United States of America",
            "country/GBR": "United Kingdom",
            "country/FRA": "France",
        }
    )
    rows = build(store=store, seed=42, id_prefix="country/")

    assert len(rows) > 0
    for row in rows:
        assert row.source == "synthetic"
        assert row.entity_type == "country"
        assert row.language == "en"
        assert row.expected_ids[0].startswith("country/")
        assert row.text  # non-empty string


def test_build_deterministic() -> None:
    """Two calls with same seed produce identical rows."""
    store = _make_mock_store(
        {
            "country/USA": "United States of America",
            "country/GBR": "United Kingdom",
        }
    )
    rows_a = build(store=store, seed=42)
    rows_b = build(store=store, seed=42)
    assert [r.text for r in rows_a] == [r.text for r in rows_b]
    assert [r.expected_ids for r in rows_a] == [r.expected_ids for r in rows_b]


def test_build_different_seed_different_output() -> None:
    """Different seeds produce different query text orderings."""
    store = _make_mock_store(
        {
            "country/USA": "United States of America",
            "country/GBR": "United Kingdom",
            "country/FRA": "France",
            "country/DEU": "Federal Republic of Germany",
        }
    )
    rows_a = build(store=store, seed=1)
    rows_b = build(store=store, seed=2)
    assert [r.text for r in rows_a] != [r.text for r in rows_b]


def test_build_respects_limit() -> None:
    """limit=2 → at most 2 rows returned."""
    store = _make_mock_store(
        {
            "country/USA": "United States of America",
            "country/GBR": "United Kingdom",
            "country/FRA": "France",
        }
    )
    rows = build(store=store, seed=42, limit=2)
    assert len(rows) <= 2


def test_build_filters_by_id_prefix() -> None:
    """id_prefix filters out entities that don't start with it."""
    store = _make_mock_store(
        {
            "country/USA": "United States of America",
            "org/WB": "World Bank",
        }
    )
    rows = build(store=store, seed=42, id_prefix="country/")
    for row in rows:
        assert row.expected_ids[0].startswith("country/")


def test_build_classifies_mutations() -> None:
    """Rows carry one of the expected difficulty/category values."""
    store = _make_mock_store(
        {
            "country/USA": "United States of America",
            "country/GBR": "United Kingdom",
            "country/DEU": "Federal Republic of Germany",
        }
    )
    rows = build(store=store, seed=42)
    valid_categories = {
        "typo",
        "case_noise",
        "canonical_unicode",
        "heavy_noise",
        "prefix_truncation",
    }
    valid_difficulties = {"easy", "medium", "hard"}
    for row in rows:
        assert row.category in valid_categories
        assert row.difficulty in valid_difficulties


def test_build_empty_store() -> None:
    """Empty store returns no rows."""
    store = _make_mock_store({})
    rows = build(store=store, seed=42)
    assert rows == []
