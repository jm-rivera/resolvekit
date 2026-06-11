"""Tests for the sentinel blocklist."""

import pytest

from resolvekit.core.util.sentinel import DEFAULT_BLOCKLIST, SentinelBlocklist


class TestSentinelBlocklistDefaults:
    """DEFAULT_BLOCKLIST blocks all expected junk forms."""

    @pytest.mark.parametrize(
        "text",
        [
            # Placeholders (exact case)
            "unknown",
            "none",
            "null",
            "n/a",
            "n.a.",
            "not applicable",
            "not available",
            "undefined",
            "unspecified",
            # Workflow
            "tbd",
            "tba",
            "pending",
            # Generic catch-all
            "various",
            "other",
            "others",
            "misc",
            "worldwide",
            "international",
            # Test junk phrases
            "test",
            "testing",
            "test string",
            "foo bar",
            "lorem ipsum",
            "qwerty",
            "asdf",
            "asdfghjkl",
            "zxcvbnm",
            "xkcd",
            # Punctuation separators
            "---",
            "...",
            "###",
            "????",
            # Pure-digit junk
            "000",
            "999",
            "00",
        ],
    )
    def test_blocked(self, text: str) -> None:
        assert DEFAULT_BLOCKLIST.is_blocked(text), f"{text!r} should be blocked"

    @pytest.mark.parametrize(
        "text",
        [
            # ISO country codes (2-letter)
            "US",
            "DE",
            "GB",
            "FR",
            "CN",
            # ISO 2-letter that looks like a placeholder
            "NA",  # Namibia — must NOT be blocked
            # ISO country codes (3-letter)
            "USA",
            "DEU",
            "GBR",
            "FRA",
            # Short real country names
            "Mali",
            "Iran",
            "Chad",
            "Niue",
            "Oman",
            "Cuba",
            "Fiji",
            "Togo",
            "Laos",
            # Real countries with long names
            "United States",
            "New Zealand",
            "South Korea",
            # Legitimate ISO numeric codes
            "840",  # USA
            "276",  # Germany
            "004",  # Afghanistan
        ],
    )
    def test_not_blocked(self, text: str) -> None:
        assert not DEFAULT_BLOCKLIST.is_blocked(text), f"{text!r} should NOT be blocked"

    def test_case_insensitive(self) -> None:
        assert DEFAULT_BLOCKLIST.is_blocked("Unknown")
        assert DEFAULT_BLOCKLIST.is_blocked("UNKNOWN")
        assert DEFAULT_BLOCKLIST.is_blocked("uNkNoWn")

    def test_strips_surrounding_whitespace(self) -> None:
        assert DEFAULT_BLOCKLIST.is_blocked("  unknown  ")
        assert DEFAULT_BLOCKLIST.is_blocked("\tunknown\n")

    def test_long_strings_never_blocked(self) -> None:
        # Even if the content looks like a placeholder, strings > 20 chars pass through.
        long_unknown = "unknown unknown unknown"
        assert len(long_unknown.strip()) > 20
        assert not DEFAULT_BLOCKLIST.is_blocked(long_unknown)

    def test_membership_syntax(self) -> None:
        assert "unknown" in DEFAULT_BLOCKLIST
        assert "US" not in DEFAULT_BLOCKLIST

    def test_non_string_membership(self) -> None:
        # __contains__ must not raise on non-strings.
        assert 42 not in DEFAULT_BLOCKLIST
        assert None not in DEFAULT_BLOCKLIST


class TestSentinelBlocklistCustomisation:
    """API for extending and replacing the blocklist."""

    def test_extra_merges_with_defaults(self) -> None:
        bl = SentinelBlocklist(extra={"custom_junk", "ALSO_JUNK"})
        assert bl.is_blocked("custom_junk")
        assert bl.is_blocked("also_junk")  # extra is casefolded
        # Defaults still apply.
        assert bl.is_blocked("unknown")

    def test_replace_overrides_defaults(self) -> None:
        bl = SentinelBlocklist(replace={"only_this"})
        assert bl.is_blocked("only_this")
        # Defaults are gone.
        assert not bl.is_blocked("unknown")
        assert not bl.is_blocked("null")

    def test_none_blocklist_disables(self) -> None:
        """Passing sentinel_blocklist=None to Resolver disables the guard."""
        # We test this at the SentinelBlocklist level: None is handled in Resolver.
        # Here just verify that a replace= with an empty set blocks nothing.
        bl = SentinelBlocklist(replace=set())
        assert not bl.is_blocked("unknown")
        assert not bl.is_blocked("null")

    def test_repr(self) -> None:
        bl = SentinelBlocklist()
        assert "SentinelBlocklist" in repr(bl)
        assert "size=" in repr(bl)


class TestReasonCode:
    """SENTINEL_BLOCKED is a valid ReasonCode."""

    def test_sentinel_blocked_exists(self) -> None:
        from resolvekit.core.model import ReasonCode

        assert ReasonCode.SENTINEL_BLOCKED.value == "sentinel_blocked"


class TestResolverSentinelIntegration:
    """Resolver returns SENTINEL_BLOCKED / NO_MATCH for junk inputs."""

    @pytest.fixture(scope="class")
    def resolver(self):
        """Stub resolver using a minimal backend so tests don't need data files."""
        from unittest.mock import MagicMock

        from resolvekit.core.api.resolver import Resolver
        from resolvekit.core.engine.interfaces import ResolverBackend
        from resolvekit.core.model import ResolutionResult, ResolutionStatus

        backend = MagicMock(spec=ResolverBackend)
        # resolve() on the backend should never be called for sentinel inputs;
        # configure a clear sentinel on any unexpected call.
        backend.resolve.return_value = ResolutionResult(
            status=ResolutionStatus.NO_MATCH
        )
        backend.available_packs = frozenset()
        backend.available_entity_types = frozenset()
        backend.available_code_systems = frozenset()
        backend.available_group_types = frozenset()
        return Resolver(runner=backend)

    @pytest.mark.parametrize(
        "text",
        [
            "unknown",
            "Unknown",
            " unknown ",
            "n/a",
            "null",
            "none",
            "tbd",
            "TBD",
            "various",
            "999",
            "000",
            "---",
            "qwerty",
            "lorem ipsum",
        ],
    )
    def test_sentinel_inputs_return_no_match(self, resolver, text: str) -> None:
        from resolvekit.core.model import ReasonCode, ResolutionStatus

        result = resolver.resolve(text)
        assert result.status == ResolutionStatus.NO_MATCH
        assert ReasonCode.SENTINEL_BLOCKED in result.reasons

    @pytest.mark.parametrize(
        "text",
        [
            "US",
            "DE",
            "Mali",
            "Iran",
            "Chad",
            "NA",  # ISO2 Namibia
            "United States",
        ],
    )
    def test_real_queries_reach_backend(self, resolver, text: str) -> None:
        from resolvekit.core.model import ReasonCode

        result = resolver.resolve(text)
        # These should NOT be blocked — they reached the (mocked) backend.
        assert ReasonCode.SENTINEL_BLOCKED not in result.reasons

    def test_disabled_blocklist_passes_through(self) -> None:
        """sentinel_blocklist=None disables the guard entirely."""
        from unittest.mock import MagicMock

        from resolvekit.core.api.resolver import Resolver
        from resolvekit.core.engine.interfaces import ResolverBackend
        from resolvekit.core.model import ReasonCode, ResolutionResult, ResolutionStatus

        backend = MagicMock(spec=ResolverBackend)
        backend.resolve.return_value = ResolutionResult(
            status=ResolutionStatus.NO_MATCH
        )
        backend.available_packs = frozenset()
        backend.available_entity_types = frozenset()
        backend.available_code_systems = frozenset()
        backend.available_group_types = frozenset()

        resolver = Resolver(runner=backend, sentinel_blocklist=None)
        result = resolver.resolve("unknown")
        assert ReasonCode.SENTINEL_BLOCKED not in result.reasons
        # Backend was called (not short-circuited).
        backend.resolve.assert_called_once()

    def test_custom_extra_blocklist(self) -> None:
        from unittest.mock import MagicMock

        from resolvekit.core.api.resolver import Resolver
        from resolvekit.core.engine.interfaces import ResolverBackend
        from resolvekit.core.model import ReasonCode, ResolutionResult, ResolutionStatus
        from resolvekit.core.util.sentinel import SentinelBlocklist

        backend = MagicMock(spec=ResolverBackend)
        backend.resolve.return_value = ResolutionResult(
            status=ResolutionStatus.NO_MATCH
        )
        backend.available_packs = frozenset()
        backend.available_entity_types = frozenset()
        backend.available_code_systems = frozenset()
        backend.available_group_types = frozenset()

        bl = SentinelBlocklist(extra={"my_custom_junk"})
        resolver = Resolver(runner=backend, sentinel_blocklist=bl)
        result = resolver.resolve("my_custom_junk")
        assert result.reasons[0] == ReasonCode.SENTINEL_BLOCKED
        backend.resolve.assert_not_called()
