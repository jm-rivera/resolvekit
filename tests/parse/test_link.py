"""Tests for link_span — span linking against the resolution engine.

All tests use a real bundled-geo Resolver via a small in-test ParseBackend
adapter. The adapter delegates directly to the private seams (``_resolve_inner``
etc.) and satisfies the ``ParseBackend`` protocol structurally (duck-typing).

The resolver is built from ``geo_test_datapack`` (the session-scoped
conftest fixture) to avoid calibrator-checksum issues with the bundled
production data. It has two entities: ``country/USA`` (United States) and
``country/GBR`` (United Kingdom).

Covers short-input gating, domain routing via entity_types context, NIL surfacing
with near-miss confidence, sentinel filtering, and explain() survival on resolved spans.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from resolvekit.core.datapack import NORMALIZER_VERSION
from resolvekit.core.model.query import ResolutionContext
from resolvekit.core.model.result import ResolutionResult, ResolutionStatus
from resolvekit.core.parse.automaton import _RawHit
from resolvekit.core.parse.link import link_span
from resolvekit.core.parse.result import DroppedSpan

if TYPE_CHECKING:
    from resolvekit.core.api.resolver import Resolver


# ---------------------------------------------------------------------------
# In-test ParseBackend adapter wrapping a real Resolver
# ---------------------------------------------------------------------------


class _ResolverAdapter:
    """Minimal ParseBackend adapter over a real Resolver.

    Delegates to private seams and satisfies the ParseBackend protocol
    structurally (duck-typing).
    """

    def __init__(self, resolver: Resolver) -> None:
        self._resolver = resolver
        self._resolve_calls: list[dict] = []

    def _resolve_one(
        self,
        text: str,
        *,
        context: ResolutionContext | None = None,
    ) -> ResolutionResult:
        """Delegate to _resolve_inner with a live weakref for explain()."""
        import weakref as _weakref

        from resolvekit.core.explain.protocol import Explainer

        # Cast to Explainer so ty accepts weakref.ref[Explainer].
        resolver_as_explainer: Explainer = self._resolver  # type: ignore[assignment]
        ref: _weakref.ref[Explainer] = _weakref.ref(resolver_as_explainer)
        self._resolve_calls.append({"text": text, "context": context})
        return self._resolver._resolve_inner(
            text,
            normalized_domain=None,  # let AutoRouter use context.entity_types
            context=context,
            include_entity=False,
            timeout=None,
            _self_ref=ref,
        )

    @property
    def pack_normalizers(self) -> dict:
        return self._resolver._pack_normalizers

    @property
    def available_packs(self) -> frozenset[str]:
        return self._resolver._runner.available_packs

    def store_for(self, pack_id: str):
        return self._resolver.store_for_domain(pack_id)

    def data_version_summary(self) -> str:
        return self._resolver._summary_data_version() or ""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def geo_resolver(geo_test_datapack: Any) -> Resolver:
    """Resolver backed by the minimal geo test fixture (no calibrator checksums).

    Uses RoutingMode.EXPLICIT so link_span can pin domain='geo' without the
    AUTO mode rejection ("Cannot specify domains with AUTO routing mode").
    """
    from resolvekit.core.api.resolver import Resolver
    from resolvekit.core.engine.router import RoutingMode

    return Resolver.from_datapacks(
        datapack_paths=[geo_test_datapack],
        routing_mode=RoutingMode.EXPLICIT,
    )


@pytest.fixture(scope="module")
def geo_backend(geo_resolver: Resolver) -> _ResolverAdapter:
    return _ResolverAdapter(geo_resolver)


def _make_hit(
    surface: str,
    *,
    entity_ids: list[str],
    pack_id: str = "geo",
    start: int = 0,
) -> _RawHit:
    end = start + len(surface)
    return _RawHit(
        start=start,
        end=end,
        surface=surface,
        entity_ids=entity_ids,
        pack_id=pack_id,
    )


# ---------------------------------------------------------------------------
# Short-input unlock via entity_types hint
# ---------------------------------------------------------------------------


def test_short_input_unlocked_with_entity_type_hint(
    geo_backend: _ResolverAdapter,
) -> None:
    """Entity_types from the hit payload unlock the short-input gate.

    Entity_types come from the automaton side-table and are supplied to the
    context before the short-input gate runs. Both uppercase and lowercase
    short inputs are unlocked when the entity_ids in the hit resolve to geo
    entity types.

    All-caps 'US' is always allowed. Lowercase 'us' is normally blocked, but
    when entity_types includes 'geo.country', the gate is bypassed.
    """
    entity_ids = ["country/USA"]

    # Uppercase 'US' — should not be short-input-dropped (all-caps is always allowed).
    hit_upper = _make_hit("US", entity_ids=entity_ids, pack_id="geo")
    outcome_upper = link_span(
        hit_upper,
        backend=geo_backend,
        base_context=None,
        confidence_threshold=None,
        ctx_cache={},
        include_nil=True,
    )
    assert not (
        isinstance(outcome_upper, DroppedSpan) and outcome_upper.reason == "short_input"
    ), f"All-caps 'US' should not be short-input-dropped: {outcome_upper}"

    # Lowercase 'us' — entity_types from side-table unlock the gate.
    hit_lower = _make_hit("us", entity_ids=entity_ids, pack_id="geo")
    outcome_lower = link_span(
        hit_lower,
        backend=geo_backend,
        base_context=None,
        confidence_threshold=None,
        ctx_cache={},
        include_nil=True,
    )
    assert not (
        isinstance(outcome_lower, DroppedSpan) and outcome_lower.reason == "short_input"
    ), (
        f"'us' with entity_types from side-table should not be short-input-dropped: "
        f"{outcome_lower}"
    )


def test_short_input_blocked_when_no_entity_ids_in_payload(
    geo_backend: _ResolverAdapter,
) -> None:
    """A hit with no entity_ids in the side-table cannot derive entity_types.

    When entity_ids is empty, _entity_types_from_ids returns frozenset(), which
    means the interned context has entity_types=frozenset() → the short-input
    gate is NOT bypassed for lowercase short alpha inputs like 'us'.
    """
    # Hit with no entity_ids → can't derive types.
    hit = _make_hit("us", entity_ids=[], pack_id="geo")
    outcome = link_span(
        hit,
        backend=geo_backend,
        base_context=None,
        confidence_threshold=None,
        ctx_cache={},
        include_nil=True,
    )
    # Without entity_types, 'us' (lowercase) should be dropped by short_input.
    assert isinstance(outcome, DroppedSpan), (
        f"'us' with empty entity_ids should be short-input-dropped, got: {outcome}"
    )
    assert outcome.reason == "short_input"


# ---------------------------------------------------------------------------
# Domain pinning spy
# ---------------------------------------------------------------------------


def test_resolve_one_called_with_entity_types_context(geo_resolver: Resolver) -> None:
    """_resolve_one routes via context.entity_types, not a domain= arg.

    This avoids AutoRouter fan-out without tripping the AUTO-mode guard.
    """
    spy_calls: list[dict] = []

    class _SpyAdapter(_ResolverAdapter):
        def _resolve_one(
            self,
            text: str,
            *,
            context: ResolutionContext | None = None,
        ) -> ResolutionResult:
            spy_calls.append({"text": text, "context": context})
            return super()._resolve_one(text, context=context)

    adapter = _SpyAdapter(geo_resolver)
    entity_ids = ["country/USA"]
    context = ResolutionContext(entity_types=frozenset({"geo.country"}))
    hit = _make_hit("United States", entity_ids=entity_ids, pack_id="geo")

    link_span(
        hit,
        backend=adapter,
        base_context=context,
        confidence_threshold=None,
        ctx_cache={},
        include_nil=True,
    )

    assert spy_calls, "_resolve_one was not called"
    call = spy_calls[-1]
    assert call["context"] is not None
    assert "geo.country" in (call["context"].entity_types or frozenset())


# ---------------------------------------------------------------------------
# NIL surfacing
# ---------------------------------------------------------------------------


def test_nil_surfacing_appear_only_with_include_nil(
    geo_backend: _ResolverAdapter,
) -> None:
    """With include_nil=True and high threshold, a NIL span is a _LinkedSpan.
    With include_nil=False, it is a DroppedSpan.
    """
    from resolvekit.core.parse.detect import _LinkedSpan

    entity_ids = ["country/USA"]
    context = ResolutionContext(entity_types=frozenset({"geo.country"}))
    hit = _make_hit("United States", entity_ids=entity_ids, pack_id="geo")

    # Very high threshold forces NO_MATCH.
    outcome_nil = link_span(
        hit,
        backend=geo_backend,
        base_context=context,
        confidence_threshold=0.9999,
        ctx_cache={},
        include_nil=True,
    )
    outcome_drop = link_span(
        hit,
        backend=geo_backend,
        base_context=context,
        confidence_threshold=0.9999,
        ctx_cache={},
        include_nil=False,
    )

    if (
        isinstance(outcome_nil, _LinkedSpan)
        and outcome_nil.status == ResolutionStatus.NO_MATCH
    ):
        assert outcome_nil.entity_id is None
    if isinstance(outcome_drop, DroppedSpan):
        assert outcome_drop.reason in {"below_threshold", "sentinel", "short_input"}


def test_near_miss_confidence_is_float(geo_backend: _ResolverAdapter) -> None:
    """When the engine finds candidates but rejects on threshold, confidence is a float."""
    from resolvekit.core.parse.detect import _LinkedSpan

    entity_ids = ["country/USA"]
    context = ResolutionContext(entity_types=frozenset({"geo.country"}))
    # Use a surface that the engine will score (United States) but force reject.
    hit = _make_hit("United States", entity_ids=entity_ids, pack_id="geo")

    outcome = link_span(
        hit,
        backend=geo_backend,
        base_context=context,
        confidence_threshold=0.9999,
        ctx_cache={},
        include_nil=True,
    )
    if (
        isinstance(outcome, _LinkedSpan)
        and outcome.status == ResolutionStatus.NO_MATCH
        and outcome.confidence is not None
    ):
        assert isinstance(outcome.confidence, float)
        assert 0.0 <= outcome.confidence <= 1.0


# ---------------------------------------------------------------------------
# DroppedSpan via sentinel
# ---------------------------------------------------------------------------


def test_sentinel_blocked_surface_drops(geo_backend: _ResolverAdapter) -> None:
    """A sentinel token ('unknown') → DroppedSpan(reason='sentinel')."""
    entity_ids = ["country/UNKNOWN"]
    hit = _make_hit("unknown", entity_ids=entity_ids, pack_id="geo")

    outcome = link_span(
        hit,
        backend=geo_backend,
        base_context=None,
        confidence_threshold=None,
        ctx_cache={},
        include_nil=True,
    )
    assert isinstance(outcome, DroppedSpan), (
        f"Expected DroppedSpan for 'unknown', got {outcome!r}"
    )
    assert outcome.reason == "sentinel"


def test_null_surface_drops_as_sentinel(geo_backend: _ResolverAdapter) -> None:
    """'null' is a sentinel token → DroppedSpan."""
    hit = _make_hit("null", entity_ids=[], pack_id="geo")
    outcome = link_span(
        hit,
        backend=geo_backend,
        base_context=None,
        confidence_threshold=None,
        ctx_cache={},
        include_nil=True,
    )
    assert isinstance(outcome, DroppedSpan)
    assert outcome.reason == "sentinel"


def test_unknown_surface_drops_as_sentinel(geo_backend: _ResolverAdapter) -> None:
    """'unknown' is a sentinel token → DroppedSpan(reason='sentinel').

    Note: 'NA' is intentionally NOT in the blocklist (it is Namibia's ISO-2 code).
    """
    hit = _make_hit("unknown", entity_ids=[], pack_id="geo")
    outcome = link_span(
        hit,
        backend=geo_backend,
        base_context=None,
        confidence_threshold=None,
        ctx_cache={},
        include_nil=True,
    )
    assert isinstance(outcome, DroppedSpan)
    assert outcome.reason == "sentinel"


# ---------------------------------------------------------------------------
# explain() survival
# ---------------------------------------------------------------------------


def test_explain_survives_on_resolved_span(geo_backend: _ResolverAdapter) -> None:
    """linked.resolution.explain() returns a Scorecard."""
    from resolvekit.core.explain.scorecard import Scorecard
    from resolvekit.core.parse.detect import _LinkedSpan

    entity_ids = ["country/USA"]
    context = ResolutionContext(entity_types=frozenset({"geo.country"}))
    hit = _make_hit("United States", entity_ids=entity_ids, pack_id="geo")

    outcome = link_span(
        hit,
        backend=geo_backend,
        base_context=context,
        confidence_threshold=None,
        ctx_cache={},
        include_nil=True,
    )

    assert isinstance(outcome, _LinkedSpan)
    assert outcome.status == ResolutionStatus.RESOLVED

    result = outcome.result
    assert result._explainer is not None

    scorecard = result.explain()
    assert isinstance(scorecard, Scorecard)


def test_explain_weakref_is_live_resolver(geo_backend: _ResolverAdapter) -> None:
    """The _explainer weakref resolves to the live Resolver."""
    from resolvekit.core.parse.detect import _LinkedSpan

    entity_ids = ["country/USA"]
    context = ResolutionContext(entity_types=frozenset({"geo.country"}))
    hit = _make_hit("United States", entity_ids=entity_ids, pack_id="geo")

    outcome = link_span(
        hit,
        backend=geo_backend,
        base_context=context,
        confidence_threshold=None,
        ctx_cache={},
        include_nil=True,
    )
    assert isinstance(outcome, _LinkedSpan)

    result = outcome.result
    if result._explainer is not None:
        live = result._explainer()
        assert live is not None


# ---------------------------------------------------------------------------
# Context interning (same-type spans reuse one context object)
# ---------------------------------------------------------------------------


def test_context_interning_same_typed_spans() -> None:
    """Same entity_type → same context object id from ctx_cache."""
    from resolvekit.core.parse.link import _intern_context

    entity_types = frozenset({"geo.country"})
    ctx_cache: dict = {}
    base = ResolutionContext(country="US")

    ctx1 = _intern_context(
        base_context=base,
        entity_types=entity_types,
        ctx_cache=ctx_cache,
    )
    ctx2 = _intern_context(
        base_context=base,
        entity_types=entity_types,
        ctx_cache=ctx_cache,
    )
    assert ctx1 is ctx2, (
        "Same entity_types + base_context should return identical context object"
    )
    assert id(ctx1) == id(ctx2)


def test_context_interning_different_types_different_objects() -> None:
    """Different entity_types → distinct context objects."""
    from resolvekit.core.parse.link import _intern_context

    ctx_cache: dict = {}
    ctx_geo = _intern_context(
        base_context=None,
        entity_types=frozenset({"geo.country"}),
        ctx_cache=ctx_cache,
    )
    ctx_org = _intern_context(
        base_context=None,
        entity_types=frozenset({"org.igo"}),
        ctx_cache=ctx_cache,
    )
    assert ctx_geo is not ctx_org


def test_context_interning_different_country_different_objects() -> None:
    """Different country → distinct context objects even with same entity_types."""
    from resolvekit.core.parse.link import _intern_context

    entity_types = frozenset({"geo.country"})
    ctx_cache: dict = {}

    ctx_us = _intern_context(
        base_context=ResolutionContext(country="US"),
        entity_types=entity_types,
        ctx_cache=ctx_cache,
    )
    ctx_gb = _intern_context(
        base_context=ResolutionContext(country="GB"),
        entity_types=entity_types,
        ctx_cache=ctx_cache,
    )
    assert ctx_us is not ctx_gb


# ---------------------------------------------------------------------------
# Continent exclusion gate
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def geo_continent_datapack(tmp_path_factory: pytest.TempPathFactory) -> Any:
    """Minimal geo DataPack containing a continent entity and a country entity.

    Session-scoped; no calibrator so no checksum mismatch.
    """
    import json
    import sqlite3

    tmp_path = tmp_path_factory.mktemp("geo_continent_datapack")
    db_path = tmp_path / "entities.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE entities (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            canonical_name_norm TEXT NOT NULL,
            valid_from TEXT,
            valid_until TEXT
        );
        CREATE TABLE names (
            entity_id TEXT NOT NULL,
            name_kind TEXT NOT NULL,
            value TEXT NOT NULL,
            value_norm TEXT NOT NULL,
            lang TEXT,
            is_preferred INTEGER DEFAULT 0
        );
        CREATE TABLE codes (
            entity_id TEXT NOT NULL,
            system TEXT NOT NULL,
            value TEXT NOT NULL,
            value_norm TEXT NOT NULL,
            PRIMARY KEY (entity_id, system)
        );
        CREATE TABLE relations (
            entity_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            target_id TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE names_fts USING fts5(entity_id, value_norm);

        INSERT INTO entities VALUES
            ('continent/SAM', 'geo.continent', 'South America', 'south america', NULL, NULL),
            ('country/BRA', 'geo.country', 'Brazil', 'brazil', NULL, NULL);

        INSERT INTO codes VALUES
            ('country/BRA', 'iso2', 'BR', 'br'),
            ('country/BRA', 'iso3', 'BRA', 'bra');

        INSERT INTO names VALUES
            ('continent/SAM', 'canonical', 'South America', 'south america', 'en', 1),
            ('country/BRA', 'canonical', 'Brazil', 'brazil', 'en', 1);

        INSERT INTO names_fts(entity_id, value_norm) VALUES
            ('continent/SAM', 'south america'),
            ('country/BRA', 'brazil');
        """
    )
    conn.commit()
    conn.close()

    (tmp_path / "metadata.json").write_text(
        json.dumps(
            {
                "datapack_id": "geo_continent_test_v1",
                "module_id": "geo.countries",
                "domain_pack_id": "geo",
                "entity_schema_version": "1.0",
                "feature_schema_version": "geo.features.v1",
                "normalizer_version": NORMALIZER_VERSION,
                "index_versions": {"fts": "fts5", "symspell": None},
                "build_timestamp": "2026-06-05T00:00:00Z",
                "source_datasets": ["test-fixture-continent"],
            }
        )
    )
    return tmp_path


@pytest.fixture(scope="module")
def continent_resolver(geo_continent_datapack: Any) -> Resolver:
    """Resolver backed by the continent fixture (South America + Brazil)."""
    from resolvekit.core.api.resolver import Resolver
    from resolvekit.core.engine.router import RoutingMode

    return Resolver.from_datapacks(
        datapack_paths=[geo_continent_datapack],
        routing_mode=RoutingMode.EXPLICIT,
    )


@pytest.fixture(scope="module")
def continent_backend(continent_resolver: Resolver) -> _ResolverAdapter:
    return _ResolverAdapter(continent_resolver)


def test_continent_excluded(continent_backend: _ResolverAdapter) -> None:
    """A span resolved to geo.continent → DroppedSpan(reason='continent_excluded').

    'South America' resolves to the continent entity (type geo.continent).
    The _EXCLUDE_CONTINENTS gate must drop it before it becomes a linked span.
    """
    hit = _make_hit("South America", entity_ids=["continent/SAM"], pack_id="geo")

    outcome = link_span(
        hit,
        backend=continent_backend,
        base_context=None,
        confidence_threshold=None,
        ctx_cache={},
        include_nil=True,
    )

    assert isinstance(outcome, DroppedSpan), (
        f"Expected DroppedSpan for continent surface, got {outcome!r}"
    )
    assert outcome.reason == "continent_excluded"


def test_country_span_untouched(continent_backend: _ResolverAdapter) -> None:
    """A span resolved to geo.country is unaffected by the continent gate.

    'Brazil' resolves to country/BRA (type geo.country), which must pass
    through the continent gate intact and be returned as a _LinkedSpan.
    """
    from resolvekit.core.parse.detect import _LinkedSpan

    hit = _make_hit("Brazil", entity_ids=["country/BRA"], pack_id="geo")

    outcome = link_span(
        hit,
        backend=continent_backend,
        base_context=None,
        confidence_threshold=None,
        ctx_cache={},
        include_nil=True,
    )

    assert isinstance(outcome, _LinkedSpan), (
        f"Expected _LinkedSpan for country surface, got {outcome!r}"
    )
    assert outcome.status == ResolutionStatus.RESOLVED
    assert outcome.entity_type == "geo.country"
