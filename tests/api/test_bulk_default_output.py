"""Tests for bulk spec path, batch-raise fix, and empty-column warning.

All tests call ``_bulk_dispatch`` directly and build spec manually to isolate
the bulk path from constructor-level wiring.
"""

from __future__ import annotations

import warnings

import pytest

from resolvekit import Resolver
from resolvekit.core.api.bulk import _bulk_dispatch
from resolvekit.core.api.output_spec import UNSET, OutputSpec, compile_output_spec
from resolvekit.core.errors import OutputMissingError, UnknownCodeSystemError
from resolvekit.core.model.bulk_result import BulkResult

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def r_geo() -> Resolver:
    """Resolver over geo countries + continental unions — fast, shared across
    tests in this module. Both are named explicitly: module selection is
    authoritative, so "European Union" (a continental union) only resolves when
    geo.continental_unions is in the list."""
    return Resolver.from_modules(module_ids=["geo.countries", "geo.continental_unions"])


@pytest.fixture(scope="module")
def r_org() -> Resolver:
    """Resolver over org.companies — no iso codes, used for warning/miss tests."""
    return Resolver.from_modules(module_ids=["org.companies"])


# ---------------------------------------------------------------------------
# Helper: dispatch with sensible defaults so call sites stay concise.
# ---------------------------------------------------------------------------


def _bulk(
    resolver: Resolver,
    values: list[str],
    *,
    spec: OutputSpec | None = None,
    to: object = UNSET,
    on_missing: str = "auto",
    output: str = "series",
) -> object:
    return _bulk_dispatch(
        resolver=resolver,
        values=values,
        to=to,
        output_spec=spec,
        on_missing=on_missing,
        output=output,
        domain=None,
        context=None,
        from_system=None,
        not_found="null",
        on_error="raise",
        on_ambiguous="null",
    )


# ---------------------------------------------------------------------------
# Batch-raise regression
# ---------------------------------------------------------------------------


def test_batch_raise_regression_code_system(r_geo: Resolver) -> None:
    """Spec path MUST NOT raise when a resolved entity lacks the code.

    ``wikidata`` is a ``kind="code"`` target (not in KNOWN_PIVOTS).  Before the
    ``_pivot_result`` fix, ``dispatch_pivot(entity, "wikidata")`` raised
    ``UnknownCodeSystemError`` for entities lacking that code — blowing up the
    whole batch.  The fix routes spec-path pivoting through ``apply_output``,
    which returns None on a per-entity miss instead of raising.

    ``European Union`` lacks ``wikidata``; ``France`` has it (Q142).
    """
    spec = compile_output_spec("wikidata", "auto", known_systems=r_geo.code_systems())
    assert spec.chain[0].kind == "code", (
        "wikidata must be kind='code' to exercise the bug"
    )

    # Without the _pivot_result fix this raised UnknownCodeSystemError and blew up the batch.
    result = _bulk(r_geo, ["European Union", "France"], spec=spec)
    assert result == [None, "Q142"], f"Expected [None, 'Q142'], got {result!r}"


# ---------------------------------------------------------------------------
# Explicit-to typo still raises (explicit-to path unchanged)
# ---------------------------------------------------------------------------


def test_explicit_to_typo_raises(r_geo: Resolver) -> None:
    """A typo'd explicit ``to=`` surfaces as ``UnknownCodeSystemError`` (spec=None path)."""
    with pytest.raises(UnknownCodeSystemError):
        _bulk(r_geo, ["France"], to="iso33")


# ---------------------------------------------------------------------------
# Spec path returns native series for output="series"
# ---------------------------------------------------------------------------


def test_spec_path_returns_native_series(r_geo: Resolver) -> None:
    """``output='series'`` with an active spec returns the raw list, not a BulkResult."""
    spec = compile_output_spec("iso3", "auto", known_systems=r_geo.code_systems())
    result = _bulk(r_geo, ["France", "Germany"], spec=spec, output="series")
    assert not isinstance(result, BulkResult)
    assert result == ["FRA", "DEU"]


def test_spec_path_output_record_wraps_bulk_result(r_geo: Resolver) -> None:
    """``output='record'`` with an active spec still wraps in BulkResult."""
    spec = compile_output_spec("iso3", "auto", known_systems=r_geo.code_systems())
    result = _bulk(r_geo, ["France", "Germany"], spec=spec, output="record")
    assert isinstance(result, BulkResult)


def test_spec_path_output_frame_wraps_bulk_result(r_geo: Resolver) -> None:
    """``output='frame'`` with an active spec still wraps in BulkResult."""
    spec = compile_output_spec("iso3", "auto", known_systems=r_geo.code_systems())
    result = _bulk(r_geo, ["France", "Germany"], spec=spec, output="frame")
    assert isinstance(result, BulkResult)


# ---------------------------------------------------------------------------
# Chain fallthrough: iso3 → name
# ---------------------------------------------------------------------------


def test_chain_fallthrough_iso3_to_name(r_geo: Resolver) -> None:
    """A country lacking iso3 yields its canonical name via the second chain link."""
    spec = compile_output_spec(
        ["iso3", "name"], "auto", known_systems=r_geo.code_systems()
    )
    result = _bulk(r_geo, ["European Union", "France"], spec=spec)
    # European Union has no iso3; "name" (bare computed terminal) never misses.
    assert result[1] == "FRA"
    assert result[0] == "European Union"


# ---------------------------------------------------------------------------
# empty-column UserWarning
# ---------------------------------------------------------------------------


def test_r6_warning_fires_when_column_wholly_empty(r_org: Resolver) -> None:
    """Single-link ['iso3'] over org entities → warning fires, all-None series."""
    spec = compile_output_spec("iso3", "auto", known_systems=r_org.code_systems())

    with pytest.warns(UserWarning, match="column wholly empty among resolved rows"):
        result = _bulk(r_org, ["Microsoft", "Apple"], spec=spec)

    assert result == [None, None]


def test_r6_no_warning_when_name_link_hits(r_geo: Resolver) -> None:
    """Two-link ['iso3', 'name'] over an iso3-less country → no warning (name hits)."""
    spec = compile_output_spec(
        ["iso3", "name"], "auto", known_systems=r_geo.code_systems()
    )

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = _bulk(r_geo, ["European Union", "France"], spec=spec)

    user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
    assert not user_warnings, f"Unexpected UserWarning(s): {user_warnings}"
    # The name link rescued EU; France has iso3.
    assert result[0] is not None
    assert result[1] == "FRA"


def test_no_warning_when_some_resolved_rows_have_value(r_geo: Resolver) -> None:
    """Mixed rows: resolved-with-code + resolved-without + NO_MATCH → no warning.

    Warning fires ONLY when every resolved row missed (wholly empty).  When at
    least one resolved row has a value, the column is not wholly empty.
    """
    spec = compile_output_spec("wikidata", "auto", known_systems=r_geo.code_systems())

    # France has wikidata (Q142); European Union lacks it; "zzz_not_a_place" → NO_MATCH.
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = _bulk(
            r_geo, ["France", "European Union", "zzz_not_a_place"], spec=spec
        )

    user_warnings = [w for w in caught if issubclass(w.category, UserWarning)]
    assert not user_warnings, f"Unexpected UserWarning(s): {user_warnings}"
    assert result[0] == "Q142"  # France: resolved + has wikidata
    assert result[1] is None  # EU: resolved but no wikidata
    assert result[2] is None  # no_match: not a resolved row


def test_warning_message_uses_full_chain_repr(r_org: Resolver) -> None:
    """The warning message cites the full chain list, not just the last token."""
    spec = compile_output_spec(
        ["iso3", "iso2"], "auto", known_systems=r_org.code_systems()
    )

    with pytest.warns(UserWarning, match=r"\['iso3', 'iso2'\]"):
        _bulk(r_org, ["Microsoft"], spec=spec)


# ---------------------------------------------------------------------------
# on_missing="raise" in bulk
# ---------------------------------------------------------------------------


def test_on_missing_raise_aborts_batch(r_geo: Resolver) -> None:
    """``on_missing='raise'`` raises OutputMissingError on the first resolved miss."""
    spec = compile_output_spec("wikidata", "auto", known_systems=r_geo.code_systems())

    # European Union lacks wikidata; with raise policy the batch aborts.
    with pytest.raises(OutputMissingError) as exc_info:
        _bulk(
            r_geo,
            ["European Union", "France"],
            spec=spec,
            on_missing="raise",
        )

    assert exc_info.value.entity_id == "EuropeanUnion"


def test_on_missing_raise_with_no_match_rows_does_not_raise(r_geo: Resolver) -> None:
    """NO_MATCH rows are not resolved entities; on_missing='raise' ignores them."""
    spec = compile_output_spec("iso3", "auto", known_systems=r_geo.code_systems())

    # "zzz_not_a_place" is NO_MATCH; France is resolved and has iso3 → no miss → no raise.
    result = _bulk(
        r_geo,
        ["zzz_not_a_place", "France"],
        spec=spec,
        on_missing="raise",
    )
    assert result[0] is None  # no_match → null
    assert result[1] == "FRA"
