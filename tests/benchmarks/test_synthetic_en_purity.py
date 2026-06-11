"""Tests for English-purity benchmark filter and collision widening.

Offline — no network or external data required.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from benchmarks.build.sources.synthetic import _PrefixFilteredStore
from benchmarks.core.kernel import Query
from resolvekit.core.model.entity import EntityRecord, NameRecord

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_name(value: str, lang: str | None, kind: str = "alias") -> NameRecord:
    return NameRecord(value=value, value_norm=value.lower(), kind=kind, lang=lang)


def _make_record(
    entity_id: str,
    canonical_name: str,
    names: list[NameRecord] | None = None,
) -> EntityRecord:
    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name=canonical_name,
        canonical_name_norm=canonical_name.lower(),
        names=names or [],
    )


def _make_query(
    text: str,
    expected_ids: tuple[str, ...],
    *,
    source: str = "synthetic",
    category: str = "canonical",
    entity_type: str = "country",
) -> Query:
    return Query(
        query_id="",
        text=text,
        expected_ids=expected_ids,
        language="en",
        entity_type=entity_type,
        category=category,
        difficulty="medium",
        capabilities=("typo",),
        source=source,
        notes=None,
    )


# ---------------------------------------------------------------------------
# _PrefixFilteredStore.bulk_get_entities
# ---------------------------------------------------------------------------


def test_bulk_get_entities_drops_fr_keeps_en_and_none() -> None:
    """bulk_get_entities strips lang='fr' names, keeps lang='en' and lang=None."""
    fr_name = _make_name("Guinée", lang="fr")
    en_name = _make_name("Guinea", lang="en")
    null_name = _make_name("GN", lang=None)

    rec = _make_record("country/GIN", "Guinea", names=[fr_name, en_name, null_name])

    inner = MagicMock()
    inner.all_entity_ids.return_value = {"country/GIN"}
    inner.bulk_get_entities.return_value = {"country/GIN": rec}

    store = _PrefixFilteredStore(inner, id_prefix="country/")
    result = store.bulk_get_entities(["country/GIN"])

    assert "country/GIN" in result
    filtered = result["country/GIN"]
    langs = [n.lang for n in filtered.names]
    assert "fr" not in langs
    assert "en" in langs
    assert None in langs


def test_bulk_get_entities_canonical_name_preserved() -> None:
    """canonical_name is never filtered regardless of names content."""
    fr_name = _make_name("Guinée", lang="fr")
    rec = _make_record("country/GIN", "Guinea", names=[fr_name])

    inner = MagicMock()
    inner.all_entity_ids.return_value = {"country/GIN"}
    inner.bulk_get_entities.return_value = {"country/GIN": rec}

    store = _PrefixFilteredStore(inner, id_prefix="country/")
    result = store.bulk_get_entities(["country/GIN"])

    assert result["country/GIN"].canonical_name == "Guinea"


def test_bulk_get_entities_only_foreign_names_all_stripped() -> None:
    """An entity with only foreign-language names ends up with empty names list."""
    rec = _make_record(
        "country/GIN",
        "Guinea",
        names=[
            _make_name("Guinée", lang="fr"),
            _make_name("Guinée équatoriale", lang="fr"),
        ],
    )

    inner = MagicMock()
    inner.bulk_get_entities.return_value = {"country/GIN": rec}

    store = _PrefixFilteredStore(inner, id_prefix="country/")
    result = store.bulk_get_entities(["country/GIN"])

    assert result["country/GIN"].names == []


def test_bulk_get_entities_empty_input() -> None:
    """Empty entity_ids list returns empty dict."""
    inner = MagicMock()
    inner.bulk_get_entities.return_value = {}

    store = _PrefixFilteredStore(inner, id_prefix="country/")
    result = store.bulk_get_entities([])

    assert result == {}


# ---------------------------------------------------------------------------
# _drop_synthetic_cross_source_collisions
# ---------------------------------------------------------------------------

# Import after the module-under-test is clear
from benchmarks.build import _drop_synthetic_cross_source_collisions  # noqa: E402


def test_collision_drops_synthetic_row_colliding_with_alias_for_different_entity() -> (
    None
):
    """Synthetic→CHN row dropped when 'Republic of China' is a wikidata alias for TWN."""
    # Non-synthetic alias row: "Republic of China" → TWN, source='wikidata', category='alias'
    roc_wikidata = _make_query(
        "Republic of China",
        ("country/TWN",),
        source="wikidata",
        category="alias",
    )
    # Synthetic row: "Republic of China" → CHN (different entity)
    roc_synthetic = _make_query(
        "Republic of China",
        ("country/CHN",),
        source="synthetic",
        category="typo",
    )

    rows = [roc_wikidata, roc_synthetic]
    result = _drop_synthetic_cross_source_collisions(rows)

    result_texts = [(r.text, r.source) for r in result]
    assert ("Republic of China", "wikidata") in result_texts
    assert ("Republic of China", "synthetic") not in result_texts


def test_collision_keeps_synthetic_row_when_expected_ids_match() -> None:
    """Synthetic row kept when expected_ids match the non-synthetic row."""
    cldr_row = _make_query(
        "Taiwan", ("country/TWN",), source="cldr", category="canonical"
    )
    synth_row = _make_query(
        "Taiwan", ("country/TWN",), source="synthetic", category="typo"
    )

    rows = [cldr_row, synth_row]
    result = _drop_synthetic_cross_source_collisions(rows)

    assert len(result) == 2


def test_collision_also_drops_on_non_canonical_alias_rows() -> None:
    """Non-canonical (alias) non-synthetic rows seed the collision dict."""
    alias_row = _make_query(
        "Netherlands",
        ("country/NLD",),
        source="geonames",
        category="alias",
    )
    synth_collision = _make_query(
        "Netherlands",
        ("country/BES",),
        source="synthetic",
        category="canonical",
    )

    rows = [alias_row, synth_collision]
    result = _drop_synthetic_cross_source_collisions(rows)

    sources_in_result = [r.source for r in result]
    assert "geonames" in sources_in_result
    assert "synthetic" not in sources_in_result


def test_no_collision_no_rows_dropped() -> None:
    """Rows without any collision are preserved unchanged."""
    cldr_row = _make_query(
        "France", ("country/FRA",), source="cldr", category="canonical"
    )
    synth_row = _make_query(
        "Frnace", ("country/FRA",), source="synthetic", category="typo"
    )

    rows = [cldr_row, synth_row]
    result = _drop_synthetic_cross_source_collisions(rows)

    assert len(result) == 2
