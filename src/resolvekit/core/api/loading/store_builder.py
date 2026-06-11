"""Store construction helpers used during ``Resolver`` instantiation.

These functions build ``EntityStore`` instances from loaded datapacks,
composing base and overlay stores into the final per-domain stores handed
to ``MultiPackRunner``.
"""

from __future__ import annotations

from resolvekit.core.datapack import LoadedDataPack
from resolvekit.core.linking import BaseNormalizer, Normalizer
from resolvekit.core.registry import DomainPack
from resolvekit.core.store import (
    CompositeStore,
    EntityStore,
    SQLiteEntityStore,
    compose_base_module_store,
)
from resolvekit.core.store.merging import MergingCompositeStore, OverlayPolicy
from resolvekit.core.store.sqlite import SQLiteTuning


def _build_domain_stores(
    base_packs: dict[str, LoadedDataPack],
    overlay_packs: dict[str, LoadedDataPack],
    pack_filter: set[str],
    *,
    sqlite_tuning: SQLiteTuning | None = None,
) -> tuple[
    dict[str, list[EntityStore]],
    dict[str, LoadedDataPack],
    dict[str, list[OverlayPolicy | None]],
    dict[str, list[LoadedDataPack]],
]:
    """Build domain stores with overlay composition.

    Args:
        base_packs: Base module datapacks keyed by module_id.
        overlay_packs: Overlay datapacks keyed by module_id.
        pack_filter: When non-empty, restrict to packs in this set.
        sqlite_tuning: SQLite connection tuning parameters forwarded to all
            created stores.

    Returns:
        Tuple of (domain_stores, domain_primary_loaded, domain_overlay_policies,
        domain_all_base_loaded).
        domain_overlay_policies[pack_id][i] corresponds to domain_stores[pack_id][i];
        None means base store, OverlayPolicy means overlay store.
        domain_all_base_loaded[pack_id] is the full list of base LoadedDataPacks for
        the domain (used to collect per-module artifacts such as symspell dicts).
    """
    domain_stores: dict[str, list[EntityStore]] = {}
    domain_primary_loaded: dict[str, LoadedDataPack] = {}
    domain_overlay_policies: dict[str, list[OverlayPolicy | None]] = {}
    domain_base_loaded: dict[str, list[LoadedDataPack]] = {}

    # Collect base packs first so same-domain modules can be composed together.
    for loaded in base_packs.values():
        pack_id = loaded.pack_id
        if pack_filter and pack_id not in pack_filter:
            continue

        if pack_id not in domain_stores:
            domain_stores[pack_id] = []
            domain_overlay_policies[pack_id] = []
            domain_primary_loaded[pack_id] = loaded
            domain_base_loaded[pack_id] = []
        domain_base_loaded[pack_id].append(loaded)
    for pack_id, loaded_list in domain_base_loaded.items():
        domain_stores[pack_id].append(
            compose_base_module_store(
                domain=pack_id,
                loaded_packs=loaded_list,
                sqlite_tuning=sqlite_tuning,
            )
        )
        domain_overlay_policies[pack_id].append(None)

    # Add overlay stores (overlays appended last - highest precedence)
    for loaded in overlay_packs.values():
        pack_id = loaded.pack_id
        if pack_filter and pack_id not in pack_filter:
            continue
        if pack_id not in domain_stores:
            continue
        domain_stores[pack_id].append(
            SQLiteEntityStore(loaded.db_path, tuning=sqlite_tuning)
        )
        domain_overlay_policies[pack_id].append(
            OverlayPolicy(allow_new_entities=loaded.metadata.allow_new_entities)
        )

    return (
        domain_stores,
        domain_primary_loaded,
        domain_overlay_policies,
        domain_base_loaded,
    )


def _build_final_stores(
    domain_stores: dict[str, list[EntityStore]],
    available_packs: dict[str, DomainPack],
    pack_normalizers_for_merge: dict[str, Normalizer],
    domain_overlay_policies: dict[str, list[OverlayPolicy | None]] | None = None,
) -> dict[str, EntityStore]:
    """Build final stores with MergingCompositeStore for overlays."""
    stores: dict[str, EntityStore] = {}
    domain_overlay_policies = domain_overlay_policies or {}

    for pack_id, store_list in domain_stores.items():
        if pack_id not in available_packs:
            continue

        if len(store_list) == 1:
            stores[pack_id] = store_list[0]
        else:
            overlay_policies = domain_overlay_policies.get(pack_id)
            if overlay_policies and any(
                policy is not None for policy in overlay_policies
            ):
                merge_normalizer = pack_normalizers_for_merge.get(
                    pack_id, BaseNormalizer()
                )
                stores[pack_id] = MergingCompositeStore(
                    store_list, merge_normalizer, overlay_policies
                )
            else:
                stores[pack_id] = CompositeStore(store_list)

    return stores
