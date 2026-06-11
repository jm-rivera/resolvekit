"""Tests for short-input guards on GeoExactCodeSource.

Single-letter inputs, lowercase short alpha, and degenerate tokens ("na",
"null", "#N/A") must never resolve to countries without an explicit geo
entity_type hint. Uppercase ISO codes (US, GBR) and hinted lowercase resolve
as normal.
"""

import pytest

from resolvekit.core.model import GenerationContext, ResolutionContext
from resolvekit.packs.geo.sources.exact_code import GeoExactCodeSource
from tests.conftest import MockEntityStore, make_query


@pytest.fixture
def code_store() -> MockEntityStore:
    """Mock store with a representative spread of geo codes."""
    return MockEntityStore(
        codes={
            ("iso2", "us"): ["country/USA"],
            ("iso2", "gb"): ["country/GBR"],
            ("iso2", "it"): ["country/ITA"],
            ("iso2", "in"): ["country/IND"],
            ("iso2", "na"): ["country/NAM"],
            ("iso2", "no"): ["country/NOR"],
            ("iso2", "nu"): ["country/NIU"],
            ("iso3", "usa"): ["country/USA"],
            ("iso3", "gbr"): ["country/GBR"],
            ("iso3", "ita"): ["country/ITA"],
            # Length-1 ITU codes — historically real, but a footgun.
            ("uicalphabeticalcountrycode", "a"): ["country/AUT"],
            ("uicalphabeticalcountrycode", "i"): ["country/ITA"],
            ("uicalphabeticalcountrycode", "f"): ["country/FRA"],
        },
    )


def _generate(source, store, raw_text, trace, context=None, normalized=None):
    """Run GeoExactCodeSource.generate() for `raw_text`."""
    query = make_query(raw_text, normalized=normalized)
    ctx = GenerationContext(
        query=query,
        context=context or ResolutionContext(),
        store=store,
        budget=10,
        trace=trace,
    )
    return source.generate(ctx)


class TestUppercaseShortInputsStillResolve:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("US", "country/USA"),
            ("GB", "country/GBR"),
            ("IT", "country/ITA"),
            ("IN", "country/IND"),
            # "NA" deliberately omitted — it's the iconic spreadsheet
            # missing-value sentinel; see TestDegenerateTokensAlwaysBlocked.
            ("NO", "country/NOR"),
            ("NU", "country/NIU"),
            ("USA", "country/USA"),
            ("GBR", "country/GBR"),
            ("ITA", "country/ITA"),
        ],
    )
    def test_uppercase_iso_resolves(self, raw, expected, code_store, null_trace):
        source = GeoExactCodeSource()
        evidence = _generate(source, code_store, raw, null_trace)

        assert len(evidence) == 1
        assert evidence[0].entity_id == expected
        assert evidence[0].raw_score == 1.0


class TestDegenerateTokensAlwaysBlocked:
    @pytest.mark.parametrize(
        "raw",
        ["NA", "Na", "na", "NULL", "null", "N/A", "n/a", "#N/A", "NaN", "TBD", "--"],
    )
    def test_degenerate_blocked_no_context(self, raw, code_store, null_trace):
        source = GeoExactCodeSource()
        evidence = _generate(source, code_store, raw, null_trace)
        assert evidence == []

    @pytest.mark.parametrize("raw", ["NA", "NULL", "#N/A", "NaN"])
    def test_degenerate_blocked_even_with_context(self, raw, code_store, null_trace):
        source = GeoExactCodeSource()
        ctx = ResolutionContext(entity_types=frozenset({"geo.country"}))
        evidence = _generate(source, code_store, raw, null_trace, context=ctx)
        assert evidence == []


class TestLowercaseShortInputsBlocked:
    @pytest.mark.parametrize(
        "raw",
        [
            "us",
            "gb",
            "it",
            "in",
            "no",
            "nu",
            "usa",
            "gbr",
            "ita",
            "uS",  # mixed-case
            "Us",  # mixed-case
        ],
    )
    def test_lowercase_no_hint_blocked(self, raw, code_store, null_trace):
        source = GeoExactCodeSource()
        evidence = _generate(source, code_store, raw, null_trace)
        assert evidence == [], (
            f"{raw!r} resolved without a hint — stopword/lowercase bypass must be off"
        )


class TestSingleLetterCodesBlocked:
    @pytest.mark.parametrize("raw", ["A", "I", "F", "a", "i", "f"])
    def test_single_letter_blocked(self, raw, code_store, null_trace):
        source = GeoExactCodeSource()
        evidence = _generate(source, code_store, raw, null_trace)
        assert evidence == []


class TestContextHintOptsIn:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("us", "country/USA"),
            ("in", "country/IND"),
            ("no", "country/NOR"),
            # Uppercase single letters retain the hint unlock: "I" → Italy uses
            # the conventional ITU/UIC all-caps casing and is unambiguous as a code.
            ("A", "country/AUT"),
            ("I", "country/ITA"),
            ("F", "country/FRA"),
            # "US" (caps) with a geo hint still admits — this is the canonical form.
            ("US", "country/USA"),
            # "chad" (4 chars, real canonical name) must still resolve with a hint —
            # it is the recall-floor canary.  4 chars > 1, so the single-letter block
            # does not fire; short_alpha_code_allowed also passes (len > 3).
        ],
    )
    def test_with_country_context_resolves(self, raw, expected, code_store, null_trace):
        source = GeoExactCodeSource()
        ctx = ResolutionContext(entity_types=frozenset({"geo.country"}))
        evidence = _generate(source, code_store, raw, null_trace, context=ctx)

        assert len(evidence) == 1
        assert evidence[0].entity_id == expected

    @pytest.mark.parametrize(
        "raw",
        [
            "i",  # single lowercase letter — blocked even with a geo hint
            "a",  # single lowercase letter — blocked even with a geo hint
            "f",  # single lowercase letter — blocked even with a geo hint
        ],
    )
    def test_single_lowercase_letter_blocked_even_with_hint(
        self, raw, code_store, null_trace
    ):
        """A bare single lowercase letter must be rejected regardless of the
        geo entity_type hint.

        "i"/"a"/"f" are too ambiguous to auto-resolve (they are also ordinary
        English words).  Uppercase counterparts ("I", "A", "F") retain the hint
        unlock because they follow the ITU/UIC all-caps convention.

        Why "chad" (4 chars) is not tested here: it is a real canonical name,
        not a single-letter code, so the single-letter block never fires.
        Why "AND" is not tested here: it is uppercase — it is handled upstream
        by the case channel before short_input_blocked is reached.
        """
        source = GeoExactCodeSource()
        ctx = ResolutionContext(entity_types=frozenset({"geo.country"}))
        evidence = _generate(source, code_store, raw, null_trace, context=ctx)
        assert evidence == [], (
            f"{raw!r} resolved despite being a single lowercase letter with a hint"
        )

    def test_degenerate_blocked_even_with_hint(self, code_store, null_trace):
        """Degenerate tokens (e.g. "NA") must be blocked regardless of the hint.

        This is unchanged behavior — the degenerate check runs first in
        short_input_blocked and the hint never overrides it.
        """
        source = GeoExactCodeSource()
        ctx = ResolutionContext(entity_types=frozenset({"geo.country"}))
        evidence = _generate(source, code_store, "NA", null_trace, context=ctx)
        assert evidence == [], "'NA' must remain blocked even with a geo hint"

    def test_unrelated_entity_types_do_not_opt_in(self, code_store, null_trace):
        """A non-geo entity_type hint does not bypass the short-input gate.

        "us" is a lowercase ISO2 code that is also a common English stopword.
        Without a geo entity_type hint the short-input gate must suppress it,
        regardless of other entity_types the caller may pass.
        """
        source = GeoExactCodeSource()
        ctx = ResolutionContext(entity_types=frozenset({"org.company"}))
        evidence = _generate(source, code_store, "us", null_trace, context=ctx)
        assert evidence == [], (
            "'us' should not resolve when only a non-geo entity_type is hinted"
        )


class TestNonShortInputsUnaffected:
    def test_iso_numeric_unaffected(self, null_trace):
        store = MockEntityStore(codes={("iso_numeric", "840"): ["country/USA"]})
        source = GeoExactCodeSource()
        evidence = _generate(source, store, "840", null_trace)
        assert len(evidence) == 1
        assert evidence[0].entity_id == "country/USA"

    def test_dcid_unaffected(self, null_trace):
        store = MockEntityStore(codes={("dcid", "country/usa"): ["country/USA"]})
        source = GeoExactCodeSource()
        evidence = _generate(
            source, store, "country/USA", null_trace, normalized="country/usa"
        )
        assert len(evidence) == 1
        assert evidence[0].entity_id == "country/USA"

    def test_long_lowercase_name_unaffected(self, null_trace):
        """A lowercase input longer than 3 chars goes through; it just won't
        match because there's no ISO code 'germany'. The guard must not
        short-circuit before the regular lookup runs."""
        store = MockEntityStore(codes={("iso2", "de"): ["country/DEU"]})
        source = GeoExactCodeSource()
        evidence = _generate(source, store, "germany", null_trace)
        assert evidence == []
