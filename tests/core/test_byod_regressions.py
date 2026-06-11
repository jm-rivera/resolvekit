"""Regression tests for BYOD bugs #18 and #19.

#18: from_records with an empty/whitespace name cell must raise a clear
     ValueError naming the record index and column, not an opaque RuntimeError.

#19: BYOD custom packs must be reachable by labels containing NFKC-
     compatibility characters (™, ℠, №, ²) because both build-time and
     query-time normalization now use NFC + casefold.
"""

from __future__ import annotations

import pytest

from resolvekit.core.api.resolver import Resolver

# ---------------------------------------------------------------------------
# #18 — empty/whitespace name raises clear ValueError
# ---------------------------------------------------------------------------


class TestEmptyNameCell:
    def test_empty_string_raises_value_error(self) -> None:
        """from_records where the name column is '' raises ValueError naming row 1."""
        with pytest.raises(ValueError, match="record 1") as exc_info:
            Resolver.from_records(
                [{"id": "a", "label": "Alpha"}, {"id": "b", "label": ""}],
                domain="custom",
                name="label",
                id="id",
                cache=False,
            )
        assert "label" in str(exc_info.value)

    def test_whitespace_only_raises_value_error(self) -> None:
        """from_records where the name column is '   ' (whitespace) raises ValueError."""
        with pytest.raises(ValueError, match="record 0"):
            Resolver.from_records(
                [{"id": "a", "label": "   "}],
                domain="custom",
                name="label",
                id="id",
                cache=False,
            )

    def test_error_is_not_runtime_error(self) -> None:
        """The error must be ValueError, not RuntimeError (internal builder type)."""
        with pytest.raises(ValueError):
            Resolver.from_records(
                [{"id": "x", "label": ""}],
                domain="custom",
                name="label",
                id="id",
                cache=False,
            )

    def test_valid_records_unaffected(self) -> None:
        """Non-empty names still build and resolve normally."""
        r = Resolver.from_records(
            [{"id": "w1", "label": "Widget"}],
            domain="custom",
            name="label",
            id="id",
            cache=False,
        )
        result = r.resolve("Widget")
        assert result.entity_id == "custom/w1"

    def test_error_message_names_the_column(self) -> None:
        """The ValueError message must mention the name column used."""
        with pytest.raises(ValueError, match="my_name_col") as exc_info:
            Resolver.from_records(
                [{"id": "a", "my_name_col": ""}],
                domain="custom",
                name="my_name_col",
                id="id",
                cache=False,
            )
        _ = exc_info  # accessed above via match=


# ---------------------------------------------------------------------------
# #19 — NFKC-compatibility characters round-trip correctly
# ---------------------------------------------------------------------------


class TestNfkcCompatibilityRoundtrip:
    def test_trademark_symbol_exact_label_resolves(self) -> None:
        """Resolver built with 'Acme™ Corp' resolves the exact stored label."""
        r = Resolver.from_records(
            [{"id": "w1", "label": "Acme™ Corp"}],
            domain="custom",
            name="label",
            id="id",
            cache=False,
        )
        result = r.resolve("Acme™ Corp")
        assert result.entity_id == "custom/w1", (
            f"exact stored label should resolve; status={result.status}"
        )

    def test_service_mark_symbol_resolves(self) -> None:
        """'Widget℠' stored label is reachable by its exact form."""
        r = Resolver.from_records(
            [{"id": "w1", "label": "Widget℠"}],
            domain="custom",
            name="label",
            id="id",
            cache=False,
        )
        result = r.resolve("Widget℠")
        assert result.entity_id == "custom/w1", (
            f"exact stored label should resolve; status={result.status}"
        )

    def test_plain_ascii_name_still_resolves(self) -> None:
        """Existing round-trips for plain ASCII names are unchanged."""
        r = Resolver.from_records(
            [{"id": "p1", "label": "Plain Name"}],
            domain="custom",
            name="label",
            id="id",
            cache=False,
        )
        result = r.resolve("Plain Name")
        assert result.entity_id == "custom/p1"

    def test_diacritic_name_still_resolves(self) -> None:
        """Names with diacritics (á, é, ü) are unaffected by the NFC fix."""
        r = Resolver.from_records(
            [{"id": "d1", "label": "Café Résumé"}],
            domain="custom",
            name="label",
            id="id",
            cache=False,
        )
        result = r.resolve("Café Résumé")
        assert result.entity_id == "custom/d1"

    def test_case_insensitive_resolve_still_works(self) -> None:
        """Case-insensitive resolution is preserved after the NFC normalizer change."""
        r = Resolver.from_records(
            [{"id": "c1", "label": "Widget"}],
            domain="custom",
            name="label",
            id="id",
            cache=False,
        )
        result = r.resolve("widget")
        assert result.entity_id == "custom/c1"
