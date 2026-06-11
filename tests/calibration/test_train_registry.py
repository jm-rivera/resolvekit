"""Guard tests for calibration.train.ADAPTER_REGISTRY shape and callability.

These tests trip if adapter entries are added, removed, renamed, or replaced
without corresponding updates to the registry and this test file.
"""

from __future__ import annotations

from resolvekit.calibration.train import ADAPTER_REGISTRY, run_adapters
from resolvekit.core.model.entity import EntityRecord, NameRecord
from tests.conftest import MockEntityStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_geo_store() -> MockEntityStore:
    """Small offline store with two countries, enough for synthetic adapter."""
    records: dict[str, EntityRecord] = {
        "country/USA": EntityRecord(
            entity_id="country/USA",
            entity_type="geo.country",
            canonical_name="United States of America",
            canonical_name_norm="united states of america",
            names=[
                NameRecord(value="USA", value_norm="usa", kind="alias"),
            ],
        ),
        "country/GBR": EntityRecord(
            entity_id="country/GBR",
            entity_type="geo.country",
            canonical_name="United Kingdom",
            canonical_name_norm="united kingdom",
            names=[],
        ),
        "country/DEU": EntityRecord(
            entity_id="country/DEU",
            entity_type="geo.country",
            canonical_name="Federal Republic of Germany",
            canonical_name_norm="federal republic of germany",
            names=[],
        ),
    }
    return MockEntityStore(entities=records)


# ---------------------------------------------------------------------------
# Registry shape assertions (parts 1 + 2)
# ---------------------------------------------------------------------------


def test_adapter_registry_geo_keys() -> None:
    """geo registry contains exactly the expected adapters."""
    assert sorted(ADAPTER_REGISTRY["geo"]) == [
        "cldr",
        "geonames",
        "multilingual_names",
        "synthetic",
        "wikidata",
    ]


def test_adapter_registry_org_keys() -> None:
    """org registry contains exactly the expected adapters."""
    assert sorted(ADAPTER_REGISTRY["org"]) == ["synthetic", "wikidata"]


def test_adapter_registry_all_callable() -> None:
    """Every registry value is callable."""
    assert all(callable(v) for d in ADAPTER_REGISTRY.values() for v in d.values())


# ---------------------------------------------------------------------------
# run_adapters smoke test (part 3) — offline, deterministic
# ---------------------------------------------------------------------------


def test_run_adapters_synthetic_geo_offline() -> None:
    """run_adapters with the synthetic adapter returns non-empty LabeledExamples offline."""
    store = _make_geo_store()
    examples = run_adapters("geo", ["synthetic"], store)
    assert len(examples) > 0
    for ex in examples:
        assert ex.source_adapter == "synthetic"
        assert ex.domain == "geo"
        assert ex.expected_entity_id in store.all_entity_ids()
