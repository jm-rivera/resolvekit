"""Regression tests for resolver entry-point validation.

Covers:
- #8:  resolve_id(on_ambiguous=<typo>) raises a named ValueError eagerly.
- #14: domain= under AUTO routing raises an actionable, public-API message
       (no internal RoutingMode enum reference).
- #15: as_of= on members_of/is_member/related/within coerces ISO date strings
       and raises a clear ValueError on bad strings.
- #23: available_entity_types() returns fine-grained types accepted by
       ResolutionContext(entity_types=...).
- #32: parse(confidence_threshold=<non-numeric / out-of-range>) raises eagerly.
- #33: parse(domain=<unknown>) raises UnknownDomainError, like resolve().
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from resolvekit.core.api.query_prep import _auto_routing_domain_error
from resolvekit.core.api.resolver import (
    _coerce_as_of,
    _on_ambiguous_error,
    _validate_confidence_threshold,
)
from resolvekit.core.errors import UnknownDomainError


class TestAutoRoutingDomainMessage:
    def test_message_is_actionable_for_public_api(self) -> None:
        msg = _auto_routing_domain_error()
        # Must NOT reference the internal, non-public RoutingMode enum.
        assert "RoutingMode" not in msg
        # Must name the public string spelling and a real constructor.
        assert 'routing_mode="explicit"' in msg
        assert "Resolver" in msg


# ---------------------------------------------------------------------------
# Pure-helper unit tests (no data needed)
# ---------------------------------------------------------------------------


class TestOnAmbiguousValidation:
    def test_error_message_lists_valid_options(self) -> None:
        msg = _on_ambiguous_error("Raise")
        assert "'raise'" in msg
        assert "'null'" in msg
        assert "'best'" in msg

    def test_error_message_suggests_close_match(self) -> None:
        assert "did you mean 'raise'" in _on_ambiguous_error("Raise")


class TestCoerceAsOf:
    def test_none_passes_through(self) -> None:
        assert _coerce_as_of(None) is None

    def test_date_passes_through(self) -> None:
        d = date(2020, 1, 1)
        assert _coerce_as_of(d) is d

    def test_iso_string_coerced(self) -> None:
        assert _coerce_as_of("2020-01-01") == date(2020, 1, 1)

    def test_bad_string_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="not a valid ISO date"):
            _coerce_as_of("not-a-date")

    def test_non_string_non_date_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="as_of must be"):
            _coerce_as_of(20200101)  # type: ignore[arg-type]


class TestConfidenceThresholdValidation:
    def test_none_ok(self) -> None:
        _validate_confidence_threshold(None)

    def test_in_range_float_ok(self) -> None:
        _validate_confidence_threshold(0.9)

    def test_string_raises(self) -> None:
        with pytest.raises(ValueError, match=r"confidence_threshold='0\.9'"):
            _validate_confidence_threshold("0.9")

    def test_bool_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence_threshold"):
            _validate_confidence_threshold(True)

    def test_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            _validate_confidence_threshold(5.0)


# ---------------------------------------------------------------------------
# Integration tests against the synthetic geo fixture
# ---------------------------------------------------------------------------


class TestResolveIdOnAmbiguousValidation:
    @pytest.fixture
    def resolver(self, geo_test_datapack: Any) -> Any:
        from resolvekit.core.api.resolver import Resolver

        r = Resolver.from_datapacks(datapack_paths=[geo_test_datapack])
        yield r
        r.close()

    def test_typo_raises_before_resolution(self, resolver: Any) -> None:
        with pytest.raises(ValueError, match="on_ambiguous='Raise'"):
            resolver.resolve_id("United States", on_ambiguous="Raise")

    def test_valid_values_do_not_raise_validation(self, resolver: Any) -> None:
        # "null" / "best" never raise the validation error.
        assert resolver.resolve_id("United States", on_ambiguous="null") is not None
        assert resolver.resolve_id("United States", on_ambiguous="best") is not None


class TestParseValidation:
    @pytest.fixture
    def resolver(self, geo_test_datapack: Any) -> Any:
        from resolvekit.core.api.resolver import Resolver

        r = Resolver.from_datapacks(datapack_paths=[geo_test_datapack])
        yield r
        r.close()

    def test_parse_unknown_domain_raises(self, resolver: Any) -> None:
        with pytest.raises(UnknownDomainError):
            resolver.parse("United States", domain="xyz")

    def test_parse_bad_confidence_threshold_raises_eagerly(self, resolver: Any) -> None:
        # Eager: raises even when no span would resolve.
        with pytest.raises(ValueError, match="confidence_threshold"):
            resolver.parse("zzzz qqqq", confidence_threshold="0.9")

    def test_parse_bulk_unknown_domain_raises(self, resolver: Any) -> None:
        with pytest.raises(UnknownDomainError):
            resolver.parse_bulk(values=["United States"], domain="xyz")


# ---------------------------------------------------------------------------
# Integration tests requiring bundled module data
# ---------------------------------------------------------------------------


def _bundled_geo_available() -> bool:
    try:
        from resolvekit import Resolver

        r = Resolver.from_modules(module_ids=["geo.countries"])
        r.close()
        return True
    except Exception:
        return False


_BUNDLED = _bundled_geo_available()
bundled = pytest.mark.skipif(
    not _BUNDLED, reason="bundled geo module data not available"
)


@bundled
class TestAvailableEntityTypes:
    def test_returns_full_dotted_types(self) -> None:
        from resolvekit import Resolver

        r = Resolver.from_modules(module_ids=["geo.countries"])
        try:
            types = r.available_entity_types()
            assert "geo.country" in types
            assert "geo" not in types
        finally:
            r.close()

    def test_values_accepted_by_entity_types_filter(self) -> None:
        from resolvekit import ResolutionContext, Resolver

        r = Resolver.lite()
        try:
            types = r.available_entity_types()
            ctx = ResolutionContext(entity_types=list(types))
            result = r.resolve("France", context=ctx, as_result=True)
            assert result.status.value == "resolved"
        finally:
            r.close()


def _geo_unions_have_members() -> bool:
    try:
        from resolvekit import Resolver

        r = Resolver.from_modules(
            module_ids=["geo.countries", "geo.continental_unions"]
        )
        try:
            return len(r.members_of("European Union")) > 0
        finally:
            r.close()
    except Exception:
        return False


_UNIONS = _geo_unions_have_members()
unions = pytest.mark.skipif(
    not _UNIONS, reason="bundled continental-union membership data not available"
)


@unions
class TestRelationshipAsOfCoercion:
    @pytest.fixture(scope="class")
    def resolver(self):  # type: ignore[no-untyped-def]
        from resolvekit import Resolver

        r = Resolver.from_modules(
            module_ids=["geo.countries", "geo.continental_unions"]
        )
        yield r
        r.close()

    def test_members_of_accepts_iso_string(self, resolver: Any) -> None:
        from_str = resolver.members_of("European Union", as_of="2020-01-01")
        from_date = resolver.members_of("European Union", as_of=date(2020, 1, 1))
        assert from_str == from_date

    def test_members_of_bad_date_raises(self, resolver: Any) -> None:
        with pytest.raises(ValueError, match="not a valid ISO date"):
            resolver.members_of("European Union", as_of="not-a-date")

    def test_is_member_accepts_iso_string(self, resolver: Any) -> None:
        # Should not raise an internals-deep AttributeError.
        resolver.is_member("France", "European Union", as_of="2020-01-01")
