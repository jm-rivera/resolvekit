"""Tests for the deny-list gate.

Covers:
- Unit-level ``is_denied()`` predicate (membership, casefold, non-members).
- Packaging smoke: the JSON data file ships in the wheel and is loadable.
- Parse-level integration: a span matching a deny-listed term produces a
  ``DroppedSpan(reason="deny_list")`` before any resolution attempt.

NOTE on "and" / "AND":
``"and"`` is deliberately NOT in the deny-list because ``"AND"`` is Andorra's
ISO alpha-3 code — casefolded matching would block ``"and".casefold() == "and"``
and therefore also drop the all-caps ``"AND"`` form before the case channel
can admit it.  The ``"and"``-as-conjunction suppression is the case channel's
responsibility (``reason="code_case_mismatch"``).
"""

from __future__ import annotations

import importlib.resources
import json

# ---------------------------------------------------------------------------
# Unit-level predicate tests
# ---------------------------------------------------------------------------


def test_common_stopwords_are_denied() -> None:
    """Stopwords that carry no entity meaning are denied regardless of casing."""
    from resolvekit.core.parse.denylist import is_denied

    # Core English function words in the list
    assert is_denied("of")
    assert is_denied("the")
    assert is_denied("or")
    assert is_denied("a")
    assert is_denied("an")
    assert is_denied("in")
    assert is_denied("on")
    assert is_denied("at")
    assert is_denied("to")
    assert is_denied("is")
    assert is_denied("as")
    assert is_denied("by")


def test_multilingual_stopwords_are_denied() -> None:
    """Multi-language function words in the list are denied."""
    from resolvekit.core.parse.denylist import is_denied

    assert is_denied("et")  # French/Latin "and"
    assert is_denied("y")  # Spanish "and"
    assert is_denied("und")  # German "and"
    assert is_denied("de")  # French/Spanish "of/from"
    assert is_denied("la")  # French/Spanish "the"
    assert is_denied("le")  # French "the"


def test_common_noun_place_alias_homographs_are_denied() -> None:
    """Common English nouns that collide with foreign-language place aliases are denied.

    "island" and "islands" match Iceland's Danish/German/Norwegian alias "Island"
    (country/ISL) at high confidence.  The bare noun must be denied so sentences
    like "a small island off Norway" do not produce a country/ISL entity.
    """
    from resolvekit.core.parse.denylist import is_denied

    assert is_denied("island")
    assert is_denied("islands")
    # Mixed-case variants are also denied (casefolded matching)
    assert is_denied("Island")
    assert is_denied("Islands")

    # Multi-word surfaces containing "islands" are NOT denied: leftmost-longest
    # AC matching emits the full alias, not a bare "islands" token.
    assert not is_denied("Solomon Islands")
    assert not is_denied("Faroe Islands")
    assert not is_denied("Marshall Islands")


def test_entity_names_are_not_denied() -> None:
    """Legitimate entity names must not be in the deny-list."""
    from resolvekit.core.parse.denylist import is_denied

    # Recall canary: "chad" must never be blocked
    assert not is_denied("chad")
    assert not is_denied("kenya")
    assert not is_denied("somalia")
    assert not is_denied("united states")


def test_iso_codes_are_not_denied() -> None:
    """ISO country codes must never appear in the deny-list.

    The deny-list uses casefolded matching, so including any string whose
    casefolded form equals an ISO code would silently block that code's
    all-caps form too.  This test guards the invariant.
    """
    from resolvekit.core.parse.denylist import is_denied

    # "and" casefolds to the normalized form of "AND" (Andorra alpha-3).
    # It must NOT be in the deny-list — the case channel handles it.
    assert not is_denied("and"), (
        "'and' must not be denied: its casefolded form matches the ISO alpha-3 "
        "code 'AND' (Andorra), which should still resolve via the case channel"
    )
    # Likewise for other codes that collide with common words
    assert not is_denied("us")  # iso2 USA
    assert not is_denied("eu")  # common org acronym
    assert not is_denied("who")  # org acronym


def test_casefold_normalization() -> None:
    """Deny-list matching is case-insensitive (casefolded)."""
    from resolvekit.core.parse.denylist import is_denied

    # "the" in various casings — all denied
    assert is_denied("The")
    assert is_denied("THE")
    assert is_denied("tHe")

    # "of" in various casings — all denied
    assert is_denied("Of")
    assert is_denied("OF")


def test_deny_set_module_constant_is_frozenset() -> None:
    """_DENY_SET is a frozenset of casefolded strings loaded at import."""
    from resolvekit.core.parse.denylist import _DENY_SET

    assert isinstance(_DENY_SET, frozenset)
    assert len(_DENY_SET) > 0
    for term in _DENY_SET:
        assert term == term.casefold(), f"Term {term!r} is not casefolded"


# ---------------------------------------------------------------------------
# Packaging smoke test
# ---------------------------------------------------------------------------


def test_deny_list_json_ships_in_wheel() -> None:
    """The deny_list.json data file is accessible via importlib.resources.

    This asserts that the file ships inside the installed package and is not
    accidentally excluded by wheel-exclude rules in pyproject.toml.
    """
    path = importlib.resources.files("resolvekit").joinpath(
        "_data/parse/deny_list.json"
    )
    assert path.is_file(), (
        "_data/parse/deny_list.json is not accessible via importlib.resources — "
        "check wheel-exclude rules in pyproject.toml"
    )

    content = json.loads(path.read_text(encoding="utf-8"))  # type: ignore[attr-defined]
    assert "version" in content
    assert "terms" in content
    assert isinstance(content["terms"], list)
    assert len(content["terms"]) > 0


# ---------------------------------------------------------------------------
# Parse-level integration test
# ---------------------------------------------------------------------------


def test_all_caps_forms_bypass_deny_gate() -> None:
    """All-caps ASCII surfaces skip the deny-list and reach the code channel.

    'LA' and 'IN' are all-caps forms of deny-listed terms ('la', 'in') whose
    uppercase form is a wanted org/geo code.  The gate must NOT fire for them.
    The predicate is_denied() still returns True (the predicate is unchanged);
    only the gate in link_span is case-aware.
    """
    from resolvekit.core.parse.automaton import _RawHit
    from resolvekit.core.parse.denylist import is_denied
    from resolvekit.core.parse.link import link_span
    from resolvekit.core.parse.result import DroppedSpan

    # Predicate still matches all casings — the gate is what's case-aware
    assert is_denied("la")
    assert is_denied("La")
    assert is_denied("LA")
    assert is_denied("in")
    assert is_denied("In")
    assert is_denied("IN")

    # But lowercase/mixed ARE dropped by the gate
    # (tested here at predicate level; parse-level coverage is below)

    class _StubBackend:
        """Minimal stub that always returns NO_MATCH so we can observe gate order."""

        def _resolve_one(self, text, *, context=None):
            from resolvekit.core.model.result import (
                ResolutionResult,
                ResolutionStatus,
            )

            return ResolutionResult(
                status=ResolutionStatus.NO_MATCH,
                confidence=None,
                candidates=[],
                reasons=[],
                query_text=text,
            )

        @property
        def pack_normalizers(self):
            return {}

        @property
        def available_packs(self):
            return frozenset({"geo"})

        def store_for(self, pack_id):
            raise ValueError(pack_id)

        def data_version_summary(self):
            return ""

    stub = _StubBackend()

    # "la" and "La" → denied by the gate
    for lower_surface in ("la", "La"):
        hit = _RawHit(
            start=0,
            end=len(lower_surface),
            surface=lower_surface,
            entity_ids=[],
            pack_id="geo",
            code_shaped=False,
        )
        outcome = link_span(
            hit,
            backend=stub,
            base_context=None,
            confidence_threshold=None,
            ctx_cache={},
            include_nil=True,
        )
        assert isinstance(outcome, DroppedSpan) and outcome.reason == "deny_list", (
            f"Expected deny_list drop for {lower_surface!r}, got {outcome!r}"
        )

    # "LA" → NOT dropped by the deny-list gate (falls through to code channel / resolve)
    for caps_surface in ("LA", "IN"):
        hit = _RawHit(
            start=0,
            end=len(caps_surface),
            surface=caps_surface,
            entity_ids=[],
            pack_id="geo",
            code_shaped=False,
        )
        outcome = link_span(
            hit,
            backend=stub,
            base_context=None,
            confidence_threshold=None,
            ctx_cache={},
            include_nil=True,
        )
        assert not (
            isinstance(outcome, DroppedSpan) and outcome.reason == "deny_list"
        ), (
            f"All-caps {caps_surface!r} must NOT be dropped by deny_list gate; "
            f"got {outcome!r}"
        )

    # "in" and "In" → denied by the gate
    for lower_surface in ("in", "In"):
        hit = _RawHit(
            start=0,
            end=len(lower_surface),
            surface=lower_surface,
            entity_ids=[],
            pack_id="geo",
            code_shaped=False,
        )
        outcome = link_span(
            hit,
            backend=stub,
            base_context=None,
            confidence_threshold=None,
            ctx_cache={},
            include_nil=True,
        )
        assert isinstance(outcome, DroppedSpan) and outcome.reason == "deny_list", (
            f"Expected deny_list drop for {lower_surface!r}, got {outcome!r}"
        )


def test_deny_list_gate_fires_in_parse_pipeline(parse_geo_resolver) -> None:
    """A deny-listed surface produces DroppedSpan(reason='deny_list').

    Uses a sentence where "the" would otherwise be matched as a surface form
    (if any entity has a name normalized to "the") or appears as a detected
    span, to verify the deny-list gate short-circuits before resolution.

    We test by injecting "of" directly through link_span so the test is
    independent of whether the automaton actually detects "of" in bundled data.
    """
    from resolvekit.core.parse.automaton import _RawHit
    from resolvekit.core.parse.link import link_span
    from resolvekit.core.parse.result import DroppedSpan

    class _Adapter:
        def __init__(self, resolver) -> None:
            self._resolver = resolver

        def _resolve_one(self, text, *, context=None):
            import weakref

            from resolvekit.core.explain.protocol import Explainer

            resolver_as_explainer: Explainer = self._resolver  # type: ignore[assignment]
            ref = weakref.ref(resolver_as_explainer)
            return self._resolver._resolve_inner(
                text,
                normalized_domain=None,
                context=context,
                include_entity=False,
                timeout=None,
                _self_ref=ref,
            )

        @property
        def pack_normalizers(self):
            return self._resolver._pack_normalizers

        @property
        def available_packs(self):
            return self._resolver._runner.available_packs

        def store_for(self, pack_id):
            return self._resolver.store_for_domain(pack_id)

        def data_version_summary(self):
            return self._resolver._summary_data_version() or ""

    adapter = _Adapter(parse_geo_resolver)

    # Inject a hit with a deny-listed surface ("of") directly into link_span.
    hit = _RawHit(
        start=10,
        end=12,
        surface="of",
        entity_ids=["country/KEN"],  # pretend the automaton matched it
        pack_id="geo",
    )

    outcome = link_span(
        hit,
        backend=adapter,
        base_context=None,
        confidence_threshold=None,
        ctx_cache={},
        include_nil=True,
    )

    assert isinstance(outcome, DroppedSpan), (
        f"Expected DroppedSpan for 'of', got: {outcome!r}"
    )
    assert outcome.reason == "deny_list", (
        f"Expected reason='deny_list', got: {outcome.reason!r}"
    )
    assert outcome.surface == "of"


def test_deny_list_gate_fires_for_the(parse_geo_resolver) -> None:
    """'the' with any entity_ids in the hit → DroppedSpan(reason='deny_list')."""
    from resolvekit.core.parse.automaton import _RawHit
    from resolvekit.core.parse.link import link_span
    from resolvekit.core.parse.result import DroppedSpan

    class _Adapter:
        def __init__(self, resolver) -> None:
            self._resolver = resolver

        def _resolve_one(self, text, *, context=None):
            import weakref

            from resolvekit.core.explain.protocol import Explainer

            resolver_as_explainer: Explainer = self._resolver  # type: ignore[assignment]
            ref = weakref.ref(resolver_as_explainer)
            return self._resolver._resolve_inner(
                text,
                normalized_domain=None,
                context=context,
                include_entity=False,
                timeout=None,
                _self_ref=ref,
            )

        @property
        def pack_normalizers(self):
            return self._resolver._pack_normalizers

        @property
        def available_packs(self):
            return self._resolver._runner.available_packs

        def store_for(self, pack_id):
            return self._resolver.store_for_domain(pack_id)

        def data_version_summary(self):
            return self._resolver._summary_data_version() or ""

    adapter = _Adapter(parse_geo_resolver)

    hit = _RawHit(
        start=0,
        end=3,
        surface="the",
        entity_ids=[],
        pack_id="geo",
    )

    outcome = link_span(
        hit,
        backend=adapter,
        base_context=None,
        confidence_threshold=None,
        ctx_cache={},
        include_nil=True,
    )

    assert isinstance(outcome, DroppedSpan)
    assert outcome.reason == "deny_list"


def test_entity_names_pass_deny_gate(parse_geo_resolver) -> None:
    """Legitimate entity name surfaces are not dropped by the deny-list gate."""
    from resolvekit.core.parse.automaton import _RawHit
    from resolvekit.core.parse.link import link_span
    from resolvekit.core.parse.result import DroppedSpan

    class _Adapter:
        def __init__(self, resolver) -> None:
            self._resolver = resolver

        def _resolve_one(self, text, *, context=None):
            import weakref

            from resolvekit.core.explain.protocol import Explainer

            resolver_as_explainer: Explainer = self._resolver  # type: ignore[assignment]
            ref = weakref.ref(resolver_as_explainer)
            return self._resolver._resolve_inner(
                text,
                normalized_domain=None,
                context=context,
                include_entity=False,
                timeout=None,
                _self_ref=ref,
            )

        @property
        def pack_normalizers(self):
            return self._resolver._pack_normalizers

        @property
        def available_packs(self):
            return self._resolver._runner.available_packs

        def store_for(self, pack_id):
            return self._resolver.store_for_domain(pack_id)

        def data_version_summary(self):
            return self._resolver._summary_data_version() or ""

    adapter = _Adapter(parse_geo_resolver)

    for surface, entity_ids in [
        ("Kenya", ["country/KEN"]),
        ("Somalia", ["country/SOM"]),
    ]:
        hit = _RawHit(
            start=0,
            end=len(surface),
            surface=surface,
            entity_ids=entity_ids,
            pack_id="geo",
        )
        outcome = link_span(
            hit,
            backend=adapter,
            base_context=None,
            confidence_threshold=None,
            ctx_cache={},
            include_nil=True,
        )
        assert not (
            isinstance(outcome, DroppedSpan) and outcome.reason == "deny_list"
        ), f"Entity name {surface!r} was incorrectly denied: {outcome!r}"
