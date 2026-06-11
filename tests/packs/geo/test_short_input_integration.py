"""Integration tests for the short-input gate across all geo sources.

These exercise the full Resolver pipeline (not just GeoExactCodeSource) to
confirm that degenerate inputs cannot leak through any source path. The
module-level fixtures avoid rebuilding the resolver per test.
"""

import pytest

from resolvekit import Resolver
from resolvekit.core.model import ResolutionContext


@pytest.fixture(scope="module")
def resolver() -> Resolver:
    return Resolver.auto()


# Inputs that must NOT silently resolve.
# Format: (query, why_it_should_be_blocked)
_BAD_INPUTS = [
    ("A", "single-letter ITU code"),
    ("i", "lowercase single letter"),
    ("I", "uppercase single letter"),
    ("F", "uppercase single letter"),
    ("NA", "ISO2 for Namibia, but universal missing-value sentinel"),
    ("Na", "casing variant of NA"),
    ("na", "lowercase NA"),
    ("NULL", "spreadsheet null marker"),
    ("null", "lowercase null"),
    ("N/A", "missing-value marker"),
    ("n/a", "lowercase missing-value marker"),
    ("#N/A", "Excel error code"),
    ("NaN", "numeric NaN marker"),
    ("nan", "lowercase NaN"),
    ("TBD", "to-be-determined"),
    ("--", "punctuation-only sentinel"),
    # Lowercase ISO codes are also common English/data stopwords and must not
    # silently resolve at high confidence without an explicit geo hint.
    ("us", "common English word and ISO2 for USA"),
    ("in", "common English preposition and ISO2 for India"),
    ("is", "common English verb and ISO2 for Iceland"),
    ("it", "common English pronoun and ISO2 for Italy"),
    ("to", "common English preposition and ISO2 for Tonga"),
    ("as", "common English word and ISO2 for American Samoa"),
    ("by", "common English preposition and ISO2 for Belarus"),
    ("no", "common English word and ISO2 for Norway"),
    ("be", "common English verb and ISO2 for Belgium"),
    ("at", "common English preposition and ISO2 for Austria"),
    ("do", "common English verb and ISO2 for Dominican Republic"),
    ("my", "common English word and ISO2 for Malaysia"),
    ("id", "common English word and ISO2 for Indonesia"),
    ("me", "common English pronoun and ISO2 for Montenegro"),
    ("so", "common English word and ISO2 for Somalia"),
    ("am", "common English verb and ISO2 for Armenia"),
    ("re", "common English word and ISO2 for Réunion"),
    ("ad", "common English word and ISO2 for Andorra"),
    ("gb", "lowercase ISO2 — blocked without hint"),
    ("fra", "lowercase ISO3 — blocked without hint"),
    ("usa", "lowercase ISO3 — blocked without hint"),
    ("gbr", "lowercase ISO3 — blocked without hint"),
    ("ita", "lowercase ISO3 — blocked without hint"),
]


# Inputs that must continue to resolve correctly (uppercase ISO codes and full
# names). Lowercase ISO codes require a geo entity_type hint (see
# TestContextHintBehavior).
_GOOD_INPUTS = [
    ("US", "country/USA"),
    ("GB", "country/GBR"),
    ("IT", "country/ITA"),
    ("IN", "country/IND"),
    ("NO", "country/NOR"),
    ("USA", "country/USA"),
    ("GBR", "country/GBR"),
    ("ITA", "country/ITA"),
    ("Italy", "country/ITA"),
    ("United States", "country/USA"),
    ("United Kingdom", "country/GBR"),
]


@pytest.mark.parametrize("query,reason", _BAD_INPUTS)
def test_bad_inputs_return_no_match(resolver, query, reason):
    """Every degenerate input must produce no_match without context."""
    result = resolver.resolve(query)
    assert result.status.value == "no_match", (
        f"{query!r} ({reason}) silently resolved to "
        f"{result.candidates[0].entity_id if result.candidates else None} "
        f"with confidence {result.confidence}"
    )


@pytest.mark.parametrize("query,expected", _GOOD_INPUTS)
def test_good_inputs_still_resolve(resolver, query, expected):
    """Legitimate uppercase ISO codes and full names must still resolve."""
    result = resolver.resolve(query)
    assert result.status.value == "resolved", (
        f"{query!r} regressed to {result.status.value}"
    )
    assert result.candidates[0].entity_id == expected


class TestContextHintBehavior:
    @pytest.fixture
    def country_ctx(self) -> ResolutionContext:
        return ResolutionContext(entity_types=frozenset({"geo.country"}))

    @pytest.mark.parametrize(
        "query,expected",
        [
            ("us", "country/USA"),
            ("in", "country/IND"),
            ("no", "country/NOR"),
            # Uppercase single letters use the ITU/UIC convention; hint unlock kept.
            ("A", "country/AUT"),
            ("I", "country/ITA"),
            ("F", "country/FRA"),
            # "US" (caps) — canonical form, admits with or without a hint.
            ("US", "country/USA"),
            # "chad" (4 chars, real canonical name) is the recall-floor canary.
            # short_input_blocked never fires: len > 1, len > _SHORT_ALPHA_MAX_LEN=3,
            # so short_alpha_code_allowed returns True and the name source resolves it.
            ("chad", "country/TCD"),
        ],
    )
    def test_short_alpha_resolves_with_country_context(
        self, resolver, country_ctx, query, expected
    ):
        result = resolver.resolve(query, context=country_ctx)
        assert result.status.value == "resolved", (
            f"{query!r} did not resolve with a geo hint (expected {expected!r})"
        )
        assert result.candidates[0].entity_id == expected

    @pytest.mark.parametrize(
        "query", ["NA", "NULL", "N/A", "#N/A", "NaN", "TBD", "--", "nan"]
    )
    def test_degenerate_tokens_blocked_even_with_context(
        self, resolver, country_ctx, query
    ):
        result = resolver.resolve(query, context=country_ctx)
        assert result.status.value == "no_match", (
            f"{query!r} resolved despite being a degenerate sentinel"
        )

    @pytest.mark.parametrize(
        "query",
        [
            "i",  # single lowercase letter — now blocked even with a geo hint
            "a",  # single lowercase letter — now blocked even with a geo hint
        ],
    )
    def test_single_lowercase_letter_blocked_even_with_hint(
        self, resolver, country_ctx, query
    ):
        """A bare single lowercase letter must not resolve even with a geo hint.

        A single-lowercase-letter check must run before the geo-hint unlock,
        ensuring "i" and "a" remain blocked.  Uppercase single letters ("I", "A")
        use the ITU/UIC all-caps convention and are unaffected.
        """
        result = resolver.resolve(query, context=country_ctx)
        assert result.status.value == "no_match", (
            f"{query!r} resolved despite being a single lowercase letter with a hint"
        )
