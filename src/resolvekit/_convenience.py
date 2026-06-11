"""Module-level convenience functions for resolvekit.

Provides singleton-managed access to a default Resolver so users can write:

    import resolvekit
    resolvekit.resolve_id("United States")  # -> "country/USA"
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from resolvekit.core.config import _UNSET as _CONFIG_UNSET

if TYPE_CHECKING:
    from resolvekit.core.api.modules import ModuleInfo
    from resolvekit.core.api.output_view import OutputView
    from resolvekit.core.api.resolver import Resolver
    from resolvekit.core.model import EntityRecord, ResolutionContext
    from resolvekit.core.model.crosswalk import Crosswalk
    from resolvekit.core.parse.result import ParseResult

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_default: Resolver | None = None
_default_pid: int | None = None


def _reset_default_after_fork() -> None:
    """Module-level fork hook: discard the parent's default after fork.

    Runs in the child process with the world stopped, so it does not need
    to take ``_lock``. Subsequent ``_get_default()`` calls in the child
    construct a fresh ``Resolver`` against the child's pid.

    Do NOT call ``_default.close()`` here: the inherited SQLite connection
    pool was opened by the parent; closing it from the child can deadlock
    or write to the WAL under another process's lock. Drop the reference
    and let GC run; the parent will close its own copy at exit.
    """
    global _default, _default_pid
    _default = None
    _default_pid = None


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_default_after_fork)


def _get_default() -> Resolver:
    """Return the cached default resolver, creating one on first call.

    After a fork, ``os.register_at_fork(after_in_child=...)`` clears the
    inherited resolver so the child constructs its own.  Reads ``default_to``
    and ``on_missing`` from core config so a prior ``configure()`` call is
    honoured on the next resolver build.
    """
    global _default, _default_pid
    if _default is not None:
        return _default
    with _lock:
        if _default is not None:
            return _default
        from resolvekit.core.api.resolver import Resolver
        from resolvekit.core.config import get_default_to, get_on_missing

        _default = Resolver.auto(
            default_to=get_default_to(),
            on_missing=get_on_missing(),
        )
        _default_pid = os.getpid()
        logger.debug("Resolver initialized for pid %d", _default_pid)
        return _default


def default() -> Resolver:
    """Return the singleton default resolver.

    Creates it on first call using :meth:`Resolver.auto`. The same instance
    is reused until :func:`reset` or :func:`configure` is called.

    Returns:
        The cached :class:`Resolver` instance.
    """
    return _get_default()


def configure(
    *,
    auto_download: bool | None | object = _CONFIG_UNSET,
    cache_dir: str | Path | None | object = _CONFIG_UNSET,
    default_to: str | list[str] | None | object = _CONFIG_UNSET,
    on_missing: Literal["raise", "null", "auto"] | object = _CONFIG_UNSET,
) -> None:
    """Configure resolvekit runtime behavior and invalidate the singleton.

    Calling this function discards the cached default resolver so the next
    call to :func:`resolve` (or any module-level function) rebuilds it
    with the updated configuration.

    Omitting a parameter leaves any previously configured value unchanged.

    Args:
        auto_download: If True, remote packs are downloaded automatically
            when needed. ``None`` resets to the default (disabled).
            Omitting leaves the current setting unchanged.
        cache_dir: Custom cache directory for remote data packs.
            ``None`` resets to the platform default (removes any custom path).
            Omitting leaves the current setting unchanged.
        default_to: Default output code system or name variant for
            module-level resolve/bulk/snap (e.g. ``"iso3"``,
            ``["iso3", "name"]``, ``"name:fr"``). ``None`` clears the default
            so resolve() returns a raw ResolutionResult. Omitting leaves
            the current setting unchanged.
        on_missing: Miss policy for the default output chain.
            ``"auto"`` = raise for scalar resolve/snap, null +
            ``UserWarning`` for bulk; ``"raise"`` always raises
            ``OutputMissingError``; ``"null"`` always returns ``None``.
            Omitting this argument leaves any previously configured policy
            unchanged.

    Raises:
        ValueError: When ``default_to`` is not a ``str``, ``list[str]``, or
            ``None``.
        UnknownOutputError: Immediately when ``default_to`` contains a
            malformed ``name:`` grammar token, or — when a default resolver
            singleton already exists — when ``default_to`` names an unknown
            code system.  Unknown code systems with no singleton defer to the
            next resolver build (first resolve call).
    """
    from resolvekit.core.api.output_spec import _validate_grammar_only
    from resolvekit.core.config import configure as _configure_core

    if default_to is not _CONFIG_UNSET:
        # Type validation: only str, list[str], or None are accepted at configure time.
        if default_to is not None and not isinstance(default_to, (str, list)):
            raise ValueError(
                f"default_to must be a str, list of str, or None;"
                f" got {type(default_to).__name__!r}"
            )
        if isinstance(default_to, list):
            bad = [x for x in default_to if not isinstance(x, str)]
            if bad:
                raise ValueError(
                    f"default_to list must contain only strings;"
                    f" got {[type(x).__name__ for x in bad]}"
                )
        # Grammar-only validation is always eager to catch malformed name: tokens.
        if default_to is not None:
            _validate_grammar_only(default_to)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    # If a singleton exists and default_to is a non-None value, compile fully
    # against its code_systems to surface typo'd code systems immediately.
    compile_on_missing = "auto" if on_missing is _CONFIG_UNSET else on_missing
    if (
        _default is not None
        and default_to is not _CONFIG_UNSET
        and default_to is not None
    ):
        from resolvekit.core.api.output_spec import compile_output_spec

        compile_output_spec(
            default_to,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
            compile_on_missing,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
            known_systems=_default.code_systems(),
        )

    _configure_core(
        auto_download=auto_download,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        cache_dir=cache_dir,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        default_to=default_to,  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]
        on_missing=on_missing,
    )
    # Invalidate the singleton so the next call rebuilds with new config.
    reset()


def reset() -> None:
    """Close and discard the cached default resolver."""
    global _default, _default_pid
    with _lock:
        if _default is not None:
            _default.close()
        _default = None
        _default_pid = None


atexit.register(reset)


def to(
    output: str | list[str],
    *,
    on_missing: Literal["raise", "null", "auto"] = "auto",
) -> OutputView:
    """Return an :class:`~resolvekit.core.api.output_view.OutputView` from the default resolver.

    Convenience wrapper around :meth:`Resolver.to` on the singleton default
    resolver.  The view binds *output* as a fixed output spec so every call
    through it returns the configured representation.

    Args:
        output: Target code system or name variant (e.g. ``"iso3"``,
            ``["iso3", "name"]``, ``"name:fr"``).
        on_missing: Miss policy for the output chain.
            ``"auto"`` (default) = raise for scalar resolve/snap, null +
            ``UserWarning`` for bulk; ``"raise"`` always raises
            ``OutputMissingError``; ``"null"`` always returns ``None``.

    Returns:
        An :class:`~resolvekit.core.api.output_view.OutputView` bound to
        *output*.
    """
    return _get_default().to(output, on_missing=on_missing)


def resolve(
    text: str,
    *,
    to: Any = ...,  # UNSET sentinel — actual type is str|None|_Unset; deferred import
    as_result: bool = False,
    domain: str | list[str] | None = None,
    context: ResolutionContext | None = None,
    from_system: str | None = None,
    include_entity: bool = True,
    timeout: float | None = None,
) -> Any:
    """Resolve a single text string using the default resolver.

    Module-level ``resolve()`` defaults ``include_entity=True`` so notebook
    users get the rich entity object without an extra call.  Use
    ``Resolver.resolve()`` (``include_entity=False`` default) for pipeline use.

    Args:
        text: The text or code to resolve.  ``str`` is used as-is.
            ``int`` and ``float`` are coerced to string (``840`` → ``"840"``;
            ``840.0`` → ``"840"``), matching the behaviour of :func:`bulk`
            on numeric columns.  ``None`` returns a NO_MATCH result silently.
            ``bool`` and all other types raise ``TypeError``.
        to: Target representation pivot (e.g. ``"iso3"``, ``"name"``).
            Omit (default) to use the configured ``default_to`` spec, or
            returns a raw :class:`ResolutionResult` when no default is set.
            Pass ``None`` to always return a raw :class:`ResolutionResult`.
        as_result: Return the full :class:`ResolutionResult` even when a
            default output is configured — the readable equivalent of
            ``to=None``.
        domain: Optional domain pack(s) to route to.
        context: Optional resolution context.
        from_system: Force-disambiguate input as a specific code system.
        include_entity: Populate ``result.entity``. Defaults to ``True``
            at the module level for notebook ergonomics.
        timeout: Maximum seconds to wait.

    Returns:
        :class:`~resolvekit.ResolutionResult` when no default spec is set or
        ``as_result=True``; otherwise the configured output value (str or None).
    """
    from resolvekit.core.api.output_spec import UNSET

    effective_to = UNSET if to is ... else to
    return _get_default().resolve(
        text,
        to=effective_to,
        as_result=as_result,
        domain=domain,
        context=context,
        from_system=from_system,
        include_entity=include_entity,
        timeout=timeout,
    )


def resolve_id(
    text: str,
    *,
    on_ambiguous: Literal["raise", "null", "best"] = "raise",
    from_system: str | None = None,
    domain: str | list[str] | None = None,
    context: ResolutionContext | None = None,
    timeout: float | None = None,
) -> str | None:
    """Resolve text and return entity_id or None.

    Args:
        text: Text to resolve.  ``str`` is used as-is.  ``int`` and
            ``float`` are coerced to string (``840`` → ``"840"``;
            ``840.0`` → ``"840"``), matching the behaviour of :func:`bulk`
            on numeric columns.  ``None`` returns ``None`` silently.
            ``bool`` and all other types raise ``TypeError``.
        on_ambiguous: Behavior when multiple entities match.
            - ``"raise"`` (default): raises :class:`AmbiguousResolutionError`.
            - ``"null"``: returns ``None`` on ambiguity.
            - ``"best"``: returns the top candidate's entity_id.
        from_system: Force-disambiguate input as a specific code system
            (e.g. ``"iso2"``).
        domain: Optional domain(s) to route to.
        context: Optional resolution context.
        timeout: Maximum seconds to wait.

    Returns:
        Entity ID string, or None if no match.

    Raises:
        TypeError: If *text* is a ``bool``, ``bytes``, ``list``, or any
            other unsupported type.
        AmbiguousResolutionError: If ``on_ambiguous="raise"`` and the
            resolution is ambiguous.
    """
    return _get_default().resolve_id(
        text,
        on_ambiguous=on_ambiguous,
        from_system=from_system,
        domain=domain,
        context=context,
        timeout=timeout,
    )


def bulk(
    *,
    values: Any,
    to: Any = ...,  # UNSET sentinel — actual type is str|None|_Unset; deferred import
    on_missing: Any = ...,  # UNSET sentinel — actual type is Literal[...] | _Unset
    domain: str | list[str] | None = None,
    context: ResolutionContext | None = None,
    output: Literal["series", "record", "frame"] = "series",
    from_system: str | None = None,
    not_found: str = "null",
    on_error: Literal["raise", "null", "keep"] = "raise",
    on_ambiguous: Literal["null", "raise", "best"] = "null",
    crosswalk: Crosswalk | None = None,
) -> Any:
    """Bulk resolution using the default resolver.

    Delegates to :meth:`Resolver.bulk` with the singleton default resolver.

    Args:
        values: Input collection (list, pd.Series, pl.Series, np.ndarray,
            or dict — resolves the values and returns a same-keyed dict).
        to: Optional pivot target (same semantics as scalar ``resolve()``).
            Omit to use the configured ``default_to`` spec.
        on_missing: Miss policy override for the default output spec.
            Omit to inherit the resolver's configured ``on_missing`` policy.
            ``"auto"`` (default when using a spec) = raise for scalar
            resolve/snap, null + ``UserWarning`` for bulk; ``"raise"`` raises
            ``OutputMissingError`` on the first missing row; ``"null"``
            returns ``None`` per row.
        domain: Optional domain filter.
        context: Optional resolution context.
        output: Output shape — ``"series"`` (default), ``"record"``
            (Series-of-struct), or ``"frame"`` (DataFrame for pandas/polars
            input, list-of-dict otherwise).  Ignored when ``to`` is a scalar.
        from_system: Force code-system for lookup (skips auto-detect).
        not_found: ``"null"`` (default) → ``None``; ``"raise"`` → raises;
            any other string → literal sentinel.
        on_error: ``"raise"`` (default), ``"null"``, or ``"keep"``.
        on_ambiguous: ``"null"`` (default), ``"raise"``, or ``"best"``.
        crosswalk: Optional :class:`~resolvekit.Crosswalk` that short-circuits
            resolution for matched values.  Values in the crosswalk bypass
            code-detection, ``on_ambiguous``, ``not_found``, and
            ``from_system`` entirely.  ``rk.IGNORE`` entries yield ``None``
            unconditionally.

    Returns:
        :class:`~resolvekit.core.model.bulk_result.BulkResult` or native
        series/list when a pivot spec is active.
    """
    from resolvekit.core.api.output_spec import UNSET

    effective_to = UNSET if to is ... else to
    effective_on_missing = UNSET if on_missing is ... else on_missing
    return _get_default().bulk(
        values=values,
        to=effective_to,
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


def snap(
    *,
    query: str,
    candidates: list[str],
    max_distance: float = 0.5,
    to: Any = ...,  # UNSET sentinel — actual type is str|None|_Unset; deferred import
    domain: str | list[str] | None = None,
    context: ResolutionContext | None = None,
) -> Any:
    """Return the closest match from an explicit candidate list.

    Delegates to :meth:`Resolver.snap` with the singleton default resolver.

    Args:
        query: Text to match.
        candidates: Candidate entity IDs or names to match against.
        max_distance: Confidence floor; below this threshold returns ``None``.
        to: Optional pivot (same semantics as :func:`resolve`).
            Omit to use the configured ``default_to`` spec.
        domain: Optional domain filter.
        context: Optional resolution context.

    Returns:
        The closest matching candidate (entity_id by default, pivoted when a
        default spec is set, or pivoted via ``to``), or ``None`` when below
        threshold.
    """
    from resolvekit.core.api.output_spec import UNSET

    effective_to = UNSET if to is ... else to
    return _get_default().snap(
        query=query,
        candidates=candidates,
        max_distance=max_distance,
        to=effective_to,
        domain=domain,
        context=context,
    )


def entity(
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

    Delegates to :meth:`Resolver.entity` with the singleton default resolver.

    Returns:
        :class:`~resolvekit.EntityRecord` if found, ``None`` otherwise.
    """
    return _get_default().entity(
        text_or_id,
        alpha_2=alpha_2,
        alpha_3=alpha_3,
        numeric=numeric,
        iso2=iso2,
        iso3=iso3,
        dcid=dcid,
        domain=domain,
        **code_kwargs,
    )


def modules() -> list[ModuleInfo]:
    """List every module installed in this resolvekit installation.

    Returns the full catalog: bundled modules (always available) plus
    remote modules (``is_available=True`` only when their data is on disk).

    Returns:
        List of :class:`~resolvekit.core.api.modules.ModuleInfo`, sorted by
        ``module_id``.
    """
    from resolvekit.core.api.modules import modules as _modules

    return _modules()


def download(target: str, *, force: bool = False) -> dict[str, Path]:
    """Download remote module data.

    Args:
        target: Module ID (``"geo.cities"``) or domain (``"geo"``)
        force: Re-download even if cached

    Returns:
        Dict of module_id -> cache_path for downloaded modules
    """
    from resolvekit.core.download_api import download as _download

    return _download(target, force=force)


def download_all(*, force: bool = False) -> dict[str, Path]:
    """Download all installed remote modules.

    Args:
        force: Re-download even if cached

    Returns:
        Dict of module_id -> cache_path for downloaded modules
    """
    from resolvekit.core.download_api import download_all as _download_all

    return _download_all(force=force)


def clear_cache(target: str | None = None) -> None:
    """Clear cached module data.

    Args:
        target: Module ID to clear, or None to clear all.
    """
    from resolvekit.core.download_api import clear_cache as _clear_cache

    _clear_cache(target)


def parse(
    text: str,
    *,
    domain: str | list[str] | None = None,
    context: ResolutionContext | None = None,
    to: str | list[str] | None = None,
    confidence_threshold: float | None = None,
    include_nil: bool = False,
    timeout: float | None = None,
) -> ParseResult:
    """Extract and link every pack-known entity mention in ``text``.

    Module-level wrapper; delegates to the singleton default resolver's
    :meth:`~resolvekit.core.api.resolver.Resolver.parse`.

    Returns a :class:`~resolvekit.core.parse.result.ParseResult` of
    :class:`~resolvekit.core.parse.result.ParsedEntity` objects with
    raw-input offsets, confidence, type, and full ``.resolution.explain()``,
    ordered by ascending start offset.

    Two abstention channels: NIL spans (detected but below threshold,
    ``status=NO_MATCH``) appear only with ``include_nil=True``; gate-rejected
    spans (sentinel/short-input/word-boundary) always live on
    ``ParseResult.dropped_spans`` as a debug channel and are never emitted as
    entities.  By default the result holds only resolved entities, so
    ``e.confidence`` is a float on the common path.

    Cost is ``O(spans x packs x passes x pipeline)``; each span is a full
    pipeline run.  Repeated surfaces of the same entity-type within one call
    hit the query cache; distinct surfaces miss.  When ``to=`` is set, one
    ``get_entity`` hydration per RESOLVED span is added (SQLite point read).
    Use one Resolver per thread (the query cache is not thread-safe).

    Args:
        text: Free-text input string.
        domain: Pack(s) to detect over.  ``None`` routes to all available.
        context: Resolution hints (country, as_of, etc.) broadcast to every
            span.
        to: Output pivot applied to each RESOLVED entity (e.g. ``"iso3"``).
            NIL spans get ``output=None``.  Does not collapse the result.
        confidence_threshold: Minimum calibrated confidence.  ``None`` uses
            each pack's built-in threshold.
        include_nil: Surface detected-but-below-threshold spans when ``True``.
        timeout: Soft per-call budget in seconds (no new machinery).

    Returns:
        :class:`~resolvekit.core.parse.result.ParseResult` with entities
        sorted by start offset and a ``dropped_spans`` debug channel.

    Raises:
        ImportError: If ``ahocorasick_rs`` is not installed; install with
            ``pip install 'resolvekit[parsing]'``.
    """
    return _get_default().parse(
        text,
        domain=domain,
        context=context,
        to=to,
        confidence_threshold=confidence_threshold,
        include_nil=include_nil,
        timeout=timeout,
    )


def warm() -> None:
    """Pre-build all lazily-constructed indexes, blocking until complete.

    Useful for servers and batch jobs that want to ensure full query
    performance before handling the first real request.

    Note: constructing the default resolver already starts a background
    warm-up (``warm=True`` is the default); call this function when you
    need to block until that warm-up is complete.
    """
    _get_default().warm()


def parse_bulk(
    *,
    values: Any,
    domain: str | list[str] | None = None,
    context: ResolutionContext | None = None,
    to: str | list[str] | None = None,
    confidence_threshold: float | None = None,
    include_nil: bool = False,
    timeout: float | None = None,
) -> ParseResult:
    """Parse a column of free-text values into a ragged ParseResult.

    Module-level wrapper; delegates to the singleton default resolver's
    :meth:`~resolvekit.core.api.resolver.Resolver.parse_bulk`.

    Each row produces zero or more
    :class:`~resolvekit.core.parse.result.ParsedEntity` objects.
    ``ParsedEntity.row_idx`` tags the source row (0-based).
    ``.to_dataframe()`` yields the exploded table with columns
    ``[row_idx, surface, entity_id, entity_type, pack_id, status,
    confidence, start, end, to]``.  No cross-row deduplication.
    Single-threaded.

    Two abstention channels: ``include_nil=True`` surfaces
    detected-but-below-threshold spans as NIL entities; gate-rejected
    spans always land on ``ParseResult.dropped_spans``.

    Cost is ``O(rows x spans x packs x passes x pipeline)``.  When
    ``to=`` is set, one ``get_entity`` hydration per RESOLVED span is added.
    ``None``/NaN rows contribute zero entities (no crash).

    Args:
        values: Text column — ``list``, ``tuple``, ``pd.Series``,
            ``pl.Series``, or ``numpy.ndarray``.
        domain: Pack(s) to detect over.  ``None`` routes to all available.
        context: Resolution hints broadcast to every span in every row.
        to: Output pivot applied to each RESOLVED entity.
        confidence_threshold: Minimum calibrated confidence.
        include_nil: Surface detected-but-below-threshold spans when ``True``.
        timeout: Soft per-call budget (no new machinery).

    Returns:
        :class:`~resolvekit.core.parse.result.ParseResult` with all rows
        concatenated.

    Raises:
        TypeError: If ``values`` is an unsupported type.
        ImportError: If ``ahocorasick_rs`` is not installed; install with
            ``pip install 'resolvekit[parsing]'``.
    """
    return _get_default().parse_bulk(
        values=values,
        domain=domain,
        context=context,
        to=to,
        confidence_threshold=confidence_threshold,
        include_nil=include_nil,
        timeout=timeout,
    )
