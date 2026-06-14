"""Tests for bulk(to=<known system>) honouring on_missing when the resolved
entity lacks that code.

Behaviour:
- A *known* code system absent from a specific entity → None under on_missing
  "auto" (bulk default) or "null"; raises under on_missing="raise".
- A *typo'd* / completely unknown system → raises UnknownCodeSystemError
  regardless of on_missing.

Test entity: ``EuropeanUnion`` (a continental union).  It resolves cleanly from
``geo.continental_unions`` but has no ``wikidata`` code.  ``wikidata`` is present
on plain countries (France → Q142) and in ``resolver.code_systems()``, making it
a deterministic known-but-absent system for this entity.
"""

from __future__ import annotations

import pytest

from resolvekit import Resolver
from resolvekit.core.api.bulk import _bulk_dispatch
from resolvekit.core.api.output_spec import UNSET
from resolvekit.core.errors import UnknownCodeSystemError

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def r_geo() -> Resolver:
    """Resolver over geo countries + continental unions.

    Both modules are needed: ``geo.countries`` supplies ``wikidata`` codes
    (and thus registers ``wikidata`` in ``code_systems()``); ``geo.continental_unions``
    is required for ``EuropeanUnion`` to resolve.
    """
    return Resolver.from_modules(module_ids=["geo.countries", "geo.continental_unions"])


# ---------------------------------------------------------------------------
# Helper — call _bulk_dispatch with sensible defaults.
# ---------------------------------------------------------------------------


def _bulk(
    resolver: Resolver,
    values: list[str],
    *,
    to: object = UNSET,
    on_missing: str = "auto",
    output: str = "series",
) -> object:
    return _bulk_dispatch(
        resolver=resolver,
        values=values,
        to=to,
        output_spec=None,
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
# (1) Known code system, entity lacks it — on_missing governs the outcome.
# ---------------------------------------------------------------------------
#
# System under test: ``wikidata``.
#   - Present in ``r_geo.code_systems()`` (registered via geo.countries packs).
#   - Absent from ``EuropeanUnion`` (only has dcid, oecd:provider, undata).
#   - Present on plain countries: France → Q142.


def test_known_system_entity_lacks_it_default_on_missing_returns_none(
    r_geo: Resolver,
) -> None:
    """Default ``on_missing`` (``"auto"``) returns None for a known-but-absent code.

    This is the load-bearing case for pydeflate: it calls bulk with an explicit
    ``to=`` and ``on_missing`` inherits the bulk default (``"auto"`` → null).
    Before the fix, this raised ``UnknownCodeSystemError`` and aborted the batch.
    """
    # Sanity: wikidata IS known to the resolver.
    assert "wikidata" in r_geo.code_systems()
    # Sanity: EuropeanUnion resolves but lacks wikidata.
    eu = r_geo.resolve("European Union", include_entity=True)
    assert eu.entity is not None
    assert "wikidata" not in eu.entity.codes_dict

    result = _bulk(r_geo, ["European Union"], to="wikidata", on_missing="auto")
    assert result == [None], f"Expected [None], got {result!r}"


def test_known_system_entity_lacks_it_explicit_null_returns_none(
    r_geo: Resolver,
) -> None:
    """Explicit ``on_missing='null'`` returns None for a known-but-absent code."""
    result = _bulk(r_geo, ["European Union"], to="wikidata", on_missing="null")
    assert result == [None], f"Expected [None], got {result!r}"


def test_known_system_entity_lacks_it_raise_raises(r_geo: Resolver) -> None:
    """``on_missing='raise'`` re-raises ``UnknownCodeSystemError`` when the entity
    lacks the code, even though it is a real (known) system."""
    with pytest.raises(UnknownCodeSystemError):
        _bulk(r_geo, ["European Union"], to="wikidata", on_missing="raise")


def test_known_system_present_on_other_entity_still_resolves(
    r_geo: Resolver,
) -> None:
    """wikidata resolves normally on entities that have it (France → Q142)."""
    result = _bulk(r_geo, ["France"], to="wikidata", on_missing="auto")
    assert result == ["Q142"], f"Expected ['Q142'], got {result!r}"


def test_mixed_batch_known_system_some_present_some_absent(
    r_geo: Resolver,
) -> None:
    """A batch mixing entities that have / lack the code returns None only for
    the missing ones, not for the whole batch."""
    result = _bulk(
        r_geo,
        ["France", "European Union"],
        to="wikidata",
        on_missing="auto",
    )
    assert result == ["Q142", None], f"Expected ['Q142', None], got {result!r}"


# ---------------------------------------------------------------------------
# (2) Typo / genuinely unknown system — always raises, on_missing is irrelevant.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("on_missing", ["auto", "null", "raise"])
def test_typo_system_always_raises(r_geo: Resolver, on_missing: str) -> None:
    """A system name that is not in ``code_systems()`` raises regardless of
    ``on_missing``.  This ensures the change does not swallow programmer errors."""
    assert "wikidataxxx" not in r_geo.code_systems(), (
        "test precondition: 'wikidataxxx' must not be a real code system"
    )
    with pytest.raises(UnknownCodeSystemError):
        _bulk(r_geo, ["France"], to="wikidataxxx", on_missing=on_missing)
