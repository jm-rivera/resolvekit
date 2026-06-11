"""Public API facade for resolution."""

import logging
import threading
import weakref
from collections.abc import Sequence
from datetime import date, datetime
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast, overload

if TYPE_CHECKING:
    import pandas

    from resolvekit.core.api.diagnostics import _DiagnosticsNamespace
    from resolvekit.core.api.info import ResolverInfo
    from resolvekit.core.api.output_view import OutputView
    from resolvekit.core.byod.result import AugmentResult
    from resolvekit.core.explain.protocol import Explainer
    from resolvekit.core.model.crosswalk import Crosswalk
    from resolvekit.core.parse.result import ParseResult
    from resolvekit.core.store import EntityStore

from resolvekit.core.api._pivot import pivot_entities, validate_scalar_pivot
from resolvekit.core.api.batch import BatchResolver
from resolvekit.core.api.cache import _QueryCache
from resolvekit.core.api.code_lookup import CodeLookup
from resolvekit.core.api.containment_api import ContainmentAPI
from resolvekit.core.api.group_api import GroupAPI
from resolvekit.core.api.loading import (
    _build_resolver_from_paths,
    _normalize_domain,
    _resolution_error,
    _resolve_requested_module_paths,
)
from resolvekit.core.api.output_spec import (
    UNSET,
    OutputSpec,
    _Unset,
    apply_resolved_output,
    compile_output_spec,
)
from resolvekit.core.api.query_prep import QueryPreparer
from resolvekit.core.api.resolve_flow import ResolveFlow
from resolvekit.core.api.suggest_flow import SuggestFlow
from resolvekit.core.datapack import DataPackMetadata, LoadedDataPack
from resolvekit.core.engine import PipelineResult, RoutingMode
from resolvekit.core.engine.interfaces import ResolverBackend
from resolvekit.core.errors import (
    AmbiguousResolutionError,
    EntityNotFoundError,
    NoModulesInstalledError,
    UnknownCodeSystemError,
    UnknownDomainError,
)
from resolvekit.core.explain import (
    TraceSink,
    Verbosity,
)
from resolvekit.core.explain.result_types import ExplainedResolution
from resolvekit.core.model import (
    CandidateSummary,
    EntityRecord,
    NormalizedText,
    Query,
    ReasonCode,
    ResolutionContext,
    ResolutionResult,
    ResolutionResultList,
    ResolutionStatus,
)
from resolvekit.core.model.entity_attributes import KNOWN_PIVOTS
from resolvekit.core.model.name_grammar import parse_name_grammar
from resolvekit.core.module_registry import list_available_modules
from resolvekit.core.store.sqlite import SQLiteTuning
from resolvekit.core.util.normalization import (
    NormalizationProfile,
    TextNormalizer,
)
from resolvekit.core.util.sentinel import DEFAULT_BLOCKLIST, SentinelBlocklist

logger = logging.getLogger(__name__)

# Default maximum query length for safety
DEFAULT_MAX_QUERY_LENGTH = 1000

# Accepted on_ambiguous policy values for resolve_id().
_ON_AMBIGUOUS_VALUES = ("raise", "null", "best")


def _on_ambiguous_error(value: object) -> str:
    """Build the ValueError message for an invalid on_ambiguous value."""
    import difflib

    msg = (
        f"on_ambiguous={value!r} is not valid; "
        f"expected one of {', '.join(repr(v) for v in _ON_AMBIGUOUS_VALUES)}"
    )
    if isinstance(value, str):
        close = difflib.get_close_matches(
            value.lower(), _ON_AMBIGUOUS_VALUES, n=1, cutoff=0.5
        )
        if close:
            msg += f"; did you mean {close[0]!r}?"
    return msg


def _validate_confidence_threshold(value: object) -> None:
    """Eagerly validate a ``confidence_threshold`` argument.

    Mirrors the eager, named validation ``timeout=`` gets: a non-numeric or
    out-of-range value raises at the call boundary instead of crashing deep in
    the parse/link pipeline only when a span happens to resolve.
    """
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(
            f"confidence_threshold={value!r} is not valid; "
            "expected a number in [0.0, 1.0] or None"
        )
    if not 0.0 <= value <= 1.0:
        raise ValueError(
            f"confidence_threshold={value!r} is out of range; "
            "expected a number in [0.0, 1.0] or None"
        )


def _coerce_as_of(value: "date | str | None") -> "date | None":
    """Coerce an ``as_of`` argument to ``datetime.date``.

    Mirrors ``ResolutionContext(as_of=...)``: ISO date strings
    (``"2020-01-01"``) are accepted and coerced, ``datetime``/``date`` pass
    through, and anything else raises a clear ``ValueError`` / ``TypeError``
    at the call boundary rather than crashing deep in the store layer.
    """
    if isinstance(value, datetime):
        return value.date()
    if value is None or isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as e:
            raise ValueError(
                f"as_of={value!r} is not a valid ISO date; "
                "expected a datetime.date or an ISO-8601 string like '2020-01-01'"
            ) from e
    raise TypeError(
        f"as_of must be a datetime.date or ISO-8601 string, got {type(value).__name__}"
    )


# Shared singleton used when callers pass context=None.  Reusing the same
# instance across calls keeps the query cache's id(context) key stable.
_DEFAULT_CONTEXT = ResolutionContext()
# Frozen by construction — see cache.py for why this matters.
# The query cache uses ``id(context)`` as part of the key; mutating the
# default context would silently poison cache entries across calls.
assert ResolutionContext.model_config.get("frozen", False), (
    "ResolutionContext must remain frozen — _DEFAULT_CONTEXT singleton "
    "depends on it for cache key stability."
)


# ExplainedResolution is the canonical type from explain/result_types; re-exported
# here so existing importers of resolvekit.core.api.resolver.ExplainedResolution
# continue to work without change.
__all__ = ["ExplainedResolution", "Resolver"]


class Resolver:
    """High-level API for entity resolution.

    Supports two modes:
    1. Direct runner injection for advanced embedding
    2. Module/datapack loading via from_modules() or from_datapacks()

    Key methods:
        resolve / bulk / snap — name/code → EntityRecord or scalar code
        entity — code or ID → EntityRecord
        related — forward relation walk (``contained_in``, etc.)
        within — reverse geographic containment walk (``contained_in``)
        members_of / is_member / known_groups — group membership
        parse / parse_bulk — extract entity mentions from free text
        from_records / augment — bring-your-own-data

    Example (multi-pack):
        resolver = Resolver.from_modules(module_ids=["geo.countries", "org.providers"])
        result = resolver.resolve("United States")
        print(result.entity_id)  # "country/USA"

    Example (direct runner injection):
        resolver = Resolver(runner=my_pipeline_runner)
        result = resolver.resolve("US")
    """

    def __init__(
        self,
        runner: ResolverBackend,
        *,
        normalizer: TextNormalizer | None = None,
        pack_profiles: dict[str, NormalizationProfile] | None = None,
        max_query_length: int = DEFAULT_MAX_QUERY_LENGTH,
        routing_mode: RoutingMode | None = None,
        loaded_modules: dict[str, list[LoadedDataPack]] | None = None,
        cache_size: int = 1024,
        sqlite_tuning: SQLiteTuning | None = None,
        default_timeout: float | None = None,
        confidence_threshold: float | None = None,
        sentinel_blocklist: SentinelBlocklist | None = DEFAULT_BLOCKLIST,
        default_to: str | list[str] | None = None,
        on_missing: "Literal['raise','null','auto']" = "auto",
        warm: bool = True,
    ) -> None:
        """Initialize Resolver.

        Args:
            runner: Pipeline runner (single or multi-pack)
            normalizer: Custom text normalizer (default: standard NFC+casefold)
            pack_profiles: Domain-specific normalization profiles (optional)
            max_query_length: Maximum query length before truncation (default: 1000)
            routing_mode: How to route queries across packs: ``AUTO``,
                ``EXPLICIT``, or ``HYBRID``.
            loaded_modules: Mapping of pack_id to its loaded base modules,
                used by ``info`` to surface data versions for reproducibility.
            cache_size: LRU result cache size. Default 1024 (LRU enabled).
                Pass ``cache_size=0`` to disable.

                For multi-threaded services, pass cache_size=0, or build one
                Resolver per worker thread. The cache is not GIL-safe.

                Each entry is a ResolutionResult (~2-10 KB depending on candidate
                count); 1024 entries is roughly 2-10 MB per Resolver.
            sqlite_tuning: SQLite connection tuning parameters. Forwarded by
                ``from_*``/``auto`` constructors at store-construction time;
                when ``None`` they use ``SQLiteTuning()`` defaults
                (pool_size=2, cache_size_mb=64, mmap_size_mb=128).
                Pass-through here is for symmetry; the runtime path of
                ``__init__`` does not consume it (the runner already holds
                pre-built stores).
            default_timeout: Default per-call timeout in seconds.  Per-call
                ``timeout=`` overrides this value.  ``None`` means no limit.
            confidence_threshold: Override the minimum calibrated score required
                to resolve a query.  The default (``None``) uses each pack's
                built-in threshold (0.70 with calibration, higher for heuristic
                packs).  Set a lower value (e.g. ``0.55``) to accept more
                results; set a higher value (e.g. ``0.85``) to be stricter.

                A NO_MATCH result caused by a score below this threshold carries
                ``result.confidence`` equal to the top candidate's calibrated
                score, letting callers distinguish a near-miss (e.g.
                ``confidence=0.66``) from a true no-candidate (``confidence=None``).

                Applies at construction time to all loaded packs.  Use the
                ``from_modules``/``from_datapacks``/``auto`` class methods to
                pass this option via their matching keyword argument.
            sentinel_blocklist: Set of normalized forms that are treated as
                placeholder / junk input and returned as NO_MATCH without
                consulting the pipeline.  Defaults to
                :data:`~resolvekit.core.util.sentinel.DEFAULT_BLOCKLIST`
                (covers "unknown", "n/a", "null", "999", etc.).

                To extend the defaults::

                    from resolvekit.core.util.sentinel import SentinelBlocklist
                    blocklist = SentinelBlocklist(extra={"lorem", "ipsum"})
                    resolver = Resolver.auto(sentinel_blocklist=blocklist)

                To disable the blocklist entirely::

                    resolver = Resolver.auto(sentinel_blocklist=None)
            default_to: Default output code system or name variant for
                ``resolve()``/``bulk()``/``snap()``.  A string (e.g. ``"iso3"``)
                or list of strings for a fallback chain (e.g. ``["iso3","name"]``).
                ``None`` (default) returns raw ``ResolutionResult`` (legacy).
            on_missing: Miss policy for the default output chain.
                ``"auto"`` (default) = raise for scalar ``resolve()``/``snap()``,
                null + ``UserWarning`` for ``bulk()``.
                ``"raise"`` = always raise ``OutputMissingError`` on miss.
                ``"null"`` = always return ``None`` on miss.
            warm: When ``True`` (default), start a background daemon thread
                immediately after construction that calls the runner's
                ``warm()`` to pre-build any lazily-constructed indexes (e.g.
                the geo large-tier SymSpell index on remote-data installs,
                which can take ~6 s).  Queries that arrive mid-build simply
                block on the per-source build lock for the remainder of the
                build.  Pass ``False`` to restore the previous fully-lazy
                behaviour.
        """
        self._runner = runner
        self._normalizer = normalizer or TextNormalizer()
        self._pack_profiles = pack_profiles or {}
        self._max_query_length = max_query_length
        self._routing_mode = routing_mode
        self._loaded_modules = loaded_modules or {}
        self._default_timeout = default_timeout
        self._confidence_threshold = confidence_threshold
        self._sentinel_blocklist = sentinel_blocklist
        # sqlite_tuning kwarg accepted for parity with from_*; not consumed
        # here because the runner is passed in pre-built.
        del sqlite_tuning
        # Apply confidence_threshold override to all loaded pack decision policies.
        if confidence_threshold is not None:
            self._apply_confidence_threshold_override(confidence_threshold)
        self._closed = False
        self._query_cache: _QueryCache | None = (
            _QueryCache(maxsize=cache_size) if cache_size > 0 else None
        )

        self._pack_normalizers: dict[str, TextNormalizer] = {}
        for pack_id, profile in self._pack_profiles.items():
            self._pack_normalizers[pack_id] = TextNormalizer(profile)

        # Collaborators — constructed once, reused across all calls.
        self._query_preparer = QueryPreparer(
            runner=runner,
            normalizer=self._normalizer,
            pack_normalizers=self._pack_normalizers,
            max_query_length=max_query_length,
            routing_mode=routing_mode,
            default_context=_DEFAULT_CONTEXT,
        )
        self._code_lookup = CodeLookup(runner=runner)
        self._group_api = GroupAPI(runner=runner)
        self._containment_api = ContainmentAPI(runner=runner)
        self._batch_resolver = BatchResolver(
            runner=runner,
            query_preparer=self._query_preparer,
            routing_mode=routing_mode,
            default_timeout=default_timeout,
        )
        self._resolve_flow = ResolveFlow(
            runner=runner,
            query_preparer=self._query_preparer,
            group_api=self._group_api,
            query_cache=self._query_cache,
            max_query_length=max_query_length,
            default_timeout=default_timeout,
        )

        # Compile the default output spec now that collaborators (and thus
        # code_systems()) are available.  Store the raw args too so bulk()
        # can recompile with a per-call on_missing override cheaply.
        self._default_to_raw = default_to
        self._on_missing_raw = on_missing
        self._output_spec: OutputSpec | None = (
            compile_output_spec(
                default_to, on_missing, known_systems=self.code_systems()
            )
            if default_to is not None
            else None
        )

        # SuggestFlow is constructed after _output_spec so it can thread
        # the compiled default spec without re-compiling it.
        self._suggest_flow = SuggestFlow(
            runner=runner,
            query_preparer=self._query_preparer,
            max_query_length=max_query_length,
            default_output_spec=self._output_spec,
        )

        # Background warm-up: pre-build lazily-constructed source indexes so
        # the first fuzzy/symspell query does not pay the build cost inline.
        if warm:
            runner_warm = getattr(self._runner, "warm", None)
            if callable(runner_warm):

                def _warm_runner() -> None:
                    try:
                        runner_warm()
                    except Exception:
                        logger.debug(
                            "Background warm-up raised an exception; "
                            "sources will build lazily on first use.",
                            exc_info=True,
                        )

                t = threading.Thread(
                    target=_warm_runner,
                    name="resolvekit-warm",
                    daemon=True,
                )
                t.start()

    def _apply_confidence_threshold_override(self, value: float) -> None:
        """Set confidence_threshold on every pack's decision policy.

        Applies to single-pack (``PipelineRunner``) and multi-pack
        (``MultiPackRunner``) backends via the runner's own method.
        Decision policies that are ``ThresholdDecisionPolicy`` instances are
        updated; others are silently skipped.

        Emits a warning when zero policies are found — this means the caller's
        ``confidence_threshold`` argument was silently ignored, which is almost
        always a misconfiguration (wrong runner type or no loaded packs).
        """
        _apply = getattr(self._runner, "apply_confidence_threshold", None)
        if not callable(_apply) or not _apply(threshold=value):
            logger.warning(
                "confidence_threshold=%.4f was passed but no ThresholdDecisionPolicy "
                "was found on any runner — the override had no effect. "
                "Check that the resolver was built with a compatible runner type.",
                value,
            )

    def close(self) -> None:
        """Release resources held by the resolver.

        Closes all stores owned by the underlying runner and evicts their
        automaton-cache entries so stores can be GC'd after close.
        Safe to call multiple times (idempotent).
        After close(), calling resolve() raises RuntimeError.
        """
        if self._closed:
            return
        self._closed = True
        # Evict automaton-cache entries for every store this resolver owns
        # so the module-level cache does not strong-ref stores indefinitely.
        import contextlib

        from resolvekit.core.parse.automaton import invalidate as _invalidate_automaton

        for pack_id in self._runner.available_packs:
            with contextlib.suppress(ValueError, AttributeError):
                _invalidate_automaton(self._runner.store_for_domain(pack_id))
        self._runner.close()

    def warm(self) -> None:
        """Build all lazily-constructed indexes now, synchronously.

        Blocks until every source's internal index (e.g. the SymSpell
        dictionary) has been built.  Safe to call concurrently with the
        background warm-up thread started by ``__init__`` — per-source build
        locks make the operation idempotent.  Useful for servers and batch
        jobs that want to ensure full performance before handling the first
        real request.

        Note: constructing a Resolver with the default ``warm=True`` already
        starts a background warm-up; call this method when you need to block
        until that warm-up is complete.
        """
        runner_warm = getattr(self._runner, "warm", None)
        if callable(runner_warm):
            runner_warm()

    def __enter__(self) -> "Resolver":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @cached_property
    def diagnostics(self) -> "_DiagnosticsNamespace":
        """Diagnostics namespace: ``inspect``, ``search``, ``cache.info``, ``cache.clear``.

        Example::

            report = resolver.diagnostics.inspect("United States")
            candidates = resolver.diagnostics.search("US", top_k=5)
            info = resolver.diagnostics.cache.info()
            resolver.diagnostics.cache.clear()
        """
        from resolvekit.core.api.diagnostics import _DiagnosticsNamespace

        return _DiagnosticsNamespace(self)

    def _search_internal(
        self,
        text: str,
        *,
        top_k: int = 10,
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
    ) -> list[CandidateSummary]:
        """Internal search implementation delegated to by ``diagnostics.search``."""
        if self._closed:
            raise RuntimeError("Resolver has been closed")
        return self._resolve_flow.search_internal(
            text, top_k=top_k, domain=domain, context=context
        )

    def _resolve_one(
        self,
        text: str,
        *,
        context: ResolutionContext | None,
    ) -> ResolutionResult:
        """Resolve *text* for one span; returns a ``ResolutionResult`` with ``_explainer`` set.

        This is the linking path used by the parse engine.  Unlike ``resolve()``,
        it intentionally passes ``normalized_domain=None`` so that the AutoRouter
        can use ``context.entity_types`` to select the correct pack without
        tripping the AUTO-mode domain-pinning guard in ``QueryPreparer.prepare_query``.

        The ``context`` supplied by ``link_span`` always carries ``entity_types``
        derived from the automaton side-table, so the AutoRouter routes to the
        right pack via the ``ResolutionContext`` hint path rather than the
        ``query.domains`` path — no routing-mode conflict arises.

        Args:
            text: Span surface (raw input substring).
            context: Per-span context carrying ``entity_types`` (from the
                automaton payload) plus any caller-supplied country/as_of hints.

        Returns:
            ``ResolutionResult`` with a live ``_explainer`` weakref so
            ``result.explain()`` works on the returned span.
        """
        return self._resolve_inner(
            text,
            normalized_domain=None,  # let AutoRouter use context.entity_types
            context=context,
            include_entity=False,
            timeout=None,
            _self_ref=weakref.ref(self),
        )

    # ------------------------------------------------------------------
    # ParseBackend protocol adapters
    # ------------------------------------------------------------------

    @property
    def pack_normalizers(self) -> dict[str, "TextNormalizer"]:
        """Per-pack ``TextNormalizer`` instances keyed by pack ID."""
        return self._pack_normalizers

    @property
    def available_packs(self) -> frozenset[str]:
        """Set of pack IDs loaded in this resolver."""
        return self._runner.available_packs

    def store_for(self, pack_id: str) -> "EntityStore":
        """Return the ``EntityStore`` backing *pack_id*.

        Delegates to ``store_for_domain``; raises ``ValueError`` when not found.
        """
        return self.store_for_domain(pack_id)

    def data_version_summary(self) -> str:
        """Return the opaque data-version string, or empty string."""
        return self._summary_data_version() or ""

    @property
    def domains(self) -> list[str]:
        """Return sorted list of available domain pack IDs."""
        return sorted(self._runner.available_packs)

    @property
    def info(self) -> "ResolverInfo":
        """Structured information about this resolver's configuration.

        Returns a :class:`~resolvekit.core.api.info.ResolverInfo` typed
        object with attribute access.  Use ``resolver.info.data_version``
        instead of the old ``resolver.info()["data_version"]``.

        Returns:
            :class:`~resolvekit.core.api.info.ResolverInfo` instance.
        """
        from resolvekit import __version__
        from resolvekit.core.api.info import build_resolver_info
        from resolvekit.core.api.modules import modules as _list_modules

        mode = self._routing_mode.value if self._routing_mode else "auto"
        cache_info = self._query_cache.info() if self._query_cache is not None else None
        try:
            modules_catalog = tuple(_list_modules())
        except Exception:
            modules_catalog = ()

        return build_resolver_info(
            domains=tuple(self.domains),
            routing_mode=mode,
            max_query_length=self._max_query_length,
            closed=self._closed,
            resolvekit_version=__version__,
            loaded_modules=self._loaded_modules,
            data_version=self._summary_data_version(),
            cache_info=cache_info,
            modules_catalog=modules_catalog,
        )

    def available_entity_types(self) -> frozenset[str]:
        """Return the fine-grained entity types declared by loaded packs.

        Returns dotted types such as ``"geo.country"`` — the same granularity
        ``ResolutionContext(entity_types=...)`` accepts and that
        :func:`resolvekit.modules` reports — so callers can feed the result
        straight into a refinement query.

        Resolvers built from the bundled catalog (``lite()``, ``auto()``,
        ``from_modules()``) report full types from the module manifest. A
        resolver built from raw datapack paths that are absent from the
        manifest falls back to the coarse domain prefixes the runner declares
        (e.g. ``"geo"``).
        """
        full = self._full_entity_types()
        return full if full is not None else self._runner.available_entity_types

    def _full_entity_types(self) -> frozenset[str] | None:
        """Map every loaded module to its manifest entity types.

        Returns ``None`` when any loaded module is missing from the manifest
        (e.g. raw ``from_datapacks`` paths), signalling the caller to fall back
        to the runner's coarse prefixes rather than report mixed granularity.
        """
        from resolvekit.core.api.modules import modules as _list_modules

        loaded_ids = {
            module.metadata.module_id
            for modules in self._loaded_modules.values()
            for module in modules
        }
        if not loaded_ids:
            return None
        by_id = {info.module_id: info.entity_types for info in _list_modules()}
        if not loaded_ids <= by_id.keys():
            return None
        types: set[str] = set()
        for module_id in loaded_ids:
            types.update(by_id[module_id])
        return frozenset(types) if types else None

    def code_systems(self) -> frozenset[str]:
        """Return all code system names known to loaded packs."""
        return self._runner.available_code_systems

    def _validate_parse_domain(self, domain: str | list[str] | None) -> None:
        """Reject unknown ``domain`` names for parse(), mirroring resolve().

        ``parse()`` detects over every loaded pack regardless of routing mode,
        so an unknown name is always a caller typo. The parse engine silently
        intersects requested domains with the available packs; validating here
        surfaces a typo as ``UnknownDomainError`` instead of an empty result
        indistinguishable from "no entities found".
        """
        if domain is None:
            return
        requested = _normalize_domain(domain)
        if not requested:
            return
        available = self._runner.available_packs
        if not available:
            return
        unknown = sorted(requested - available)
        if unknown:
            raise UnknownDomainError(unknown, sorted(available))

    # ------------------------------------------------------------------
    # Group / membership surface — thin delegations to GroupAPI
    # ------------------------------------------------------------------

    def members_of(
        self,
        group: str,
        *,
        as_of: date | str | None = None,
        as_codes: str | None = None,
    ) -> list[str]:
        """Return entity IDs (or codes) of all members of the given group.

        Args:
            group: Group name, abbreviation, or entity ID. Same forms as resolve().
                Examples: "EU", "European Union", "country/EuropeanUnion", "NATO",
                "EU27", "G8".
            as_of: Reference date for membership lookup. Defaults to today.
                Accepts a ``datetime.date`` or an ISO-8601 string
                (``"2020-01-01"``); an invalid string raises ``ValueError``.
                **Warning:** For snapshot entities (frozen membership, e.g.
                "EU27", "EU28", "G8", "BRIC"), as_of has no effect — passing one
                emits a UserWarning so callers iterating future-state scenarios
                see the mismatch. Snapshot membership is by definition fixed.
            as_codes: When None (default), returns sorted entity_ids. Pass a
                code system name (e.g. ``"iso3"``, ``"iso2"``) to return code
                values instead. Must be a system known to the loaded packs;
                raises ``UnknownCodeSystemError`` for unrecognized systems.

        Returns:
            Sorted list of member entity_ids, or sorted code strings when
            as_codes is set. The code-form list may be shorter than the
            entity_id form when entities lack the requested code (e.g. some
            "iso2" codes are missing for special territories).

        Raises:
            GroupNotFoundError: If group does not resolve to any entity
                (the entity does not exist).
            AmbiguousResolutionError: If group resolves ambiguously.
            ResolutionError: If the resolution pipeline errored (e.g. store
                outage) — distinct from GroupNotFoundError ("we couldn't
                tell" vs. "it does not exist").
            UnknownCodeSystemError: If as_codes is not a recognized code system.
            RuntimeError: If the resolver has been closed.
        """
        if self._closed:
            raise RuntimeError("Resolver has been closed")
        return self._group_api.members_of(
            group,
            as_of=_coerce_as_of(as_of),
            as_codes=as_codes,
            resolve_fn=self.resolve,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        )

    def is_member(
        self,
        country: str,
        group: str,
        *,
        as_of: date | str | None = None,
    ) -> bool:
        """Check whether a country is a member of a group on the given date.

        Args:
            country: Country name, code, or entity ID (same forms as resolve()).
            group: Group name, abbreviation, or entity ID.
            as_of: Reference date. Defaults to today.  Accepts a
                ``datetime.date`` or an ISO-8601 string (``"2020-01-01"``).
                **Warning:** For snapshot groups, as_of has no effect; passing
                one emits a UserWarning.

        Returns:
            True if the country is a member of the group on the reference date.

        Raises:
            GroupNotFoundError: If country or group does not resolve to any
                entity (the entity does not exist).
            AmbiguousResolutionError: If country or group resolves ambiguously.
            ResolutionError: If the resolution pipeline errored (e.g. store
                outage) — distinct from GroupNotFoundError ("we couldn't
                tell" vs. "it does not exist").
            RuntimeError: If the resolver has been closed.
        """
        if self._closed:
            raise RuntimeError("Resolver has been closed")
        return self._group_api.is_member(
            country,
            group,
            as_of=_coerce_as_of(as_of),
            resolve_fn=self.resolve,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        )

    def known_groups(self) -> list[str]:
        """Return canonical names of all queryable group entities, sorted.

        Enumerates types declared by each loaded pack's
        group_entity_types property — there is no hardcoded type set.

        Returns:
            Sorted list of canonical names (e.g. ["African Union", "ASEAN",
            "BRICS", "European Union", ...]).

        Raises:
            RuntimeError: If the resolver has been closed.
        """
        if self._closed:
            raise RuntimeError("Resolver has been closed")
        return self._group_api.known_groups()

    def _resolve_group_id(self, text: str) -> str:
        return self._group_api.resolve_group_id(text, resolve_fn=self.resolve)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    def _apply_group_preference_tiebreak(
        self, result: ResolutionResult
    ) -> ResolutionResult:
        return self._group_api.apply_group_preference_tiebreak(result)

    def _all_pack_group_types(self) -> frozenset[str]:
        return self._runner.available_group_types

    def __repr__(self) -> str:
        domains = self.domains
        mode = self._routing_mode.value if self._routing_mode else "auto"
        state = "closed" if self._closed else "open"
        data_version = self._summary_data_version()
        return (
            f"Resolver(domains={domains}, routing='{mode}', "
            f"state='{state}', data_version={data_version!r})"
        )

    def _summary_data_version(self) -> str | None:
        """Summary CalVer across all loaded modules, mirroring ``info.data_version``."""
        ordered = [
            module.metadata
            for pack_id in sorted(self._loaded_modules)
            for module in sorted(
                self._loaded_modules[pack_id], key=lambda m: m.module_id
            )
        ]
        return next(
            (m.data_version for m in ordered if m.data_version),
            next((m.datapack_id for m in ordered), None),
        )

    @classmethod
    def from_datapacks(
        cls,
        *,
        datapack_paths: list[str | Path],
        domains: list[str] | None = None,
        routing_mode: RoutingMode = RoutingMode.AUTO,
        trace: bool | TraceSink = False,
        normalizer: TextNormalizer | None = None,
        max_query_length: int = DEFAULT_MAX_QUERY_LENGTH,
        cache_size: int = 1024,
        sqlite_tuning: SQLiteTuning | None = None,
        default_timeout: float | None = None,
        confidence_threshold: float | None = None,
        sentinel_blocklist: SentinelBlocklist | None = DEFAULT_BLOCKLIST,
        default_to: str | list[str] | None = None,
        on_missing: "Literal['raise','null','auto']" = "auto",
        warm: bool = True,
    ) -> "Resolver":
        """Create resolver from one or more explicit datapack filesystem paths.

        Args:
            datapack_paths: Paths to DataPack directories (with metadata.json).
            domains: Which domain packs to enable (default: all in datapacks).
            routing_mode: How to route queries (see ``Resolver.__init__`` for full docs).
            trace: Whether to collect trace events. Pass True for an in-memory
                sink, or a TraceSink instance to use directly.
            normalizer: Custom text normalizer (see ``Resolver.__init__`` for full docs).
            max_query_length: Maximum query length before truncation (see
                ``Resolver.__init__`` for full docs).
            cache_size: LRU result cache size (see ``Resolver.__init__`` for full docs).
            sqlite_tuning: SQLite connection tuning parameters (see
                ``Resolver.__init__`` for full docs).
            default_timeout: Default per-call timeout in seconds (see
                ``Resolver.__init__`` for full docs).
            confidence_threshold: Override the minimum calibrated score required
                to resolve a query (see ``Resolver.__init__`` for full docs).
            sentinel_blocklist: Placeholder/junk blocklist (see
                ``Resolver.__init__`` for full docs).
            default_to: Default output code system or name variant (see
                ``Resolver.__init__`` for full docs).
            on_missing: Miss policy for the default output chain (see
                ``Resolver.__init__`` for full docs).
            warm: Start a background index warm-up on construction (see
                ``Resolver.__init__`` for full docs).

        Returns:
            Configured Resolver instance
        """
        return _build_resolver_from_paths(
            cls=cls,
            datapack_paths=datapack_paths,
            packs=domains,
            routing_mode=routing_mode,
            trace=trace,
            normalizer=normalizer,
            max_query_length=max_query_length,
            cache_size=cache_size,
            sqlite_tuning=sqlite_tuning,
            default_timeout=default_timeout,
            confidence_threshold=confidence_threshold,
            sentinel_blocklist=sentinel_blocklist,
            default_to=default_to,
            on_missing=on_missing,
            warm=warm,
        )

    @classmethod
    def from_modules(
        cls,
        *,
        module_ids: list[str] | None = None,
        domains: list[str] | None = None,
        routing_mode: RoutingMode = RoutingMode.AUTO,
        trace: bool | TraceSink = False,
        normalizer: TextNormalizer | None = None,
        max_query_length: int = DEFAULT_MAX_QUERY_LENGTH,
        cache_size: int = 1024,
        sqlite_tuning: SQLiteTuning | None = None,
        default_timeout: float | None = None,
        confidence_threshold: float | None = None,
        sentinel_blocklist: SentinelBlocklist | None = DEFAULT_BLOCKLIST,
        default_to: str | list[str] | None = None,
        on_missing: "Literal['raise','null','auto']" = "auto",
        warm: bool = True,
    ) -> "Resolver":
        """Create resolver from installed or explicitly registered modules.

        Args:
            module_ids: Specific module IDs to load (e.g. ``["geo.countries"]``).
                Pass ``None`` to load all installed modules (same as ``auto()``).
            domains: Which domain packs to enable (default: all in modules).
            routing_mode: How to route queries (see ``Resolver.__init__`` for full docs).
            trace: Whether to collect trace events.
            normalizer: Custom text normalizer (see ``Resolver.__init__`` for full docs).
            max_query_length: Maximum query length before truncation (see
                ``Resolver.__init__`` for full docs).
            cache_size: LRU result cache size (see ``Resolver.__init__`` for full docs).
            sqlite_tuning: SQLite connection tuning parameters (see
                ``Resolver.__init__`` for full docs).
            default_timeout: Default per-call timeout in seconds (see
                ``Resolver.__init__`` for full docs).
            confidence_threshold: Override the minimum calibrated score required
                to resolve a query (see ``Resolver.__init__`` for full docs).
            sentinel_blocklist: Placeholder/junk blocklist (see
                ``Resolver.__init__`` for full docs).
            default_to: Default output code system or name variant (see
                ``Resolver.__init__`` for full docs).
            on_missing: Miss policy for the default output chain (see
                ``Resolver.__init__`` for full docs).
            warm: Start a background index warm-up on construction (see
                ``Resolver.__init__`` for full docs).

        Returns:
            Configured Resolver instance
        """
        module_paths = _resolve_requested_module_paths(module_ids)
        return _build_resolver_from_paths(
            cls=cls,
            datapack_paths=list(module_paths.values()),
            packs=domains,
            routing_mode=routing_mode,
            trace=trace,
            normalizer=normalizer,
            max_query_length=max_query_length,
            cache_size=cache_size,
            sqlite_tuning=sqlite_tuning,
            default_timeout=default_timeout,
            confidence_threshold=confidence_threshold,
            sentinel_blocklist=sentinel_blocklist,
            default_to=default_to,
            on_missing=on_missing,
            warm=warm,
        )

    @classmethod
    def auto(
        cls,
        *,
        domains: list[str] | None = None,
        routing_mode: RoutingMode = RoutingMode.AUTO,
        trace: bool | TraceSink = False,
        normalizer: TextNormalizer | None = None,
        max_query_length: int = DEFAULT_MAX_QUERY_LENGTH,
        cache_size: int = 1024,
        sqlite_tuning: SQLiteTuning | None = None,
        default_timeout: float | None = None,
        confidence_threshold: float | None = None,
        sentinel_blocklist: SentinelBlocklist | None = DEFAULT_BLOCKLIST,
        default_to: str | list[str] | None = None,
        on_missing: "Literal['raise','null','auto']" = "auto",
        warm: bool = True,
    ) -> "Resolver":
        """Create resolver from all installed modules.

        Discovers every installed module and builds a resolver.
        Optionally filter by domain pack ID.

        Args:
            domains: If given, only include modules whose domain_pack_id
                is in this list.
            routing_mode: How to route queries (see ``Resolver.__init__`` for full docs).
            trace: Whether to collect trace events. Pass True for an in-memory
                sink, or a TraceSink instance to use directly.
            normalizer: Custom text normalizer (see ``Resolver.__init__`` for full docs).
            max_query_length: Maximum query length before truncation (see
                ``Resolver.__init__`` for full docs).
            cache_size: LRU result cache size (see ``Resolver.__init__`` for full docs).
            sqlite_tuning: SQLite connection tuning parameters (see
                ``Resolver.__init__`` for full docs).
            default_timeout: Default per-call timeout in seconds (see
                ``Resolver.__init__`` for full docs).
            confidence_threshold: Override the minimum calibrated score required
                to resolve a query (see ``Resolver.__init__`` for full docs).
            sentinel_blocklist: Placeholder/junk blocklist (see
                ``Resolver.__init__`` for full docs).
            default_to: Default output code system or name variant (see
                ``Resolver.__init__`` for full docs).
            on_missing: Miss policy for the default output chain (see
                ``Resolver.__init__`` for full docs).
            warm: Start a background index warm-up on construction (see
                ``Resolver.__init__`` for full docs).

        Returns:
            Configured Resolver instance
        """
        available = list_available_modules()
        if not available:
            raise NoModulesInstalledError()
        if domains is not None:
            from resolvekit.core.api.loading.module_catalog import (
                _module_data_locally_available,
            )
            from resolvekit.core.module_registry import get_manifest_overrides

            manifest_overrides = get_manifest_overrides()
            domain_set = set(domains)
            available_domains: set[str] = set()
            filtered_paths = []
            for module_id, path in available.items():
                meta = DataPackMetadata.from_file(path / "metadata.json")
                available_domains.add(meta.domain_pack_id)
                if meta.domain_pack_id in domain_set and _module_data_locally_available(
                    module_id, path, manifest_overrides
                ):
                    filtered_paths.append(path)
            missing_domains = sorted(domain_set - available_domains)
            if missing_domains:
                raise UnknownDomainError(missing_domains, sorted(available_domains))
            return cls.from_datapacks(
                datapack_paths=filtered_paths,
                routing_mode=routing_mode,
                trace=trace,
                normalizer=normalizer,
                max_query_length=max_query_length,
                cache_size=cache_size,
                sqlite_tuning=sqlite_tuning,
                default_timeout=default_timeout,
                confidence_threshold=confidence_threshold,
                sentinel_blocklist=sentinel_blocklist,
                default_to=default_to,
                on_missing=on_missing,
                warm=warm,
            )
        return cls.from_modules(
            routing_mode=routing_mode,
            trace=trace,
            normalizer=normalizer,
            max_query_length=max_query_length,
            cache_size=cache_size,
            sqlite_tuning=sqlite_tuning,
            default_timeout=default_timeout,
            confidence_threshold=confidence_threshold,
            sentinel_blocklist=sentinel_blocklist,
            default_to=default_to,
            on_missing=on_missing,
            warm=warm,
        )

    # -- Country-level geo module IDs for the lite preset --
    # Deliberately excludes geo.admin1 and deeper tiers whose dependency
    # chains (admin2, admin3, cities …) trigger heavy SQLite composition.
    # To add admin-1 coverage, pass module_ids=["geo.countries", "geo.admin1"].
    _LITE_GEO_MODULE_IDS: tuple[str, ...] = (
        "geo.countries",
        "geo.regions",
        "geo.continents",
        "geo.continental_unions",
    )

    @classmethod
    def lite(
        cls,
        *,
        module_ids: list[str] | None = None,
        routing_mode: RoutingMode = RoutingMode.AUTO,
        trace: bool | TraceSink = False,
        normalizer: TextNormalizer | None = None,
        max_query_length: int = DEFAULT_MAX_QUERY_LENGTH,
        cache_size: int = 1024,
        sqlite_tuning: SQLiteTuning | None = None,
        default_timeout: float | None = None,
        confidence_threshold: float | None = None,
        sentinel_blocklist: SentinelBlocklist | None = DEFAULT_BLOCKLIST,
        default_to: str | list[str] | None = None,
        on_missing: "Literal['raise','null','auto']" = "auto",
        warm: bool = True,
    ) -> "Resolver":
        """Create a footprint-optimised resolver from a curated small module set.

        Loads only country-level geo modules by default
        (``geo.countries``, ``geo.regions``, ``geo.continents``,
        ``geo.continental_unions``).  This skips the large admin and cities
        dictionaries, reducing cold-start time and RSS compared with
        :meth:`auto`.

        The SymSpell index for these modules is still built **lazily** on the
        first fuzzy query — the common exact-name / code resolution path has
        essentially zero extra cost.

        Callers that need a custom module set can pass *module_ids* explicitly;
        passing ``None`` (the default) uses the built-in lite selection.

        Note: ``auto()`` remains the default and covers the full breadth of
        available modules.  Use ``lite()`` when startup latency or resident
        memory is the primary constraint and country-level resolution suffices.

        To add admin-1 coverage at higher memory cost::

            resolver = Resolver.lite(module_ids=["geo.countries", "geo.admin1"])

        Args:
            module_ids: Override the lite module set.  Pass a list of module
                IDs (e.g. ``["geo.countries"]``) or ``None`` to use the
                built-in lite selection.
            routing_mode: How to route queries (see ``Resolver.__init__`` for full docs).
            trace: Whether to collect trace events.
            normalizer: Custom text normalizer (see ``Resolver.__init__`` for full docs).
            max_query_length: Maximum query length before truncation (see
                ``Resolver.__init__`` for full docs).
            cache_size: LRU result cache size (see ``Resolver.__init__`` for full docs).
            sqlite_tuning: SQLite connection tuning parameters (see
                ``Resolver.__init__`` for full docs).
            default_timeout: Default per-call timeout in seconds (see
                ``Resolver.__init__`` for full docs).
            confidence_threshold: Override the minimum calibrated score required
                to resolve a query (see ``Resolver.__init__`` for full docs).
            sentinel_blocklist: Placeholder/junk blocklist (see
                ``Resolver.__init__`` for full docs).
            default_to: Default output code system or name variant (see
                ``Resolver.__init__`` for full docs).
            on_missing: Miss policy for the default output chain (see
                ``Resolver.__init__`` for full docs).
            warm: Start a background index warm-up on construction (see
                ``Resolver.__init__`` for full docs).

        Returns:
            Configured Resolver instance
        """
        ids = (
            list(module_ids)
            if module_ids is not None
            else list(cls._LITE_GEO_MODULE_IDS)
        )
        return cls.from_modules(
            module_ids=ids,
            routing_mode=routing_mode,
            trace=trace,
            normalizer=normalizer,
            max_query_length=max_query_length,
            cache_size=cache_size,
            sqlite_tuning=sqlite_tuning,
            default_timeout=default_timeout,
            confidence_threshold=confidence_threshold,
            sentinel_blocklist=sentinel_blocklist,
            default_to=default_to,
            on_missing=on_missing,
            warm=warm,
        )

    def entity(
        self,
        text_or_id: str | None = None,
        *,
        alpha_2: str | None = None,
        alpha_3: str | None = None,
        numeric: str | None = None,
        iso2: str | None = None,
        iso3: str | None = None,
        dcid: str | None = None,
        domain: str | list[str] | None = None,
        **code_kwargs: str,
    ) -> EntityRecord | None:
        """Look up a fully hydrated entity by text, ID, or code.

        Resolution order:
        1. If any code-system kwarg is set (``alpha_2``, ``iso2``, etc.),
           look up via that code system.
        2. Else if ``text_or_id`` looks like an entity ID
           (e.g. ``"country/USA"``), call ``_runner.get_entity()`` directly.
        3. Else resolve ``text_or_id`` as free text and return the entity.

        Ambiguous matches raise :class:`AmbiguousResolutionError` from every
        path (code-lookup and free-text alike) — there's no silent path that
        masks ambiguity behind ``None``.

        Args:
            text_or_id: Entity text or ID (e.g. ``"United States"`` or
                ``"country/USA"``).  Positional-or-keyword (no ``/`` marker).
            alpha_2: ISO 3166-1 alpha-2 code (pycountry-compat alias for
                ``iso2``).
            alpha_3: ISO 3166-1 alpha-3 code (pycountry-compat alias for
                ``iso3``).
            numeric: ISO 3166-1 numeric code.
            iso2: ISO 3166-1 alpha-2 code (alias for ``alpha_2``).
            iso3: ISO 3166-1 alpha-3 code (alias for ``alpha_3``).
            dcid: Data Commons ID.
            domain: Optional domain filter.
            **code_kwargs: Any other code system by name (e.g.
                ``wikidata="Q30"``).

        Returns:
            EntityRecord if found, None otherwise.

        Raises:
            ValueError: If more than one code-system kwarg is provided.
            AmbiguousResolutionError: If the lookup matches multiple entities.
            RuntimeError: If the resolver has been closed.
        """
        if self._closed:
            raise RuntimeError("Resolver has been closed")
        from resolvekit.core.api.entity_lookup import _entity_dispatch

        return _entity_dispatch(
            resolver=self,
            text_or_id=text_or_id,
            alpha_2=alpha_2,
            alpha_3=alpha_3,
            numeric=numeric,
            iso2=iso2,
            iso3=iso3,
            dcid=dcid,
            domain=domain,
            code_kwargs=code_kwargs,
        )

    # Non-scalar KNOWN_PIVOTS that return a list rather than a scalar string;
    # related(to=) must reject these to keep the list[str | None] annotation honest.
    _NON_SCALAR_PIVOTS: frozenset[str] = frozenset({"aliases"})

    def _resolve_entity_arg(self, entity_or_id: "str | EntityRecord") -> EntityRecord:
        """Resolve *entity_or_id* to an EntityRecord deterministically (no fuzzy).

        Used by related() and diagnostics.unresolved_relations() so the
        no-fuzzy contract lives in one place.

        Resolution order:
        - EntityRecord → returned directly.
        - str containing '/' → get_entity() exact ID lookup (None → EntityNotFoundError).
        - bare str → lookup_name_exact() exact name/alias match:
            * 0 distinct entity_ids → EntityNotFoundError
            * >1 distinct entity_ids → AmbiguousResolutionError
            * exactly 1 → get_entity() on that id

        Raises:
            EntityNotFoundError: String matches no entity.
            AmbiguousResolutionError: String matches more than one entity.
        """
        if isinstance(entity_or_id, EntityRecord):
            return entity_or_id

        text = entity_or_id
        if "/" in text:
            entity = self._runner.get_entity(text)
            if entity is None:
                raise EntityNotFoundError(
                    f"no entity found for id {text!r}",
                    hint="check that the entity ID is correct and the pack is loaded",
                )
            return entity

        # Exact name/alias lookup — normalize to lowercase (same as inspect.py).
        normalized = text.lower()
        pairs = self._runner.lookup_name_exact(value=normalized)
        # Judge ambiguity on distinct entity_ids, not pair count — the same
        # entity appearing in multiple packs is not ambiguous.
        distinct_ids = list(dict.fromkeys(eid for _pack_id, eid in pairs))
        if len(distinct_ids) == 0:
            raise EntityNotFoundError(
                f"no entity found for name {text!r}",
                hint="use resolver.entity() for fuzzy / code-based lookup",
            )
        if len(distinct_ids) > 1:
            raise AmbiguousResolutionError(
                candidates=[
                    CandidateSummary(entity_id=eid, confidence=None)
                    for eid in distinct_ids
                ],
                hint=f"matched entities: {distinct_ids}",
            )
        entity = self._runner.get_entity(distinct_ids[0])
        if entity is None:
            raise EntityNotFoundError(f"no entity found for name {text!r}")
        return entity

    def related(
        self,
        entity_or_id: "str | EntityRecord",
        *,
        relation: str | None = None,
        as_of: date | str | None = None,
        to: str | None = None,
    ) -> "list[EntityRecord] | list[str | None]":
        """Return resolved related entities for *entity_or_id*, deduped, in edge order.

        Resolves the input deterministically (EntityRecord used directly; a
        string is matched by exact entity ID then exact name/alias — never
        fuzzy). For each relation edge (optionally filtered by *relation* and
        *as_of*), looks up the target via exact entity-ID lookup; unresolvable
        targets are omitted. With *to* set, each resolved entity is pivoted via
        ``EntityRecord.to(to)`` and the method returns those code/attribute
        values instead.

        Unlike ``entity()``, this method is deterministic-only and never falls
        back to fuzzy resolution. Unlike ``members_of()``, ``as_of=None``
        returns all edges regardless of date (not today's default).

        Args:
            entity_or_id: An EntityRecord, an entity ID string (e.g.
                ``"country/FRA"``), or an exact canonical name/alias string
                (e.g. ``"France"``).
            relation: When given, only follow edges of this type (e.g.
                ``"contained_in"``).  ``None`` follows all edge types.
            as_of: When given, only edges whose validity window includes this
                date are considered (half-open ``[valid_from, valid_until)``).
                ``None`` returns all edges regardless of date.  Accepts a
                ``datetime.date`` or an ISO-8601 string (``"2020-01-01"``).
            to: When given, pivot each resolved entity via
                ``EntityRecord.to(to)`` and return code/attribute strings
                instead of EntityRecord objects.  Must be a scalar code system
                or attribute (e.g. ``"iso3"``); raises ``UnknownCodeSystemError``
                for unknown or non-scalar pivots (e.g. ``"aliases"``).

        Returns:
            ``list[EntityRecord]`` when *to* is ``None``;
            ``list[str | None]`` when *to* is set.

        Raises:
            EntityNotFoundError: String *entity_or_id* matches no entity.
            AmbiguousResolutionError: String *entity_or_id* matches >1 entity.
            UnknownCodeSystemError: *to* is unknown or non-scalar.
            RuntimeError: Resolver is closed.
        """
        if self._closed:
            raise RuntimeError("Resolver has been closed")

        # Validate to= as a scalar pivot before doing any work.
        if to is not None:
            scalar_pivots = KNOWN_PIVOTS - self._NON_SCALAR_PIVOTS
            if to in self._NON_SCALAR_PIVOTS:
                available = sorted(self._runner.available_code_systems | scalar_pivots)
                raise UnknownCodeSystemError(
                    to,
                    available,
                    hint=f"{to!r} returns a list, not a scalar; available scalars: {available}",
                )
            # name / name:<lang|kind>[:<script>] tokens are always scalar (str | None).
            # parse_name_grammar validates the grammar and raises UnknownOutputError
            # on malformed tokens — let that propagate as-is.
            _is_name_token = to == "name" or to.startswith("name:")
            if _is_name_token:
                parse_name_grammar(to)  # raises UnknownOutputError on bad grammar
            elif (
                to not in scalar_pivots
                and to not in self._runner.available_code_systems
            ):
                available = sorted(self._runner.available_code_systems | scalar_pivots)
                raise UnknownCodeSystemError(to, available)

        entity = self._resolve_entity_arg(entity_or_id)

        as_of_date = _coerce_as_of(as_of)
        effective_as_of_str: str | None = (
            as_of_date.isoformat() if as_of_date is not None else None
        )
        seen: set[str] = set()
        out: list[EntityRecord] = []
        for rel in entity.relations:
            if relation is not None and rel.relation_type != relation:
                continue
            if effective_as_of_str is not None:
                # Half-open interval: [valid_from, valid_until)
                if rel.valid_from is not None and effective_as_of_str < rel.valid_from:
                    continue
                if (
                    rel.valid_until is not None
                    and effective_as_of_str >= rel.valid_until
                ):
                    continue
            # Exact ID lookup only — no fuzzy fallback.
            target = self._runner.get_entity(rel.target_id)
            if target is None or target.entity_id in seen:
                continue
            seen.add(target.entity_id)
            out.append(target)

        if to is None:
            return out

        # Pivot branch: cast to list[str | None] since EntityRecord.to() -> object
        # but we've validated to= is a scalar pivot above.
        return cast(
            "list[str | None]",
            [target.to(to) for target in out],
        )

    # Entity types that identify canonical geographic hierarchy nodes.
    # ``geo.subregion`` covers UN M.49 sub-regions; ``geo.continent`` covers continents.
    _GEO_HIERARCHY_TYPES: frozenset[str] = frozenset({"geo.continent", "geo.subregion"})

    def _resolve_container(self, container: "str | EntityRecord") -> "EntityRecord":
        """Resolve *container* to an EntityRecord for use by ``within()`` only.

        Identical to ``_resolve_entity_arg`` for EntityRecord inputs and
        ``"/"``-containing strings (direct entity-ID path).  For bare name
        strings that match more than one distinct entity, applies a
        geographic-hierarchy preference: if exactly one candidate has
        ``entity_type`` in ``_GEO_HIERARCHY_TYPES``, that candidate is chosen
        automatically.
        If zero or more than one canonical node remains after filtering,
        falls back to ``AmbiguousResolutionError`` (unchanged behaviour for
        genuinely-ambiguous non-geographic cases).

        Do NOT use this for ``related()`` or other callers — they keep the
        strict no-preference contract of ``_resolve_entity_arg``.

        Raises:
            EntityNotFoundError: String matches no entity.
            AmbiguousResolutionError: String matches multiple non-geographic
                entities, or multiple canonical geographic nodes.
        """
        if isinstance(container, EntityRecord):
            return container

        text = container
        if "/" in text:
            entity = self._runner.get_entity(text)
            if entity is None:
                raise EntityNotFoundError(
                    f"no entity found for id {text!r}",
                    hint="check that the entity ID is correct and the pack is loaded",
                )
            return entity

        normalized = text.lower()
        pairs = self._runner.lookup_name_exact(value=normalized)
        distinct_ids = list(dict.fromkeys(eid for _pack_id, eid in pairs))

        if len(distinct_ids) == 0:
            raise EntityNotFoundError(
                f"no entity found for name {text!r}",
                hint="use resolver.entity() for fuzzy / code-based lookup",
            )
        if len(distinct_ids) == 1:
            entity = self._runner.get_entity(distinct_ids[0])
            if entity is None:
                raise EntityNotFoundError(f"no entity found for name {text!r}")
            return entity

        # Multiple matches: prefer canonical geographic hierarchy nodes.
        # A node is canonical if its entity_type is in _GEO_HIERARCHY_TYPES
        # (geo.subregion for UN M.49 sub-regions, geo.continent for continents).
        def _is_geo_hierarchy(eid: str) -> bool:
            record = self._runner.get_entity(eid)
            return (
                record is not None and record.entity_type in self._GEO_HIERARCHY_TYPES
            )

        canonical_ids = [eid for eid in distinct_ids if _is_geo_hierarchy(eid)]
        if len(canonical_ids) == 1:
            entity = self._runner.get_entity(canonical_ids[0])
            if entity is None:
                raise EntityNotFoundError(f"no entity found for name {text!r}")
            return entity

        # Zero or multiple canonical nodes — raise as genuinely ambiguous.
        raise AmbiguousResolutionError(
            candidates=[
                CandidateSummary(entity_id=eid, confidence=None) for eid in distinct_ids
            ],
            hint=f"matched entities: {distinct_ids}",
        )

    def within(
        self,
        container: "str | EntityRecord",
        *,
        entity_type: str | list[str] | None = None,
        recursive: bool = True,
        max_depth: int | None = None,
        as_of: date | str | None = None,
        to: str | None = None,
    ) -> "list[EntityRecord] | list[str | None]":
        """Return entities geographically contained in *container*, recursively.

        Reverse-walks ``contained_in`` edges from the resolved container with a
        visited-set (the geographic graph is a DAG: Americas ⊃ South America).
        Results are deduped and sorted by ``entity_id`` (so minted regions sort in
        numeric ``m49/*`` order, NOT geographic order).

        Unlike ``members_of``, ``as_of=None`` returns ALL edges (it does not
        default to today). ``entity_type`` filters the OUTPUT only — intermediate
        regions are still traversed to reach their descendants. ``recursive=False``
        is equivalent to ``max_depth=1`` (direct children only). With ``to`` set,
        each result is pivoted via ``EntityRecord.to(to)`` to a scalar code — the
        same pivot ``related()`` uses (``members_of`` spells this ``as_codes``);
        entities lacking the code yield ``None`` holes, so pair it with
        ``entity_type`` to keep the rows aligned.

        When a name matches both a canonical geographic hierarchy node and another
        entity (e.g. a same-named statistical aggregate), within() prefers the
        geographic hierarchy node — one whose ``entity_type`` is ``"geo.subregion"``
        (UN M.49 sub-regions such as Western Europe or Sub-Saharan Africa) or
        ``"geo.continent"``.  Genuinely-ambiguous non-geographic cases still raise
        ``AmbiguousResolutionError``.

        **entity_type filter vs. statistical aggregates (breaking change in 0.1):**
        ``entity_type="geo.region"`` returns *statistical* aggregates (LDCs, SIDS,
        development groups), **NOT** geographic sub-regions.  To retrieve UN M.49
        geographic sub-regions use ``entity_type="geo.subregion"``.  Example:
        ``within("Africa", entity_type="geo.subregion")`` returns the six African
        M.49 sub-regions (Western/Eastern/Northern/Middle/Southern Africa,
        Sub-Saharan Africa); ``entity_type="geo.region"`` would return any same-named
        statistical aggregates instead.  To fetch a specific sub-region node (e.g.
        Western Europe / ``m49/155``) use ``entity("Western Europe")`` — ``within``
        returns descendants, not the container node itself.

        Args:
            container: Region name, alias, or entity ID (e.g. "Africa",
                "Eastern Africa", "wikidataId/Q15"). Resolved deterministically
                (exact ID then exact name/alias — never fuzzy).
            entity_type: Restrict OUTPUT to these types (e.g. ``"geo.country"``,
                ``"geo.subregion"`` for UN M.49 sub-regions, ``"geo.region"`` for
                statistical aggregates). Intermediate regions are traversed
                regardless. Accepts a single string or a list of strings.
            recursive: Walk transitively (default). False ⇒ direct children only.
            max_depth: Bound the descent in hops (1 = direct children). None =
                unbounded.
            as_of: Half-open [valid_from, valid_until) filter. None = all edges.
                Accepts a ``datetime.date`` or an ISO-8601 string
                (``"2020-01-01"``).
            to: Scalar pivot (e.g. "iso3"); returns code strings (None where
                absent) instead of EntityRecords.

        Returns:
            ``list[EntityRecord]`` when *to* is None; ``list[str | None]`` when
            *to* is set.

        Raises:
            EntityNotFoundError: *container* matches no entity.
            AmbiguousResolutionError: *container* matches multiple non-geographic
                entities, or multiple canonical geographic nodes.
            UnknownCodeSystemError: *to* is unknown or non-scalar.
            RuntimeError: Resolver is closed.

        Examples:
            >>> r.within("Africa", entity_type="geo.country", to="iso3")   # ~54 ISO3
            >>> r.within("Europe", entity_type="geo.country")              # EntityRecords
            >>> r.within("Eastern Africa", entity_type="geo.country", to="iso3")
        """
        if self._closed:
            raise RuntimeError("Resolver has been closed")

        # Validate to= as a scalar pivot before doing any work.
        if to is not None:
            validate_scalar_pivot(
                to, available_code_systems=self._runner.available_code_systems
            )

        as_of = _coerce_as_of(as_of)
        container_entity = self._resolve_container(container)

        # Normalize entity_type to frozenset for the collaborator.
        entity_type_set: frozenset[str] | None = None
        if entity_type is not None:
            if isinstance(entity_type, str):
                entity_type_set = frozenset({entity_type})
            else:
                entity_type_set = frozenset(entity_type)

        records = self._containment_api.within(
            container_id=container_entity.entity_id,
            entity_type=entity_type_set,
            recursive=recursive,
            max_depth=max_depth,
            as_of=as_of,
        )

        if to is None:
            return records

        return pivot_entities(records, to)

    def _resolve_inner_cached_then_hydrate(
        self,
        text: str,
        *,
        domain: str | list[str] | None,
        context: ResolutionContext | None,
        timeout: float | None,
    ) -> ResolutionResult:
        """Resolve via the cache path, then hydrate the entity if needed.

        Resolves without ``include_entity`` so the query cache stays effective
        (it stores raw ``ResolutionResult``), then fetches the entity separately
        only when the result resolved but is not yet hydrated. This avoids
        polluting the cache with hydrated variants, keeping cache entries stable
        and reusable across different pivoting needs.
        """
        result = self._resolve_inner(
            text,
            normalized_domain=_normalize_domain(domain),
            context=context,
            include_entity=False,
            timeout=timeout,
        )
        if (
            result.is_resolved
            and result.entity_id is not None
            and result.entity is None
        ):
            entity = self._runner.get_entity(result.entity_id)
            if entity is not None:
                result = result.model_copy(update={"entity": entity})
        return result

    def _resolve_inner(
        self,
        text: str,
        *,
        normalized_domain: frozenset[str] | None,
        context: ResolutionContext | None,
        include_entity: bool,
        timeout: float | None,
        _self_ref: "weakref.ref[Explainer] | None" = None,
    ) -> ResolutionResult:
        """Per-call resolve path — thin delegation to ResolveFlow.

        Callers that already validated domains at batch start (e.g.
        ``_resolve_many_internal``) take this entry point. The public
        ``resolve()`` validates once then delegates here.

        ``_self_ref`` is the per-batch weakref (Explainer back-reference).
        When None (single-call path), this method supplies ``weakref.ref(self)``.
        """
        if not isinstance(text, str):
            return self._invalid_query_result(ReasonCode.INVALID_INPUT_TYPE)
        if self._sentinel_blocklist is not None and self._sentinel_blocklist.is_blocked(
            text
        ):
            return ResolutionResult(
                status=ResolutionStatus.NO_MATCH,
                reasons=(ReasonCode.SENTINEL_BLOCKED,),
                query_text=text,
            )
        ref: weakref.ref[Explainer] = (
            _self_ref if _self_ref is not None else weakref.ref(self)
        )
        return self._resolve_flow.resolve_inner(
            text,
            normalized_domain=normalized_domain,
            context=context,
            include_entity=include_entity,
            timeout=timeout,
            _self_ref=ref,
        )

    @overload
    def resolve(
        self,
        text: str,
        *,
        to: _Unset = ...,
        as_result: Literal[True],
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
        from_system: str | None = None,
        include_entity: bool = False,
        timeout: float | None = None,
    ) -> ResolutionResult: ...
    @overload
    def resolve(
        self,
        text: str,
        *,
        to: _Unset = ...,
        as_result: bool = False,
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
        from_system: str | None = None,
        include_entity: bool = False,
        timeout: float | None = None,
    ) -> "ResolutionResult | str | None": ...
    @overload
    def resolve(
        self,
        text: str,
        *,
        to: None,
        as_result: bool = False,
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
        from_system: str | None = None,
        include_entity: bool = False,
        timeout: float | None = None,
    ) -> ResolutionResult: ...
    @overload
    def resolve(
        self,
        text: str,
        *,
        to: type[EntityRecord],
        as_result: bool = False,
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
        from_system: str | None = None,
        include_entity: bool = False,
        timeout: float | None = None,
    ) -> EntityRecord | None: ...
    @overload
    def resolve(
        self,
        text: str,
        *,
        to: Literal["iso3", "iso2", "numeric", "name", "flag", "continent", "aliases"]
        | str,
        as_result: bool = False,
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
        from_system: str | None = None,
        include_entity: bool = False,
        timeout: float | None = None,
    ) -> str | None: ...
    def resolve(
        self,
        text: object,
        *,
        to: "Literal['iso3','iso2','numeric','name','flag','continent','aliases'] | str | type[EntityRecord] | None | _Unset" = UNSET,
        as_result: bool = False,
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
        from_system: str | None = None,
        include_entity: bool = False,
        timeout: float | None = None,
    ) -> "ResolutionResult | str | EntityRecord | None":
        """Resolve a single text string, optionally pivoting to a code or attribute.

        Args:
            text: The text or code to resolve.  ``str`` is used as-is.
                ``int`` and ``float`` are coerced to string (``840`` →
                ``"840"``; ``840.0`` → ``"840"``), matching the behaviour of
                :meth:`bulk` on numeric columns.  ``None`` returns a
                NO_MATCH result silently.  ``bool`` and all other types raise
                ``TypeError``.
            to: Target representation.  ``UNSET`` (default) uses the resolver's
                configured ``default_to`` spec when set, or returns a raw
                :class:`ResolutionResult` when no spec is configured.
                ``None`` (explicit) always returns a :class:`ResolutionResult`.
                A code-system name (``"iso3"``, ``"dcid"``) returns the matching
                code string.  An attribute name (``"continent"``, ``"name"``,
                ``"flag"``) returns that attribute.  ``EntityRecord`` returns the
                full entity record.
                IDE-known canonical values: ``"iso3"``, ``"iso2"``, ``"numeric"``,
                ``"name"``, ``"flag"``, ``"continent"``, ``"aliases"``.
            as_result: Return the full ``ResolutionResult`` even when a default
                output is configured — the readable equivalent of ``to=None``.
                Raises ``ValueError`` when combined with an explicit non-None
                ``to=`` (contradictory).
            domain: Optional domain pack(s) — ``"geo"`` or ``["geo", "org"]``.
            context: Optional resolution context (as_of date, entity_types, etc.).
            from_system: Force-disambiguate a code (default: auto-detect across
                loaded code systems in priority order ``iso3 > iso2 > numeric >
                dcid > wikidata > <standards> > <custom alphabetical>``).
            include_entity: When True, populate ``result.entity`` with the full
                :class:`EntityRecord`.  Defaults to ``False`` for
                ``Resolver.resolve()`` to avoid per-call overhead.  When ``to``
                is set (or a default spec is active), ``include_entity`` is forced
                to ``True`` internally.
            timeout: Maximum seconds to wait.  Falls back to
                ``Resolver._default_timeout`` when ``None``.

        Returns:
            - ``to=UNSET`` + no spec → :class:`ResolutionResult` (legacy).
            - ``to=UNSET`` + spec set → pivoted ``str | None`` (or raise on miss).
            - ``to=None`` or ``as_result=True`` → :class:`ResolutionResult`.
            - ``to="iso3"`` (or any scalar code/attribute) → ``str | None``.
            - ``to=EntityRecord`` → :class:`EntityRecord` or ``None``.

        Raises:
            ValueError: If ``as_result=True`` combined with an explicit ``to=``
                (other than ``UNSET``/``None``), or if ``timeout <= 0``.
            TypeError: If *text* is a ``bool``, ``bytes``, ``list``, ``tuple``,
                or any other unsupported type.  ``int`` and ``float`` are
                accepted (coerced); ``None`` is accepted (soft NO_MATCH).
            AmbiguousResolutionError: When pivoting and the result is ambiguous.
            OutputMissingError: When a spec is active and the entity lacks the
                requested output and ``on_missing="raise"`` (or ``"auto"`` scalar).
            RuntimeError: If the resolver has been closed.
        """
        if self._closed:
            raise RuntimeError("Resolver has been closed")

        # as_result + explicit non-None to= is contradictory.
        if as_result and to is not UNSET and to is not None:
            raise ValueError("pass either to= or as_result=True, not both")

        if not isinstance(text, str):
            # Non-empty list/tuple: likely a bulk-call mistake — raise with hint
            # so the caller can switch to rk.bulk().
            if isinstance(text, (list, tuple)) and len(text) > 0:  # type: ignore[arg-type]
                err = TypeError(
                    "resolve() takes a single string; "
                    "for bulk lookup use rk.bulk(values=[...])"
                )
                setattr(err, "hint", "rk.bulk(values=[...])")  # noqa: B010
                raise err
            # None → silent NO_MATCH (unchanged).
            if text is None:
                return self._invalid_query_result(ReasonCode.INVALID_INPUT_TYPE)
            # bool is an int subclass — reject before the int check to avoid
            # True→"1" / False→"0" mapping to real entities.
            if isinstance(text, bool):
                raise TypeError(
                    f"resolve() text must be a str, int, or float; got {type(text).__name__!r}"
                )
            # int / float → coerce to canonical string via the shared helper so
            # scalar and bulk can never diverge.
            if isinstance(text, (int, float)):
                from resolvekit.core.api.bulk import _numeric_to_str

                text = _numeric_to_str(text)  # type: ignore[assignment]
            else:
                # bytes, empty list/tuple, arbitrary objects → TypeError.
                raise TypeError(
                    f"resolve() text must be a str, int, or float; got {type(text).__name__!r}"
                )
        effective_timeout = timeout if timeout is not None else self._default_timeout
        if effective_timeout is not None and effective_timeout <= 0:
            raise ValueError("timeout must be positive")

        # Determine which output path is active.
        # want_raw: caller explicitly asked for a ResolutionResult.
        want_raw = (to is None) or as_result
        # spec applies only when to= was omitted (UNSET) — not for explicit to=.
        spec = None if (to is not UNSET) else self._output_spec
        # pivoting: we need entities hydrated.
        pivoting = (to is not UNSET and to is not None) or (
            spec is not None and not want_raw
        )
        effective_include_entity = include_entity or pivoting

        # Code-input short-circuit: fire when from_system is set or an explicit
        # to= is given (str/EntityRecord/None).  The spec path (to=UNSET, spec
        # active) uses _resolve_inner WITHOUT include_entity so the query cache
        # remains effective (cache stores raw ResolutionResult; entity is fetched
        # post-cache only when needed for pivoting).
        use_cache_path = not (
            from_system is not None or (to is not UNSET and to is not None)
        )
        if not use_cache_path:
            result = self._code_lookup.resolve_or_lookup(
                text,
                explainer_ref=weakref.ref(self),
                from_system=from_system,
                domain=domain,
                context=context,
                include_entity=effective_include_entity,
                timeout=effective_timeout,
                resolve_inner_fn=self._resolve_inner,
            )
        elif spec is not None and not want_raw:
            # Spec active: resolve via the cache path, hydrating the entity
            # afterwards via _resolve_inner_cached_then_hydrate.
            result = self._resolve_inner_cached_then_hydrate(
                text,
                domain=domain,
                context=context,
                timeout=effective_timeout,
            )
        else:
            result = self._resolve_inner(
                text,
                normalized_domain=_normalize_domain(domain),
                context=context,
                include_entity=effective_include_entity,
                timeout=effective_timeout,
            )

        if domain is not None or context is not None:
            result._resolve_domain = domain  # type: ignore[attr-defined]
            result._resolve_context = context  # type: ignore[attr-defined]

        # Legacy path: omitted to= with no spec (or explicit raw request).
        if want_raw or (to is UNSET and spec is None):
            return result

        # Explicit to= path (str, EntityRecord, or non-UNSET non-None) and spec
        # path (to is UNSET, spec set, not want_raw) both delegate to the shared
        # terminal guard.  dispatch_pivot's return type is widened to `object` to
        # cover all pivot kinds; cast back to the union the public method advertises.
        if to is not UNSET:
            out = apply_resolved_output(result, to=to)
        else:
            assert spec is not None  # guaranteed: we're in the spec-active branch
            out = apply_resolved_output(result, spec=spec)
        return cast("ResolutionResult | str | EntityRecord | None", out)

    def resolve_id(
        self,
        text: str,
        *,
        on_ambiguous: "Literal['raise', 'null', 'best']" = "raise",
        from_system: str | None = None,
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
        timeout: float | None = None,
    ) -> str | None:
        """Resolve text and return entity_id or None.

        Returns the entity ID for RESOLVED results, None for NO_MATCH,
        and handles AMBIGUOUS per ``on_ambiguous``.

        Args:
            text: Text to resolve.  ``str`` is used as-is.  ``int`` and
                ``float`` are coerced to string (``840`` → ``"840"``;
                ``840.0`` → ``"840"``), matching the behaviour of
                :meth:`bulk` on numeric columns.  ``None`` returns ``None``
                silently.  ``bool`` and all other types raise ``TypeError``.
            on_ambiguous: Behavior when multiple entities match.
                - ``"raise"`` (default): preserves the existing contract;
                  raises :class:`AmbiguousResolutionError` with candidates.
                - ``"null"``: returns ``None`` on ambiguity.
                - ``"best"``: returns the top candidate's entity_id silently.
            from_system: Force-disambiguate input as a specific code system
                (e.g. ``"iso2"``).  When set, skips name resolution and goes
                directly to the code-lookup path.
            domain: Optional domain(s) to route to.
            context: Optional resolution context.
            timeout: Maximum seconds to wait.  Falls back to
                ``Resolver._default_timeout``.

        Returns:
            Entity ID string, or None if no match.

        Raises:
            TypeError: If *text* is a ``bool``, ``bytes``, ``list``, or any
                other unsupported type.
            AmbiguousResolutionError: If ``on_ambiguous="raise"`` and the
                resolution is ambiguous.
            ResolutionError: If the resolution pipeline errored.
            ValueError: If ``on_ambiguous`` is not one of
                ``"raise"``, ``"null"``, or ``"best"``.
        """
        if on_ambiguous not in _ON_AMBIGUOUS_VALUES:
            raise ValueError(_on_ambiguous_error(on_ambiguous))
        # Pass to=None explicitly so a bound default_to spec does NOT pivot here.
        # resolve_id always returns entity_id regardless of any configured default output.
        result = self.resolve(
            text,
            to=None,
            from_system=from_system,
            domain=domain,
            context=context,
            timeout=timeout,
        )
        if result.is_resolved:
            return result.entity_id
        if result.is_ambiguous:
            if on_ambiguous == "raise":
                raise AmbiguousResolutionError(candidates=list(result.candidates))
            if on_ambiguous == "best":
                top = result.best_candidate
                return top.entity_id if top else None
            return None  # on_ambiguous="null"
        if result.status == ResolutionStatus.ERROR:
            raise _resolution_error(text, result)
        return None  # NO_MATCH

    def require_id(
        self,
        text: str,
        *,
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
    ) -> str:
        """Resolve text and return entity_id, or raise on failure.

        Args:
            text: Text to resolve
            domain: Optional domain(s) to route to
            context: Optional resolution context

        Returns:
            Entity ID string

        Raises:
            AmbiguousResolutionError: If resolution is ambiguous
            ResolutionError: For any other non-resolved status
        """
        # Pass to=None so a bound default_to spec does not pivot here.
        result = self.resolve(text, to=None, domain=domain, context=context)
        if result.is_resolved and result.entity_id is not None:
            return result.entity_id
        if result.is_ambiguous:
            raise AmbiguousResolutionError(candidates=list(result.candidates))
        raise _resolution_error(text, result)

    def suggest(
        self,
        prefix: str,
        *,
        top_k: int = 10,
        domain: str | list[str] | None = None,
        entity_type: str | list[str] | None = None,
        context: ResolutionContext | None = None,
        to: str | list[str] | None = None,
        fuzzy: "Literal['auto', 'always', 'never']" = "auto",
        timeout: float | None = None,
    ) -> "list":
        """Return a ranked typeahead suggestion list for *prefix*.

        Unlike :meth:`resolve`, ``suggest()`` always returns a ranked list and
        never raises a thresholded verdict.  Empty or whitespace-only prefixes
        return ``[]`` without touching the store.

        The result type is ``list[SuggestionResult]`` (importable from
        :mod:`resolvekit.core.model`).  ``SuggestionResult`` is a frozen
        Pydantic model with:

        - ``entity_id``, ``canonical_name``, ``entity_type``, ``pack_id``
        - ``match_class`` (:class:`~resolvekit.core.model.MatchClass`): how the
          candidate was found (``"exact_prefix"``, ``"token_prefix"``,
          ``"infix"``, ``"fuzzy"``).
        - ``fuzzy_score``: raw ``partial_ratio`` score (0-100) from RapidFuzz;
          ``None`` unless ``match_class == "fuzzy"``.
        - ``ranking_quality``: ``"ranked"`` when the tier has live prominence
          data (currently ``geo.country``); ``"unranked"`` otherwise.
        - ``display``: ``to=``-rendered output string; ``None`` on miss.
        - ``highlight_ranges``: Unicode **code-point** offsets (NOT UTF-16),
          end-exclusive, into ``display``; JS/browser callers must convert.

        Args:
            prefix: Partial query string (e.g. ``"unit"`` → United States, …).
            top_k: Maximum suggestions to return; clamped to [1, 100].
                Default 10.
            domain: Domain pack filter (e.g. ``"geo"``).  Same validation as
                :meth:`resolve`.
            entity_type: Sub-type filter within a domain (e.g.
                ``"geo.country"``).  Accepts a single string or list.
            context: Reserved for future caller hints; currently ignored.
            to: Output code system or name variant for ``display`` (e.g.
                ``"iso3"``, ``"name"``).  Overrides ``default_to`` for this
                call.  ``None`` (default) uses ``canonical_name`` as the
                display value.
            fuzzy: Fuzzy-matching policy.
                ``"auto"`` (default) — fuzzy on small non-denylisted tiers
                (bundled geo tiers ≤20 k names, excl. cities/admin2+).
                ``"always"`` — force fuzzy regardless (caller accepts noise).
                ``"never"`` — exact prefix / infix only.
            timeout: Per-call time budget in seconds.  Exceeding it returns
                partial results rather than raising.

        Returns:
            ``list[SuggestionResult]``, sorted by match quality (best first),
            length at most ``top_k``.

        Raises:
            RuntimeError: If the resolver has been closed.
            ValueError: If *domain* contains dotted names (use *entity_type*
                instead) or *to* references an unknown code system.
        """
        if self._closed:
            raise RuntimeError("Resolver has been closed")
        return self._suggest_flow.suggest(
            prefix,
            top_k=top_k,
            domain=domain,
            entity_type=entity_type,
            context=context,
            to=to,
            fuzzy=fuzzy,
            timeout=timeout,
        )

    def _resolve_many_internal(
        self,
        texts: list[str],
        *,
        domain: str | list[str] | None = None,
        context: ResolutionContext | Sequence[ResolutionContext | None] | None = None,
        include_entity: bool = False,
        timeout: float | None = None,
    ) -> ResolutionResultList:
        """Resolve multiple texts — internal bulk path used by ``bulk()``.

        Runs a serial loop with per-batch deduplication.  Identical
        ``(text, context)`` pairs are resolved once and reused.
        """
        if self._closed:
            raise RuntimeError("Resolver has been closed")
        return self._batch_resolver.resolve_many_internal(
            texts,
            domain=domain,
            context=context,
            include_entity=include_entity,
            timeout=timeout,
            resolve_inner_fn=self._resolve_inner,
            explainer_ref_factory=lambda: weakref.ref(self),
        )

    def bulk(
        self,
        *,
        values: Any,
        to: Any = UNSET,
        on_missing: Any = UNSET,
        output: "Literal['series', 'record', 'frame']" = "series",
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
        from_system: str | None = None,
        not_found: str = "null",
        on_error: "Literal['raise', 'null', 'keep']" = "raise",
        on_ambiguous: "Literal['null', 'raise', 'best']" = "null",
        crosswalk: "Crosswalk | None" = None,
    ) -> Any:
        """Resolve a collection of values in bulk using this resolver.

        Delegates to the shared
        :func:`~resolvekit.core.api.bulk._bulk_dispatch` with ``self`` pinned
        as the resolver — the same dispatch the convenience-layer
        :func:`resolvekit.bulk` uses.

        Args:
            values: Input collection — ``pd.Series``, ``pl.Series``,
                ``numpy.ndarray``, ``list``, ``tuple``, or ``dict``
                (resolves the values and returns a same-keyed dict).
            to: Explicit pivot target.  ``UNSET`` (default) activates the
                resolver's configured ``default_to`` spec when set.  ``None``
                forces raw :class:`BulkResult` output.  A scalar code/attribute
                returns native shape directly.
            on_missing: Miss policy override for the default output spec.
                ``UNSET`` (default) = defaults to the resolver's configured
                ``on_missing`` policy.  ``"raise"`` raises
                :class:`~resolvekit.errors.OutputMissingError` on the first
                resolved-but-missing entity, aborting the batch.  ``"null"``
                forces null silently.
                ``"auto"`` = null for bulk rows.  Only applies on the spec path.
            output: ``"series"`` (default), ``"record"``, or ``"frame"``.
                Ignored when ``to`` is a scalar.
            domain: Optional domain filter.
            context: Optional resolution context broadcast to every row.
            from_system: Force code-system for lookup.
            not_found: ``"null"`` (default), ``"raise"``, or a sentinel string.
            on_error: ``"raise"`` (default), ``"null"``, or ``"keep"``.
            on_ambiguous: ``"null"`` (default), ``"raise"``, or ``"best"``.
            crosswalk: Optional :class:`~resolvekit.Crosswalk` that short-circuits
                resolution for matched values.  Values in the crosswalk bypass
                code-detection, ``on_ambiguous``, ``not_found``, and
                ``from_system`` entirely.  ``rk.IGNORE`` entries yield ``None``
                unconditionally.

        Returns:
            Native shape when ``to`` is scalar or a default spec is active with
            ``output="series"``; :class:`BulkResult` otherwise.
        """
        if self._closed:
            raise RuntimeError("Resolver has been closed")
        return self._bulk_with_spec(
            values=values,
            spec=self._output_spec if to is UNSET else None,
            on_missing=on_missing,
            to=to,
            output=output,
            domain=domain,
            context=context,
            from_system=from_system,
            not_found=not_found,
            on_error=on_error,
            on_ambiguous=on_ambiguous,
            crosswalk=crosswalk,
        )

    def parse(
        self,
        text: str,
        *,
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
        to: str | list[str] | None = None,
        confidence_threshold: float | None = None,
        include_nil: bool = False,
        timeout: float | None = None,
    ) -> "ParseResult":
        """Extract and link every pack-known entity mention in ``text``.

        Returns a :class:`~resolvekit.core.parse.result.ParseResult` of
        :class:`~resolvekit.core.parse.result.ParsedEntity` (raw-input offsets,
        confidence, type, full ``.resolution.explain()``), ordered by ascending
        start offset.

        Two abstention channels: NIL spans (detected but below threshold,
        status=NO_MATCH) appear only with ``include_nil=True``; gate-rejected
        spans (sentinel/short-input/word-boundary) always live on
        ``ParseResult.dropped_spans`` as a debug channel and are never emitted
        as entities.  By default the result holds only resolved entities, so
        ``e.confidence`` is a float on the common path.

        Cost is ``O(spans x packs x passes x pipeline)``; each span is a full
        pipeline run.  Repeated surfaces of the same entity-type within one
        call hit the query cache; distinct surfaces miss.  When ``to=`` is set,
        one ``get_entity`` hydration per RESOLVED span is added (SQLite point
        read; not currently batched).  Use one Resolver per thread (the query
        cache is not thread-safe).

        Args:
            text: Free-text input string.
            domain: Pack(s) to detect over.  ``None`` routes to all available.
            context: Resolution hints (country, as_of, etc.) broadcast to every
                span.
            to: Output pivot applied to each RESOLVED entity (e.g. ``"iso3"``).
                NIL spans get ``output=None``.  Does not collapse the result
                to a list; use ``.to_dataframe()["to"]`` for the column form.
            confidence_threshold: Minimum calibrated confidence to include a
                span.  ``None`` uses each pack's built-in threshold.
            include_nil: When ``True``, below-threshold detected spans are
                surfaced with ``status=NO_MATCH``; when ``False`` they are
                dropped (not included in ``entities`` or ``dropped_spans``).
            timeout: Soft per-call budget in seconds.  Accepted in the
                signature for forward compatibility; the engine does not
                currently thread it per-span (no new timeout machinery).

        Returns:
            :class:`~resolvekit.core.parse.result.ParseResult` with
            ``entities`` sorted by start offset and a ``dropped_spans``
            debug channel.

        Raises:
            RuntimeError: If the resolver has been closed.
            ImportError: If ``ahocorasick_rs`` is not installed; install with
                ``pip install 'resolvekit[parsing]'``.
            ValueError: If ``confidence_threshold`` is not a number in
                ``[0.0, 1.0]``.
            UnknownDomainError: If ``domain`` names an unavailable pack.
        """
        if self._closed:
            raise RuntimeError("Resolver has been closed")
        _validate_confidence_threshold(confidence_threshold)
        self._validate_parse_domain(domain)

        from resolvekit.core.parse._pivot import apply_to_pivot
        from resolvekit.core.parse.engine import parse_one
        from resolvekit.core.parse.result import ParseResult

        entities, dropped = parse_one(
            text,
            backend=self,
            domain=domain,
            context=context,
            confidence_threshold=confidence_threshold,
            include_nil=include_nil,
        )
        entities = apply_to_pivot(
            entities, to, runner=self._runner, code_systems=self.code_systems()
        )
        return ParseResult(entities=entities, dropped_spans=dropped)

    def parse_bulk(
        self,
        *,
        values: Any,
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
        to: str | list[str] | None = None,
        confidence_threshold: float | None = None,
        include_nil: bool = False,
        timeout: float | None = None,
    ) -> "ParseResult":
        """Parse a column of free-text values into a ragged ParseResult.

        Each row produces zero or more
        :class:`~resolvekit.core.parse.result.ParsedEntity` objects; the
        result is an exploded flat list.  ``ParsedEntity.row_idx`` tags the
        source row (0-based) so consumers can re-join to the original column.
        ``.to_dataframe()`` yields the exploded table with columns
        ``[row_idx, surface, entity_id, entity_type, pack_id, status,
        confidence, start, end, to]``.  No cross-row deduplication.
        Single-threaded (the query cache is not thread-safe).

        Two abstention channels: ``include_nil=True`` surfaces
        detected-but-below-threshold spans as NIL entities; gate-rejected
        spans always land on ``ParseResult.dropped_spans``.

        Cost is ``O(rows x spans x packs x passes x pipeline)``.  When
        ``to=`` is set, one ``get_entity`` hydration per RESOLVED span is
        added (SQLite point read).  ``None``/NaN rows contribute zero
        entities (no crash).

        Args:
            values: Text column — ``list``, ``tuple``, ``pd.Series``,
                ``pl.Series``, or ``numpy.ndarray``.  Each element is the
                raw text for one row.
            domain: Pack(s) to detect over.  ``None`` routes to all available.
            context: Resolution hints broadcast to every span in every row.
            to: Output pivot applied to each RESOLVED entity.  ``None`` means
                no pivot; NIL spans always get ``output=None``.
            confidence_threshold: Minimum calibrated confidence.  ``None`` uses
                each pack's built-in threshold.
            include_nil: Surface detected-but-below-threshold spans when ``True``.
            timeout: Soft per-call budget; accepted for forward compatibility.

        Returns:
            :class:`~resolvekit.core.parse.result.ParseResult` with all rows
            concatenated.  Each entity carries its ``row_idx``.

        Raises:
            RuntimeError: If the resolver has been closed.
            TypeError: If ``values`` is an unsupported type.
            ImportError: If ``ahocorasick_rs`` is not installed; install with
                ``pip install 'resolvekit[parsing]'``.
            ValueError: If ``confidence_threshold`` is not a number in
                ``[0.0, 1.0]``.
            UnknownDomainError: If ``domain`` names an unavailable pack.
        """
        if self._closed:
            raise RuntimeError("Resolver has been closed")
        _validate_confidence_threshold(confidence_threshold)
        self._validate_parse_domain(domain)

        from resolvekit.core.api.bulk import _detect_input_kind
        from resolvekit.core.parse._pivot import apply_to_pivot, coerce_to_str_list
        from resolvekit.core.parse.engine import parse_bulk_rows
        from resolvekit.core.parse.result import ParseResult

        _kind, raw_values = _detect_input_kind(values)
        rows = coerce_to_str_list(raw_values)

        entities, dropped = parse_bulk_rows(
            rows,
            backend=self,
            domain=domain,
            context=context,
            confidence_threshold=confidence_threshold,
            include_nil=include_nil,
        )
        entities = apply_to_pivot(
            entities, to, runner=self._runner, code_systems=self.code_systems()
        )
        return ParseResult(entities=entities, dropped_spans=dropped)

    def snap(
        self,
        *,
        query: str,
        candidates: list[str],
        max_distance: float = 0.5,
        to: Any = UNSET,
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
    ) -> Any:
        """Return the closest match among *candidates*.

        Delegates to the shared
        :func:`~resolvekit.core.api.snap._snap_dispatch` with ``self`` pinned
        as the resolver — the same dispatch the convenience-layer
        :func:`resolvekit.snap` uses.

        Args:
            query: The query string to match.
            candidates: Entity IDs or free-text labels to match against.
            max_distance: Confidence floor; below this threshold returns ``None``.
            to: Explicit pivot target.  ``UNSET`` (default) activates the
                resolver's configured ``default_to`` spec when set.  ``None``
                (explicit) forces entity_id (pre-spec behavior).
            domain: Optional domain filter.
            context: Optional resolution context.

        Returns:
            The closest matching candidate, pivoted per the active output path,
            or ``None`` when below threshold.
        """
        if self._closed:
            raise RuntimeError("Resolver has been closed")
        return self._snap_with_spec(
            query=query,
            candidates=candidates,
            spec=self._output_spec if to is UNSET else None,
            max_distance=max_distance,
            to=to,
            domain=domain,
            context=context,
        )

    # ------------------------------------------------------------------
    # Private spec-apply helpers — single implementation of the apply-branch
    # shared by bound-spec paths (resolve/bulk/snap with self._output_spec)
    # and the OutputView forwarders.
    # ------------------------------------------------------------------

    def _resolve_with_spec(
        self,
        text: str,
        *,
        spec: OutputSpec,
        as_result: bool = False,
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
        from_system: str | None = None,
        timeout: float | None = None,
    ) -> "ResolutionResult | str | None":
        """Resolve *text* applying *spec* as the output chain.

        Used by :class:`~resolvekit.core.api.output_view.OutputView` so that
        both the bound-resolver path and the view share one implementation.
        The caller supplies the spec directly; this method does not consult
        ``self._output_spec``.
        """
        if self._closed:
            raise RuntimeError("Resolver has been closed")
        if as_result:
            # Raw result requested — skip spec entirely.
            return self.resolve(
                text,
                to=None,
                domain=domain,
                context=context,
                from_system=from_system,
                timeout=timeout,
            )

        if not isinstance(text, str):
            return None

        effective_timeout = timeout if timeout is not None else self._default_timeout
        if effective_timeout is not None and effective_timeout <= 0:
            raise ValueError("timeout must be positive")

        # Cache-preserving two-step: when from_system is set, take the code-lookup
        # path (include_entity=True); otherwise resolve without include_entity so
        # the query cache can engage, then fetch the entity separately if needed
        # for pivoting.
        if from_system is not None:
            result = self._code_lookup.resolve_or_lookup(
                text,
                explainer_ref=weakref.ref(self),
                from_system=from_system,
                domain=domain,
                context=context,
                include_entity=True,
                timeout=effective_timeout,
                resolve_inner_fn=self._resolve_inner,
            )
        else:
            result = self._resolve_inner_cached_then_hydrate(
                text,
                domain=domain,
                context=context,
                timeout=effective_timeout,
            )

        if domain is not None or context is not None:
            result._resolve_domain = domain  # type: ignore[attr-defined]
            result._resolve_context = context  # type: ignore[attr-defined]

        return cast(
            "ResolutionResult | str | None",
            apply_resolved_output(result, spec=spec),
        )

    def _bulk_with_spec(
        self,
        *,
        values: Any,
        spec: "OutputSpec | None",
        on_missing: Any = UNSET,
        to: Any = UNSET,
        output: str = "series",
        domain: str | list[str] | None = None,
        context: "ResolutionContext | None" = None,
        from_system: str | None = None,
        not_found: str = "null",
        on_error: str = "raise",
        on_ambiguous: str = "null",
        crosswalk: "Crosswalk | None" = None,
    ) -> Any:
        """Internal bulk dispatch wiring spec + on_missing inherit/override.

        ``on_missing=UNSET`` inherits the spec's policy; an explicit string
        overrides it.  ``_bulk_dispatch`` owns the per-call override logic; we
        resolve inherit-vs-override here and always pass a concrete string.
        """
        from resolvekit.core.api.bulk import _bulk_dispatch

        effective_on_missing: str
        if spec is not None and on_missing is UNSET:
            # Inherit the spec's own policy.
            effective_on_missing = spec.on_missing
        elif on_missing is UNSET:
            effective_on_missing = "auto"
        else:
            effective_on_missing = on_missing

        return _bulk_dispatch(
            resolver=self,
            values=values,
            to=to,
            output_spec=spec,
            on_missing=effective_on_missing,
            output=output,
            domain=domain,
            context=context,
            from_system=from_system,
            not_found=not_found,
            on_error=on_error,
            on_ambiguous=on_ambiguous,
            crosswalk=crosswalk,
        )

    def _snap_with_spec(
        self,
        *,
        query: str,
        candidates: list[str],
        spec: "OutputSpec | None",
        max_distance: float = 0.5,
        to: Any = UNSET,
        domain: str | list[str] | None = None,
        context: "ResolutionContext | None" = None,
    ) -> Any:
        """Internal snap dispatch threading output_spec."""
        from resolvekit.core.api.snap import _snap_dispatch

        return _snap_dispatch(
            resolver=self,
            query=query,
            candidates=candidates,
            max_distance=max_distance,
            to=to,
            domain=domain,
            context=context,
            output_spec=spec,
        )

    def to(
        self,
        output: "str | list[str]",
        *,
        on_missing: "Literal['raise','null','auto']" = "auto",
    ) -> "OutputView":
        """Return an :class:`~resolvekit.core.api.output_view.OutputView` bound to *output*.

        The view forwards ``resolve``/``bulk``/``snap`` applying the compiled
        output spec; ``resolve_id`` always returns entity_id (unaffected).

        Args:
            output: Code system or name variant, or a fallback chain list
                (e.g. ``"iso3"`` or ``["iso3", "name"]``).
            on_missing: Miss policy — ``"auto"`` (default), ``"raise"``, or
                ``"null"``.  See ``Resolver.__init__`` for semantics.

        Returns:
            An :class:`~resolvekit.core.api.output_view.OutputView` instance.
        """
        # Deferred import to avoid the import cycle: output_view imports Resolver
        # (TYPE_CHECKING only), and this method is the only call site.
        from resolvekit.core.api.output_view import OutputView

        return OutputView(
            _resolver=self,
            _spec=compile_output_spec(
                output, on_missing, known_systems=self.code_systems()
            ),
        )

    def resolve_explained(
        self,
        text: str,
        *,
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
        verbosity: "Verbosity | str" = Verbosity.STANDARD,
        timeout: float | None = None,
    ) -> ExplainedResolution:
        """Resolve with full tracing; backs ``result.explain()`` and the ``Explainer`` protocol.

        This is the concrete implementation that satisfies ``Explainer.resolve_explained``.
        Callers should normally use ``result.explain()`` instead of calling this directly;
        the method is kept non-private because ``ResolutionResult._explainer`` weakrefs
        need it reachable without going through the model layer.
        """
        if self._closed:
            raise RuntimeError("Resolver has been closed")
        return self._resolve_flow.resolve_explained(
            text,
            domain=domain,
            context=context,
            verbosity=verbosity,
            timeout=timeout,
            default_timeout=self._default_timeout,
            _self_ref=weakref.ref(self),
        )

    def resolve_detailed(
        self,
        text: str,
        *,
        domain: str | list[str] | None = None,
        context: ResolutionContext | None = None,
        timeout: float | None = None,
    ) -> PipelineResult:
        """Advanced: resolve and return the full ``PipelineResult`` with candidates.

        Mirrors :meth:`resolve` but always returns a :class:`PipelineResult`
        (never a ``ResolutionResult``).  Use this when you need the raw
        candidate list or pack-level metadata from the pipeline.

        Args:
            text: The text or code to resolve.
            domain: Optional domain pack(s).
            context: Optional resolution context.
            timeout: Maximum seconds to wait.

        Returns:
            :class:`PipelineResult` with ``.result``, ``.candidates``, and
            ``.pack_id``.

        Raises:
            RuntimeError: If the resolver has been closed.
            ValueError: If ``timeout <= 0``.
        """
        if self._closed:
            raise RuntimeError("Resolver has been closed")
        if not isinstance(text, str):
            return PipelineResult(
                result=self._invalid_query_result(ReasonCode.INVALID_INPUT_TYPE)
            )
        effective_timeout = timeout if timeout is not None else self._default_timeout
        if effective_timeout is not None and effective_timeout <= 0:
            raise ValueError("timeout must be positive")
        if not text or not text.strip():
            return PipelineResult(result=self._invalid_query_result())

        from resolvekit.core.api.resolve_flow import prepare_detailed_call

        prep = prepare_detailed_call(
            text=text,
            context=context,
            domain=domain,
            effective_timeout=effective_timeout,
            query_preparer=self._query_preparer,
        )
        if prep is None:
            return PipelineResult(result=self._invalid_query_result())
        query, ctx, deadline = prep

        pipeline_result = self._runner.resolve_detailed(query, ctx, deadline=deadline)
        # Apply the same finalization resolve() does so .result agrees with
        # resolve(): realign query_text, run the group-preference tiebreak
        # (which can promote a unique group candidate AMBIGUOUS -> RESOLVED),
        # and attach the explainer back-reference.
        explainer_ref: weakref.ref[Explainer] = weakref.ref(self)
        finalized = pipeline_result.result.model_copy(update={"query_text": text})
        finalized = self._group_api.apply_group_preference_tiebreak(finalized)
        finalized._explainer = explainer_ref
        pipeline_result.result = finalized
        return pipeline_result

    def _resolve_series_dedup(
        self,
        series: "pandas.Series",
        *,
        domain: str | list[str] | None,
        context: ResolutionContext | None,
    ) -> "tuple[pandas.Index, list[ResolutionResult]]":
        """Deduplicate a Series, resolve unique values, broadcast back."""
        return self._batch_resolver.resolve_series_dedup(
            series,
            domain=domain,
            context=context,
            resolve_many_fn=self._resolve_many_internal,
        )

    def _invalid_query_result(
        self, reason: ReasonCode = ReasonCode.INVALID_QUERY
    ) -> ResolutionResult:
        """Return a stable result for empty / whitespace-only / non-string queries."""
        return self._query_preparer.invalid_query_result(reason)

    def _normalize(self, text: str, pack_id: str | None = None) -> NormalizedText:
        """Normalize text using configured normalizer."""
        return self._query_preparer.normalize(text, pack_id)

    def _prepare_query(
        self,
        text: str,
        context: ResolutionContext | None,
        domains: frozenset[str] | None,
    ) -> tuple[Query, ResolutionContext]:
        """Validate and prepare query for resolution."""
        return self._query_preparer.prepare_query(text, context, domains)

    def store_for_domain(self, domain: str) -> "EntityStore":
        """Return the EntityStore backing this resolver for the given domain.

        Looks up the store by exact domain key first, then by prefix match
        (e.g. ``"geo"`` matches a pack registered as ``"geo_v2"``).

        Args:
            domain: Domain pack ID (e.g. ``"geo"`` or ``"org"``).

        Returns:
            The :class:`~resolvekit.core.store.EntityStore` for that domain.

        Raises:
            ValueError: If no store is found for the given domain.
        """
        return self._runner.store_for_domain(domain)

    # ------------------------------------------------------------------
    # BYOD verbs: from_records + augment
    # ------------------------------------------------------------------

    @classmethod
    def from_records(
        cls,
        data: Any,
        *,
        domain: str = "custom",
        namespace: str | None = None,
        name: "str | list[str]",
        id: str | None = None,
        aliases: "str | list[str] | None" = None,
        codes: "list[str] | dict[str, str] | None" = None,
        attrs: "list[str] | Literal['rest'] | None" = None,
        entity_type: str | None = None,
        cache: bool = True,
        warm: bool = True,
        **resolver_kwargs: Any,
    ) -> "Resolver":
        """Stand up a standalone resolver from user-supplied records.

        Every row mints a new entity under ``<namespace>/<id>``; there is no
        base to link against.  Pass ``attrs="rest"`` to keep all unlisted
        columns as entity attributes; the default drops them.

        ``data`` is positional by convention — consistent with ``resolve(text,
        *,…)`` / ``parse`` / ``bulk`` where the *subject* is positional and
        *options* are keyword-only.

        When the same ``id`` value appears in more than one row, the first
        occurrence's ``canonical_name`` and ``entity_type`` win; later rows
        with the same ``id`` do not replace them but still contribute their
        codes and aliases, which accumulate onto the entity.  The build is
        sized for up to ~1e5 rows; larger inputs are accepted but will be slower.

        Args:
            data: Records in any supported form — ``list[dict]``, ``dict``
                (id→record), CSV/JSON/JSONL file path, or a pandas/polars
                DataFrame (duck-typed; neither library is imported).
            domain: Domain pack — ``"custom"`` (default, zero-config),
                ``"geo"``, or ``"org"`` to reuse richer domain semantics.
            namespace: Entity-ID prefix (e.g. ``"my_widgets"``).  Defaults to
                *domain*.  Must match ``^[a-zA-Z0-9][a-zA-Z0-9_-]*$``.
            name: Required — canonical name column name(s).
            id: Column whose values become entity-ID seeds.  Sequential integers
                are assigned when ``None``.
            aliases: Alias column name(s).
            codes: Code columns.  List form ``["sku"]`` → system name equals
                column name.  Dict form ``{"sku": "product_code"}`` → system →
                column.
            attrs: Attribute columns, ``"rest"`` (keep all unlisted), or
                ``None`` (default — drop unlisted).
            entity_type: Column name or literal to stamp on all entities.
            cache: Cache the built pack on disk under the configured cache
                directory.  ``True`` (default) reuses an identical-input build on
                subsequent calls; ``False`` always rebuilds to a fresh temp dir.
            warm: Start a background index warm-up on construction (see
                ``Resolver.__init__`` for full docs).
            **resolver_kwargs: Forwarded verbatim to
                :meth:`from_datapacks` (e.g. ``routing_mode``,
                ``confidence_threshold``).

        Note:
            ``from_records`` does not accept a ``columns=`` shorthand (unlike
            :meth:`augment`).  To map a non-standard column name, pass the
            actual column name directly — e.g. ``name="country_name"`` or
            ``codes={"iso3": "iso3_col"}``.

        Returns:
            A new :class:`Resolver` resolving against the built pack.

        Raises:
            ValueError: If *namespace* (or *domain* when *namespace* is unset)
                contains disallowed characters (path-traversal guard).
            ValueError: If *name* is missing or a *codes* column does not exist
                in the records.
        """
        from resolvekit.core.api._byod import prepare_standalone_pack

        outcome = prepare_standalone_pack(
            data=data,
            domain=domain,
            namespace=namespace,
            name=name,
            id=id,
            aliases=aliases,
            codes=codes,
            attrs=attrs,
            entity_type=entity_type,
            cache=cache,
        )

        return cls.from_datapacks(
            datapack_paths=[outcome.pack_dir],
            domains=[domain],
            warm=warm,
            **resolver_kwargs,
        )

    @overload
    def augment(
        self,
        data: Any,
        *,
        link_on: list[str],
        columns: "dict[str, str] | None" = None,
        add_codes: "list[str] | None" = None,
        add_aliases: "str | list[str] | None" = None,
        add_attrs: "list[str] | Literal['rest'] | None" = None,
        on_miss: "Literal['mint', 'skip', 'error']" = "skip",
        namespace: str | None = None,
        return_report: Literal[False] = False,
        cache: bool = True,
    ) -> "Resolver": ...

    @overload
    def augment(
        self,
        data: Any,
        *,
        link_on: list[str],
        columns: "dict[str, str] | None" = None,
        add_codes: "list[str] | None" = None,
        add_aliases: "str | list[str] | None" = None,
        add_attrs: "list[str] | Literal['rest'] | None" = None,
        on_miss: "Literal['mint', 'skip', 'error']" = "skip",
        namespace: str | None = None,
        return_report: Literal[True],
        cache: bool = True,
    ) -> "AugmentResult": ...

    def augment(
        self,
        data: Any,
        *,
        link_on: list[str],
        columns: "dict[str, str] | None" = None,
        add_codes: "list[str] | None" = None,
        add_aliases: "str | list[str] | None" = None,
        add_attrs: "list[str] | Literal['rest'] | None" = None,
        on_miss: "Literal['mint', 'skip', 'error']" = "skip",
        namespace: str | None = None,
        return_report: bool = False,
        cache: bool = True,
    ) -> "Resolver | AugmentResult":
        """Attach extra codes, aliases, or attributes to this resolver's base entities.

        Builds an OVERLAY pack by linking each row to an existing entity via the
        ordered ``link_on`` systems, then composing a new resolver from the
        original base plus the overlay.  The original resolver is unchanged.

        ``data`` is positional — consistent with the rest of the BYOD/resolve
        surface.

        ``"name"`` in *link_on* is a strategy sentinel meaning "match by exact
        normalised canonical name"; it is not a column reference.

        *namespace* is used only when ``on_miss="mint"``; it prefixes newly
        minted entity IDs.  When unset, the base domain is used.

        Args:
            data: Records to augment with — any supported BYOD source.
            link_on: Ordered list of systems to try for linking.  Each entry
                must be ``"name"`` or a system present in
                ``self.code_systems()``.  Empty list is rejected (use
                :meth:`from_records` to stand up a standalone pack).
            columns: Role/system → column-name override for the record schema.
            add_codes: Code-column names to add to linked/minted entities. To
                map a logical system name to a differently-named column, pass
                ``columns={"<system>": "<column>"}``.
            add_aliases: Alias column name(s) to add.
            add_attrs: Attribute columns to add, or ``"rest"`` for all
                unlisted columns.
            on_miss: Behaviour for rows that do not link —
                ``"skip"`` (default, drops the row),
                ``"mint"`` (creates a new entity under *namespace*),
                ``"error"`` (raises ``ValueError``).
            namespace: Entity-ID prefix for minted rows.  Required when
                ``on_miss="mint"`` and the default domain prefix is not
                desired.  Must match ``^[a-zA-Z0-9][a-zA-Z0-9_-]*$``.
            return_report: When ``True``, return an :class:`AugmentResult`
                carrying the new resolver and tally counters.  The default
                returns only the resolver.  When the overlay is served from
                the cache (``cache=True`` and identical inputs), tally counters
                are read from a ``byod_tally.json`` sidecar persisted at build
                time and returned faithfully — they are identical to those from
                the original fresh build.
            cache: Cache the overlay pack on disk.  ``True`` (default) reuses
                an identical-input build; ``False`` always rebuilds.

        Returns:
            A new :class:`Resolver` (or :class:`AugmentResult` when
            ``return_report=True``) composing the original base + overlay.

        Raises:
            ValueError: If *link_on* is empty.
            ValueError: If any *link_on* entry is not ``"name"`` and not in
                ``self.code_systems()``.
            ValueError: If *namespace* contains disallowed characters.
            ValueError: If this resolver has more than one domain and the
                target domain is ambiguous.
            RuntimeError: If the resolver has been closed.
        """
        if self._closed:
            raise RuntimeError("Resolver has been closed")

        from resolvekit.core.api._byod import prepare_augment_pack
        from resolvekit.core.byod.result import AugmentResult

        prep = prepare_augment_pack(
            data=data,
            link_on=link_on,
            columns=columns,
            add_codes=add_codes,
            add_aliases=add_aliases,
            add_attrs=add_attrs,
            on_miss=on_miss,
            namespace=namespace,
            cache=cache,
            loaded_modules=self._loaded_modules,
            available_systems=self.code_systems(),
        )

        # Compose a new resolver: base dirs + overlay dir.
        new_resolver = type(self).from_datapacks(
            datapack_paths=[*prep.base_dirs, prep.outcome.pack_dir],
            domains=[prep.domain],
        )

        if return_report:
            return AugmentResult(
                resolver=new_resolver,
                linked=prep.outcome.linked,
                minted=prep.outcome.minted,
                skipped=prep.outcome.skipped,
                ambiguous=prep.outcome.ambiguous,
                errors=prep.outcome.errors,
            )
        return new_resolver
