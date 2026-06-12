"""Regression tests for iso_numeric zero-padding bugs (#2, #4) and aliases dedup (#12).

#2: iso_numeric codes stored unpadded — lookups and emission must handle padding.
#4: EntityRecord.numeric looked up 'numeric' key instead of 'iso_numeric'.
#12: EntityRecord.aliases leaked canonical name and duplicates.
"""

from __future__ import annotations

import pytest

from resolvekit.core.api.code_lookup import (
    _CODE_SYSTEM_PRIORITY,
    _iso_numeric_lookup_value,
)
from resolvekit.core.model.entity import CodeRecord, EntityRecord, NameRecord

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_country(
    *,
    entity_id: str,
    canonical_name: str,
    iso_numeric: str | None = None,
    extra_names: list[tuple[str, bool]] | None = None,
) -> EntityRecord:
    """Build a minimal EntityRecord with iso_numeric stored unpadded (as bundled data does)."""
    codes: list[CodeRecord] = []
    if iso_numeric is not None:
        codes.append(
            CodeRecord(
                system="iso_numeric",
                value=iso_numeric,
                value_norm=iso_numeric,
            )
        )
    names: list[NameRecord] = []
    for value, is_preferred in extra_names or []:
        names.append(
            NameRecord(
                value=value,
                value_norm=value.lower(),
                kind="alias",
                is_preferred=is_preferred,
            )
        )
    return EntityRecord(
        entity_id=entity_id,
        entity_type="geo.country",
        canonical_name=canonical_name,
        canonical_name_norm=canonical_name.lower(),
        codes=codes,
        names=names,
    )


# ---------------------------------------------------------------------------
# Finding #2 — iso_numeric zero-padding: _iso_numeric_lookup_value helper
# ---------------------------------------------------------------------------


class TestIsoNumericLookupValue:
    def test_padded_input_strips_leading_zeros(self) -> None:
        assert _iso_numeric_lookup_value("004") == "4"

    def test_unpadded_input_unchanged(self) -> None:
        assert _iso_numeric_lookup_value("4") == "4"

    def test_three_digit_no_leading_zeros_unchanged(self) -> None:
        assert _iso_numeric_lookup_value("840") == "840"

    def test_two_leading_zeros_stripped(self) -> None:
        assert _iso_numeric_lookup_value("004") == "4"
        assert _iso_numeric_lookup_value("040") == "40"

    def test_all_zeros_returns_zero(self) -> None:
        assert _iso_numeric_lookup_value("000") == "0"

    def test_already_unpadded_250(self) -> None:
        assert _iso_numeric_lookup_value("250") == "250"


# ---------------------------------------------------------------------------
# Finding #2 — iso_numeric zero-padding: codes_dict emission
# ---------------------------------------------------------------------------


class TestCodesDictIsoNumericPadding:
    def test_unpadded_4_emits_padded_004(self) -> None:
        """Afghanistan stored as '4'; codes_dict must return '004'."""
        entity = _make_country(
            entity_id="country/AFG",
            canonical_name="Afghanistan",
            iso_numeric="4",
        )
        assert entity.codes_dict["iso_numeric"] == "004"

    def test_unpadded_40_emits_padded_040(self) -> None:
        entity = _make_country(
            entity_id="country/TEST",
            canonical_name="Test",
            iso_numeric="40",
        )
        assert entity.codes_dict["iso_numeric"] == "040"

    def test_already_padded_250_unchanged(self) -> None:
        """France stored as '250' (no leading zeros needed)."""
        entity = _make_country(
            entity_id="country/FRA",
            canonical_name="France",
            iso_numeric="250",
        )
        assert entity.codes_dict["iso_numeric"] == "250"

    def test_code_method_returns_padded(self) -> None:
        entity = _make_country(
            entity_id="country/AFG",
            canonical_name="Afghanistan",
            iso_numeric="4",
        )
        assert entity.code("iso_numeric") == "004"

    def test_non_iso_numeric_systems_unaffected(self) -> None:
        """iso2, iso3, wikidata etc. are NOT zero-padded."""
        from resolvekit.core.model.entity import CodeRecord

        entity = EntityRecord(
            entity_id="country/USA",
            entity_type="geo.country",
            canonical_name="United States",
            canonical_name_norm="united states",
            codes=[
                CodeRecord(system="iso2", value="US", value_norm="us"),
                CodeRecord(system="iso3", value="USA", value_norm="usa"),
                CodeRecord(system="iso_numeric", value="840", value_norm="840"),
            ],
        )
        assert entity.codes_dict["iso2"] == "US"
        assert entity.codes_dict["iso3"] == "USA"
        assert entity.codes_dict["iso_numeric"] == "840"


# ---------------------------------------------------------------------------
# Finding #4 — EntityRecord.numeric must read 'iso_numeric', not 'numeric'
# ---------------------------------------------------------------------------


class TestEntityNumericProperty:
    def test_numeric_returns_padded_value_from_iso_numeric_system(self) -> None:
        entity = _make_country(
            entity_id="country/FRA",
            canonical_name="France",
            iso_numeric="250",
        )
        assert entity.numeric == "250"

    def test_numeric_returns_padded_for_single_digit_code(self) -> None:
        entity = _make_country(
            entity_id="country/AFG",
            canonical_name="Afghanistan",
            iso_numeric="4",
        )
        assert entity.numeric == "004"

    def test_numeric_returns_none_when_absent(self) -> None:
        entity = _make_country(
            entity_id="country/XXX",
            canonical_name="No Numeric",
        )
        assert entity.numeric is None

    def test_numeric_is_not_read_from_system_named_numeric(self) -> None:
        """Old bug: .numeric looked for system='numeric'; must not return that."""
        from resolvekit.core.model.entity import CodeRecord

        entity = EntityRecord(
            entity_id="country/XXX",
            entity_type="geo.country",
            canonical_name="Old Bug",
            canonical_name_norm="old bug",
            codes=[
                CodeRecord(system="numeric", value="999", value_norm="999"),
            ],
        )
        # system='numeric' is NOT 'iso_numeric', so .numeric must return None
        assert entity.numeric is None

    def test_numeric_reads_iso_numeric_system(self) -> None:
        """Correct system name is 'iso_numeric'."""
        from resolvekit.core.model.entity import CodeRecord

        entity = EntityRecord(
            entity_id="country/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            codes=[
                CodeRecord(system="iso_numeric", value="250", value_norm="250"),
            ],
        )
        assert entity.numeric == "250"


# ---------------------------------------------------------------------------
# Finding #2 — _CODE_SYSTEM_PRIORITY: 'iso_numeric' not 'numeric'
# ---------------------------------------------------------------------------


class TestCodeSystemPriority:
    def test_iso_numeric_in_priority_list(self) -> None:
        assert "iso_numeric" in _CODE_SYSTEM_PRIORITY

    def test_dead_numeric_not_in_priority_list(self) -> None:
        assert "numeric" not in _CODE_SYSTEM_PRIORITY

    def test_iso_numeric_before_dcid_and_wikidata(self) -> None:
        idx_iso_numeric = _CODE_SYSTEM_PRIORITY.index("iso_numeric")
        idx_dcid = _CODE_SYSTEM_PRIORITY.index("dcid")
        idx_wikidata = _CODE_SYSTEM_PRIORITY.index("wikidata")
        assert idx_iso_numeric < idx_dcid
        assert idx_iso_numeric < idx_wikidata


# ---------------------------------------------------------------------------
# Finding #12 — EntityRecord.aliases deduplication
# ---------------------------------------------------------------------------


class TestEntityAliasesDedup:
    def test_canonical_name_excluded_from_aliases(self) -> None:
        entity = _make_country(
            entity_id="country/FRA",
            canonical_name="France",
            extra_names=[
                ("France", False),  # canonical value as non-preferred record
                ("République française", False),
            ],
        )
        assert "France" not in entity.aliases

    def test_duplicate_alias_values_deduplicated(self) -> None:
        entity = _make_country(
            entity_id="country/CUB",
            canonical_name="Cuba",
            extra_names=[
                ("Cuba", False),
                ("Cuba", False),
                ("Cuba", False),
                ("Cuba", False),
                ("Cuba", False),
            ],
        )
        assert entity.aliases.count("Cuba") == 0  # also excluded as canonical

    def test_genuine_aliases_preserved(self) -> None:
        entity = _make_country(
            entity_id="country/DEU",
            canonical_name="Germany",
            extra_names=[
                ("Deutschland", False),
                ("Allemagne", False),
                ("Germany", False),  # same as canonical — must be excluded
            ],
        )
        assert "Deutschland" in entity.aliases
        assert "Allemagne" in entity.aliases
        assert "Germany" not in entity.aliases

    def test_preferred_names_excluded(self) -> None:
        entity = _make_country(
            entity_id="country/XXX",
            canonical_name="Test",
            extra_names=[
                ("Preferred Alt", True),  # is_preferred=True
                ("Real Alias", False),
            ],
        )
        assert "Preferred Alt" not in entity.aliases
        assert "Real Alias" in entity.aliases

    def test_duplicate_non_canonical_values_deduplicated(self) -> None:
        entity = _make_country(
            entity_id="country/IND",
            canonical_name="India",
            extra_names=[
                ("Bharat", False),
                ("Bharat", False),  # duplicate non-canonical
                ("भारत", False),
            ],
        )
        assert entity.aliases.count("Bharat") == 1
        assert "भारत" in entity.aliases

    def test_order_preserved_first_occurrence_wins(self) -> None:
        entity = _make_country(
            entity_id="country/XXX",
            canonical_name="Test",
            extra_names=[
                ("Alpha", False),
                ("Beta", False),
                ("Alpha", False),  # duplicate, should be dropped
                ("Gamma", False),
            ],
        )
        assert entity.aliases == ["Alpha", "Beta", "Gamma"]

    def test_empty_names_list(self) -> None:
        entity = _make_country(
            entity_id="country/XXX",
            canonical_name="Test",
        )
        assert entity.aliases == []


# ---------------------------------------------------------------------------
# Integration: entity().numeric and entity().aliases against live bundled data
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLiveBundledData:
    """Probes against the actual bundled geo.countries pack."""

    @pytest.fixture(scope="class")
    def resolver(self):
        from resolvekit.core.api.resolver import Resolver

        return Resolver.from_modules(module_ids=["geo.countries"])

    def test_france_numeric_is_padded(self, resolver) -> None:
        e = resolver.entity("France")
        assert e is not None
        assert e.numeric == "250"

    def test_afghanistan_numeric_is_zero_padded(self, resolver) -> None:
        e = resolver.entity("Afghanistan")
        assert e is not None
        assert e.numeric == "004"

    def test_resolve_to_iso_numeric_emits_padded(self, resolver) -> None:
        assert resolver.resolve("Afghanistan", to="iso_numeric") == "004"
        assert resolver.resolve("France", to="iso_numeric") == "250"

    def test_resolve_id_from_system_iso_numeric_padded(self, resolver) -> None:
        assert resolver.resolve_id("004", from_system="iso_numeric") == "country/AFG"
        assert resolver.resolve_id("4", from_system="iso_numeric") == "country/AFG"
        assert resolver.resolve_id("250", from_system="iso_numeric") == "country/FRA"

    def test_germany_canonical_not_in_aliases(self, resolver) -> None:
        e = resolver.entity("Germany")
        assert e is not None
        assert e.canonical_name not in e.aliases

    def test_germany_aliases_no_duplicates(self, resolver) -> None:
        e = resolver.entity("Germany")
        assert e is not None
        assert len(e.aliases) == len(set(e.aliases))

    def test_cuba_canonical_not_in_aliases(self, resolver) -> None:
        e = resolver.entity("Cuba")
        assert e is not None
        assert e.canonical_name not in e.aliases
        assert e.aliases.count(e.canonical_name) == 0

    def test_france_canonical_not_in_aliases(self, resolver) -> None:
        e = resolver.entity("France")
        assert e is not None
        assert e.canonical_name not in e.aliases
