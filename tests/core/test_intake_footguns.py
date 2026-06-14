"""Tests for intake footguns: ragged link_on columns and name-strategy guard.

Covers the behaviour of ``RecordSchema.resolve``:
  - ``avail`` is the UNION of keys across ALL rows, not just ``rows[0]``.
  - A code column absent from a particular row at runtime produces no link for
    that row and routes it to on_miss (existing build-loop behaviour).
  - ``link_on=['name']`` with neither add_aliases nor add_codes raises a clear
    ValueError (guard in ``_infer_augment_schema:80``).

Schema-level tests use ``RecordSchema.resolve`` directly. Tests here use the
private helper (``_infer_augment_schema``) to stay independent of the full
augment() path.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from resolvekit.core.api._byod import _infer_augment_schema
from resolvekit.core.byod.intake import RecordSchema

# ---------------------------------------------------------------------------
# Minimal stub normalizer (mirrors test_byod_intake.py)
# ---------------------------------------------------------------------------


@dataclass
class _IdentityNormalizer:
    """Normalizer that lower-cases values unchanged."""

    def normalize_name(self, name: str) -> str:
        return name.lower()

    def normalize_code(self, system: str, value: str) -> str:
        return value.lower()


_NORM = _IdentityNormalizer()


# ---------------------------------------------------------------------------
# 1a — link column present in row 0, absent in row 2 → row 2 routes to on_miss
# ---------------------------------------------------------------------------


class TestRaggedLinkColPresentInRow0AbsentLater:
    """Row 0 has the link column; a later row does not.

    The avail-union change must not break this already-working case: schema
    validation passed (row 0 had the column) and per-record extraction already
    routed rows lacking the column to on_miss via the build-loop's link_keys
    filter.  Test confirms no regression from the union-avail change.
    """

    def test_schema_allows_col_missing_from_later_row(self) -> None:
        """avail union must not REJECT a column that a later row happens to omit."""
        rows = [
            {"name": "Alpha", "iso3": "AAA"},
            {"name": "Beta", "iso3": "BBB"},
            {"name": "Gamma"},  # iso3 absent — ragged
        ]
        # Must not raise even though row 2 lacks iso3.
        schema = RecordSchema.resolve(rows, name="name", codes=["iso3"])
        assert schema.codes == {"iso3": "iso3"}

    def test_record_without_link_col_has_empty_codes(self) -> None:
        """row_to_record for the ragged row produces no iso3 code."""
        rows = [
            {"name": "Alpha", "iso3": "AAA"},
            {"name": "Gamma"},  # iso3 absent
        ]
        schema = RecordSchema.resolve(rows, name="name", codes=["iso3"])
        record_with = schema.row_to_record(rows[0], normalizer=_NORM)
        record_without = schema.row_to_record(rows[1], normalizer=_NORM)
        assert record_with.codes == {"iso3": "AAA"}
        # Row without iso3 gets empty codes — the build loop routes it to on_miss.
        assert "iso3" not in record_without.codes

    def test_known_systems_inference_allows_later_only_col(self) -> None:
        """Inferred codes via known_systems work for columns absent in row 0."""
        rows = [
            {"name": "Alpha"},  # iso3 absent in row 0
            {"name": "Beta", "iso3": "BBB"},
        ]
        # Old code: avail = {"name"} → iso3 not inferred.
        # New code: avail = {"name", "iso3"} → iso3 inferred as a code.
        schema = RecordSchema.resolve(
            rows,
            name="name",
            known_systems=frozenset({"iso3"}),
        )
        assert "iso3" in schema.codes


# ---------------------------------------------------------------------------
# 1b — link column absent in row 0, present in row 2 → union fires, col recognised
# ---------------------------------------------------------------------------


class TestRaggedLinkColAbsentInRow0PresentLater:
    """Row 0 lacks the link column; a later row has it.

    Old behaviour: ``avail = set(rows[0].keys())`` → iso3 not in avail →
    ``RecordSchema.resolve`` raised ``ValueError: codes column 'iso3' not found``
    even though iso3 was present in later rows.

    New behaviour: avail is the union of all rows → iso3 is found → schema
    resolves; row 0 produces no iso3 code and routes to on_miss; later rows link.
    """

    def test_schema_recognises_col_only_in_later_row(self) -> None:
        """The union-avail fix must NOT raise when the column appears only after row 0."""
        rows = [
            {"name": "Unknown"},  # iso3 absent in row 0
            {"name": "France", "iso3": "FRA"},
        ]
        # Old code raised ValueError here; new code must succeed.
        schema = RecordSchema.resolve(rows, name="name", codes=["iso3"])
        assert "iso3" in schema.codes

    def test_row0_without_col_has_empty_codes(self) -> None:
        """row_to_record for the leading ragged row produces no iso3 code."""
        rows = [
            {"name": "Unknown"},
            {"name": "France", "iso3": "FRA"},
        ]
        schema = RecordSchema.resolve(rows, name="name", codes=["iso3"])
        rec_ragged = schema.row_to_record(rows[0], normalizer=_NORM)
        rec_with = schema.row_to_record(rows[1], normalizer=_NORM)
        assert "iso3" not in rec_ragged.codes
        assert rec_with.codes == {"iso3": "FRA"}

    def test_known_systems_inference_union(self) -> None:
        """Inferred codes (via known_systems) also use the union of all rows."""
        rows = [
            {"name": "Unknown"},  # iso3 absent in row 0
            {"name": "France", "iso3": "FRA"},
        ]
        schema = RecordSchema.resolve(
            rows,
            name="name",
            known_systems=frozenset({"iso3"}),
        )
        # iso3 must be inferred as a code despite being absent from row 0.
        assert "iso3" in schema.codes

    def test_dict_form_codes_also_uses_union(self) -> None:
        """dict-form codes= also benefit from the union avail."""
        rows = [
            {"name": "Unknown"},
            {"name": "France", "country_code": "FRA"},
        ]
        # dict-form: {system: actual_column}; column is "country_code"
        schema = RecordSchema.resolve(rows, name="name", codes={"iso3": "country_code"})
        assert schema.codes == {"iso3": "country_code"}
        rec_ragged = schema.row_to_record(rows[0], normalizer=_NORM)
        rec_france = schema.row_to_record(rows[1], normalizer=_NORM)
        assert "iso3" not in rec_ragged.codes
        assert rec_france.codes == {"iso3": "FRA"}

    def test_empty_rows_avail_stays_empty(self) -> None:
        """Empty row list still produces an empty avail (no KeyError)."""
        schema = RecordSchema.resolve([], name="name")
        assert schema.names == ["name"]

    def test_all_rows_ragged_different_columns(self) -> None:
        """When every row has a different column set, union covers all."""
        rows = [
            {"name": "Alpha", "iso3": "AAA"},
            {"name": "Beta", "iso2": "BB"},
            {"name": "Gamma", "wikidata": "Q999"},
        ]
        schema = RecordSchema.resolve(
            rows,
            name="name",
            known_systems=frozenset({"iso3", "iso2", "wikidata"}),
        )
        # All three systems must be inferred via the union.
        assert "iso3" in schema.codes
        assert "iso2" in schema.codes
        assert "wikidata" in schema.codes


# ---------------------------------------------------------------------------
# 2 — name strategy without add_aliases raises a clear error
# ---------------------------------------------------------------------------


class TestNameStrategyFootgun:
    """link_on=['name'] without add_aliases and without add_codes raises ValueError.

    The guard lives in ``_infer_augment_schema:80`` (``_byod.py``) and was
    already in place before Slice 3.4.  Tests here confirm it via the private
    helper directly (mirrors ``test_byod_schema_inference.py`` style) to keep
    the test independent of the full augment() path.
    """

    def test_link_on_name_no_aliases_no_codes_raises(self) -> None:
        """link_on=['name'] with neither add_aliases nor add_codes → clear ValueError."""
        with pytest.raises(ValueError, match="link_on=\\['name'\\]"):
            _infer_augment_schema(
                link_on=["name"],
                add_aliases=None,
                add_codes=None,
            )

    def test_error_message_mentions_add_aliases(self) -> None:
        """The error message must name add_aliases as a remedy."""
        with pytest.raises(ValueError, match="add_aliases"):
            _infer_augment_schema(
                link_on=["name"],
                add_aliases=None,
                add_codes=None,
            )

    def test_link_on_name_with_add_aliases_accepted(self) -> None:
        """link_on=['name'] WITH add_aliases must not raise."""
        name_col, codes = _infer_augment_schema(
            link_on=["name"],
            add_aliases="local_name",
            add_codes=None,
        )
        assert name_col == "local_name"
        assert codes is None  # no code columns

    def test_link_on_name_with_add_codes_accepted(self) -> None:
        """link_on=['name'] WITH add_codes must not raise; name_col inferred from codes."""
        name_col, codes = _infer_augment_schema(
            link_on=["name"],
            add_aliases=None,
            add_codes=["iso3"],
        )
        # First code column becomes name proxy when no add_aliases given.
        assert name_col == "iso3"
        assert codes == ["iso3"]
