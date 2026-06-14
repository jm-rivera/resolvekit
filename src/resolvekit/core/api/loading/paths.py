"""Datapack path resolution, domain normalization, router construction, and the
``_build_resolver_from_paths`` orchestrator.

This is the top-level module in the loading subpackage — it imports from its
siblings (pack_loader, store_builder, module_catalog) and orchestrates the
full construction sequence.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from resolvekit.core.engine import (
    AutoRouter,
    ExplicitRouter,
    HybridRouter,
    MultiPackRunner,
    RoutingMode,
)
from resolvekit.core.errors import ResolutionError
from resolvekit.core.explain import MemoryTraceSink, NullTraceSink, TraceSink
from resolvekit.core.model import ResolutionResult
from resolvekit.core.util.normalization import TextNormalizer

if TYPE_CHECKING:
    from resolvekit.core.api.resolver import Resolver
    from resolvekit.core.store.sqlite import SQLiteTuning
    from resolvekit.core.util.sentinel import SentinelBlocklist

logger = logging.getLogger(__name__)


def _resolution_error(text: str, result: ResolutionResult) -> ResolutionError:
    """Build a ResolutionError for a non-resolved, non-ambiguous result."""
    return ResolutionError(
        status=result.status,
        candidates=list(result.candidates),
        message=f"Resolution error for {text!r}: "
        f"reasons={[r.value for r in result.reasons]}",
    )


def _normalize_domain(domain: str | list[str] | None) -> frozenset[str] | None:
    """Convert the public ``domain`` parameter to an internal ``frozenset[str] | None``.

    Returns a frozenset (immutable + hashable) so callers can use it as a
    pack_filter without defensive copying.
    """
    if domain is None:
        return None
    domains = {domain} if isinstance(domain, str) else set(domain)
    dotted = sorted(d for d in domains if "." in d)
    if dotted:
        raise ValueError(
            f"Domain names must be simple strings (e.g., 'geo'), not dotted. "
            f"Got: {dotted}. Did you mean entity_types={set(dotted)!r} "
            f"in ResolutionContext?"
        )
    return frozenset(domains)


def _build_router(
    mode: RoutingMode,
    available_packs: list[str],
    pack_hints: dict[str, Any] | None = None,
) -> ExplicitRouter | AutoRouter | HybridRouter:
    """Build router based on routing mode."""
    if mode == RoutingMode.EXPLICIT:
        return ExplicitRouter(available_packs=available_packs)
    elif mode == RoutingMode.HYBRID:
        return HybridRouter(packs=available_packs)
    else:
        return AutoRouter(available_packs=available_packs, pack_hints=pack_hints)


def _resolve_datapack_path(path_or_name: str | Path) -> Path:
    """Resolve an explicit datapack path to a filesystem path."""
    p = Path(path_or_name)

    # Path objects are always treated as filesystem paths
    if isinstance(path_or_name, Path):
        return p

    if p.is_dir() and (p / "metadata.json").is_file():
        return p

    raise FileNotFoundError(
        f"Explicit datapack path not found or missing metadata.json: {path_or_name}. "
        "Use Resolver.from_modules() for installed module discovery."
    )


def _expand_datapack_input(path_or_name: str | Path) -> list[Path]:
    """Normalize a datapack input to a single explicit datapack directory."""
    return [_resolve_datapack_path(path_or_name)]


def _build_resolver_from_paths(
    *,
    cls: type[Resolver],
    datapack_paths: list[str | Path],
    packs: list[str] | None,
    routing_mode: RoutingMode,
    trace: bool | TraceSink,
    normalizer: TextNormalizer | None,
    max_query_length: int,
    cache_size: int = 1024,
    sqlite_tuning: SQLiteTuning | None = None,
    default_timeout: float | None = None,
    confidence_threshold: float | None = None,
    sentinel_blocklist: SentinelBlocklist | None = None,
    default_to: str | list[str] | None = None,
    on_missing: Literal["raise", "null", "auto"] = "auto",
    warm: bool = True,
) -> Resolver:
    from resolvekit.core.api.loading.module_catalog import (
        _ensure_remote_data_available,
        _load_and_separate_datapacks,
        _validate_module_dependencies,
        _validate_overlay_relationships,
    )
    from resolvekit.core.api.loading.pack_loader import _create_pack_instances
    from resolvekit.core.api.loading.store_builder import (
        _build_domain_stores,
        _build_final_stores,
    )
    from resolvekit.core.registry import _ensure_builtin_factories

    _ensure_builtin_factories()
    pack_filter = set(packs or [])

    _ensure_remote_data_available(datapack_paths, pack_filter)

    base_packs, overlay_packs = _load_and_separate_datapacks(
        datapack_paths, pack_filter
    )
    _validate_module_dependencies(base_packs, overlay_packs, pack_filter)
    _validate_overlay_relationships(overlay_packs, base_packs, pack_filter)

    (
        domain_stores,
        domain_primary_loaded,
        domain_overlay_policies,
        domain_all_base_loaded,
    ) = _build_domain_stores(
        base_packs, overlay_packs, pack_filter, sqlite_tuning=sqlite_tuning
    )
    available_packs, pack_profiles, pack_normalizers_for_merge = _create_pack_instances(
        domain_primary_loaded, domain_all_base_loaded
    )

    if not available_packs:
        raise ValueError(
            f"No valid packs found in datapacks. "
            f"Filter: {pack_filter or 'none'}, paths: {datapack_paths}"
        )

    stores = _build_final_stores(
        domain_stores,
        available_packs,
        pack_normalizers_for_merge,
        domain_overlay_policies,
    )

    pack_hints = {}
    for pack_id, pack in available_packs.items():
        if pack.routing_hints is not None:
            pack_hints[pack_id] = pack.routing_hints

    router = _build_router(
        routing_mode, list(available_packs.keys()), pack_hints=pack_hints
    )
    if isinstance(trace, TraceSink):
        trace_sink: TraceSink = trace
    elif trace:
        trace_sink = MemoryTraceSink()
    else:
        trace_sink = NullTraceSink()
    pack_normalizers = {
        pack_id: TextNormalizer(profile) for pack_id, profile in pack_profiles.items()
    }

    runner = MultiPackRunner(
        router=router,
        packs=available_packs,
        stores=stores,
        trace_sink=trace_sink,
        pack_normalizers=pack_normalizers,
        pack_code_normalizers=pack_normalizers_for_merge,
    )

    loaded_modules = {
        pack_id: list(modules)
        for pack_id, modules in domain_all_base_loaded.items()
        if pack_id in available_packs
    }

    # Capture the loaded overlay packs so the Resolver can carry them forward
    # into chained augment() calls — prior overlays would otherwise be dropped
    # because domain_all_base_loaded contains only base packs.
    loaded_overlays = list(overlay_packs.values())

    return cls(
        runner=runner,
        normalizer=normalizer,
        pack_profiles=pack_profiles,
        max_query_length=max_query_length,
        routing_mode=routing_mode,
        loaded_modules=loaded_modules,
        loaded_overlays=loaded_overlays,
        cache_size=cache_size,
        sqlite_tuning=sqlite_tuning,
        default_timeout=default_timeout,
        confidence_threshold=confidence_threshold,
        sentinel_blocklist=sentinel_blocklist,
        default_to=default_to,
        on_missing=on_missing,
        warm=warm,
    )
