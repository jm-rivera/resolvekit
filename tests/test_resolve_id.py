"""resolve_id on_ambiguous kwarg tests.

Tests for the Resolver.resolve_id() on_ambiguous parameter:
- "raise" (default): raises AmbiguousResolutionError
- "null": returns None on AMBIGUOUS
- "best": returns the top candidate's entity_id
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from resolvekit.core.errors import AmbiguousResolutionError
from resolvekit.core.model import (
    CandidateSummary,
    ResolutionResult,
    ResolutionStatus,
)


def _make_ambiguous_result(top_id: str = "country/USA") -> ResolutionResult:
    """Build a minimal AMBIGUOUS result."""
    return ResolutionResult(
        query_text="United",
        status=ResolutionStatus.AMBIGUOUS,
        entity_id=None,
        confidence=None,
        candidates=[
            CandidateSummary(entity_id=top_id, confidence=0.7),
            CandidateSummary(entity_id="country/GBR", confidence=0.6),
        ],
    )


class TestResolveIdOnAmbiguous:
    """Tests for Resolver.resolve_id on_ambiguous parameter."""

    @pytest.fixture
    def resolver(self, geo_test_datapack: Any) -> Any:
        """Resolver backed by the minimal geo fixture."""
        from resolvekit.core.api.resolver import Resolver

        return Resolver.from_datapacks(datapack_paths=[geo_test_datapack])

    def test_resolved_returns_entity_id(self, resolver: Any) -> None:
        """RESOLVED result returns the entity_id."""
        result = resolver.resolve_id("United States")
        assert result == "country/USA"

    def test_no_match_returns_none(self, resolver: Any) -> None:
        """NO_MATCH result returns None."""
        result = resolver.resolve_id("xyzzy_no_such_entity_12345")
        assert result is None

    def test_default_on_ambiguous_raises(self, resolver: Any) -> None:
        """Default on_ambiguous='raise' raises AmbiguousResolutionError."""
        # Mock resolve() to return an AMBIGUOUS result
        ambiguous = _make_ambiguous_result()
        with (
            patch.object(resolver, "resolve", return_value=ambiguous),
            pytest.raises(AmbiguousResolutionError),
        ):
            resolver.resolve_id("United")

    def test_on_ambiguous_null_returns_none(self, resolver: Any) -> None:
        """on_ambiguous='null' returns None for AMBIGUOUS results."""
        ambiguous = _make_ambiguous_result()
        with patch.object(resolver, "resolve", return_value=ambiguous):
            result = resolver.resolve_id("United", on_ambiguous="null")
        assert result is None

    def test_on_ambiguous_best_returns_top_candidate(self, resolver: Any) -> None:
        """on_ambiguous='best' returns the top candidate's entity_id."""
        ambiguous = _make_ambiguous_result(top_id="country/USA")
        with patch.object(resolver, "resolve", return_value=ambiguous):
            result = resolver.resolve_id("United", on_ambiguous="best")
        assert result == "country/USA"

    def test_on_ambiguous_best_empty_candidates_returns_none(
        self, resolver: Any
    ) -> None:
        """on_ambiguous='best' with no candidates returns None."""
        empty_ambiguous = ResolutionResult(
            query_text="United",
            status=ResolutionStatus.AMBIGUOUS,
            entity_id=None,
            candidates=[],
        )
        with patch.object(resolver, "resolve", return_value=empty_ambiguous):
            result = resolver.resolve_id("United", on_ambiguous="best")
        assert result is None


class TestModuleLevelResolveId:
    """Tests for module-level resolvekit.resolve_id."""

    def test_resolve_id_returns_string(self) -> None:
        """Module-level resolve_id returns a string for a known entity."""
        import resolvekit

        result = resolvekit.resolve_id("United States")
        assert isinstance(result, str)
        assert result == "country/USA"

    def test_resolve_id_returns_none_for_no_match(self) -> None:
        """Module-level resolve_id returns None for no match."""
        import resolvekit

        result = resolvekit.resolve_id("xyzzy_no_such_entity_99999")
        assert result is None

    def test_resolve_id_on_ambiguous_null_at_module_level(self) -> None:
        """Module-level resolve_id(on_ambiguous='null') returns None on AMBIGUOUS."""
        import resolvekit

        mock_resolver = MagicMock()
        mock_resolver.resolve_id.return_value = None

        with patch("resolvekit._convenience._get_default", return_value=mock_resolver):
            result = resolvekit.resolve_id("United", on_ambiguous="null")

        mock_resolver.resolve_id.assert_called_once_with(
            "United",
            on_ambiguous="null",
            from_system=None,
            domain=None,
            context=None,
            timeout=None,
        )
        assert result is None


class TestResolveIdIntegration:
    """Integration tests using the real resolver pipeline."""

    @pytest.fixture
    def resolver(self, geo_test_datapack: Any) -> Any:
        from resolvekit.core.api.resolver import Resolver

        return Resolver.from_datapacks(datapack_paths=[geo_test_datapack])

    def test_raise_is_default(self, resolver: Any) -> None:
        """Default behavior is on_ambiguous='raise'."""
        import inspect as _inspect

        sig = _inspect.signature(resolver.resolve_id)
        default = sig.parameters["on_ambiguous"].default
        assert default == "raise"

    def test_resolve_id_iso2_known(self, resolver: Any) -> None:
        """resolve_id on a known ISO-2 code returns the entity_id."""
        result = resolver.resolve_id("US")
        assert result == "country/USA"

    def test_resolve_id_lowercase_iso2_with_from_system(self, resolver: Any) -> None:
        """Lowercase ISO-2 resolves when ``from_system`` is explicit.

        The shape regex in ``code_lookup`` is case-insensitive, so the
        ``from_system="iso2"`` short-circuit accepts lowercase. Ambient
        ``resolve_id("us")`` without ``from_system`` is still gated by the
        geo pack's ``short_alpha_code_allowed`` — that's a separate policy.
        """
        assert resolver.resolve_id("us", from_system="iso2") == "country/USA"

    def test_resolve_id_lowercase_iso3_with_from_system(self, resolver: Any) -> None:
        assert resolver.resolve_id("usa", from_system="iso3") == "country/USA"
