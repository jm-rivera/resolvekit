"""Pack instantiation and feature-schema validation helpers.

These are pure functions used during ``Resolver`` construction to turn
loaded datapack metadata into live ``DomainPack`` instances.
"""

from __future__ import annotations

import inspect
from typing import Any

from resolvekit.core.datapack import LoadedDataPack
from resolvekit.core.errors import IncompatibleFeatureSchemaError
from resolvekit.core.linking import Normalizer
from resolvekit.core.registry import DomainPack, get_pack_factory
from resolvekit.core.util.normalization import NormalizationProfile

_DOMAIN_ARTIFACT_PARAMS: dict[str, str] = {
    "calibrator": "calibrator_path",
    "model": "model_path",
}


def _create_pack_instance(
    pack_factory: type,
    loaded: Any,
    all_loaded: list[Any] | None = None,
) -> Any:
    """Create pack instance, passing artifact paths for accepted parameters.

    This allows custom pack factories to work without requiring them to
    accept any particular parameter. Built-in packs (geo, org) accept
    symspell_dict_path and calibrator_path for optional artifact loading.

    When *all_loaded* contains multiple modules for the same domain and the
    factory accepts ``symspell_dict_paths_small`` / ``symspell_dict_paths_large``
    (the split-index API), dictionaries are partitioned by module ID into the
    SMALL group (countries, admin1, regions, continents, continental unions) and
    the LARGE group (admin2-5, cities).  Each group gets its own lazily-built
    SymSpell index at full params (prefix_length=7, max_edit_distance=2) so
    country-tier recall is independent of whether large-tier data is loaded.

    Falls back to the legacy ``symspell_dict_paths`` (plural) or scalar
    ``symspell_dict_path`` when the factory does not declare the split-index
    parameters.
    """
    try:
        sig = inspect.signature(pack_factory)
    except (ValueError, TypeError):
        return pack_factory()

    has_var_keyword = any(
        p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
    )

    def _accepts(param_name: str) -> bool:
        if has_var_keyword:
            return True
        param = sig.parameters.get(param_name)
        return param is not None and param.kind != inspect.Parameter.POSITIONAL_ONLY

    kwargs: dict[str, Any] = {}

    # -- SymSpell wiring: split-index API (preferred) or legacy scalar/plural --
    has_split_params = (
        "symspell_dict_paths_small" in sig.parameters
        or "symspell_dict_paths_large" in sig.parameters
    )
    has_plural_param = "symspell_dict_paths" in sig.parameters

    if has_split_params and all_loaded:
        # Partition loaded modules into SMALL and LARGE groups by module ID.
        large_tier_ids: frozenset[str] = getattr(
            pack_factory, "_LARGE_TIER_MODULE_IDS", frozenset()
        )
        small_paths: list[str] = []
        large_paths: list[str] = []
        for ld in all_loaded:
            p = ld.artifact_path("symspell")
            if p is None:
                continue
            path_str = str(p)
            if ld.module_id in large_tier_ids:
                large_paths.append(path_str)
            else:
                small_paths.append(path_str)
        if _accepts("symspell_dict_paths_small"):
            kwargs["symspell_dict_paths_small"] = small_paths if small_paths else None
        if _accepts("symspell_dict_paths_large"):
            kwargs["symspell_dict_paths_large"] = large_paths if large_paths else None
    elif all_loaded and len(all_loaded) > 1 and has_plural_param:
        # Legacy: merge all into one list (no split).
        paths = [
            str(p)
            for ld in all_loaded
            if (p := ld.artifact_path("symspell")) is not None
        ]
        kwargs["symspell_dict_paths"] = paths if paths else None
    elif _accepts("symspell_dict_path"):
        path = loaded.artifact_path("symspell")
        kwargs["symspell_dict_path"] = str(path) if path else None

    # -- Domain-level artifacts (calibrator, model, etc.: one per domain) --
    # These are NOT per-module like symspell — scan all loaded packs and take
    # the first one found.
    packs_to_scan = all_loaded if all_loaded is not None else [loaded]
    for artifact_key, param_name in _DOMAIN_ARTIFACT_PARAMS.items():
        if not _accepts(param_name):
            continue
        for ld in packs_to_scan:
            p = ld.artifact_path(artifact_key)
            if p is not None:
                kwargs[param_name] = str(p)
                break

    return pack_factory(**kwargs) if kwargs else pack_factory()


def _validate_feature_schema(pack: DomainPack, loaded: LoadedDataPack) -> None:
    """Validate feature schema version compatibility between pack and datapack."""
    extractor = pack.feature_extractor
    if extractor is None or not hasattr(extractor, "schema_version"):
        return  # No extractor or no version declared -- skip

    datapack_version = loaded.metadata.feature_schema_version
    if datapack_version is None:
        return  # No version in metadata -- skip

    extractor_version = extractor.schema_version
    if extractor_version is None:
        return

    if datapack_version == extractor_version:
        return
    raise IncompatibleFeatureSchemaError(
        pack_id=pack.pack_id,
        datapack_version=datapack_version,
        extractor_version=extractor_version,
    )


def _create_pack_instances(
    domain_primary_loaded: dict[str, LoadedDataPack],
    domain_all_base_loaded: dict[str, list[LoadedDataPack]] | None = None,
) -> tuple[
    dict[str, DomainPack], dict[str, NormalizationProfile], dict[str, Normalizer]
]:
    """Create pack instances and extract normalizers."""
    available_packs: dict[str, DomainPack] = {}
    pack_profiles: dict[str, NormalizationProfile] = {}
    pack_normalizers_for_merge: dict[str, Normalizer] = {}

    for pack_id, loaded in domain_primary_loaded.items():
        pack_factory = get_pack_factory(pack_id)
        if pack_factory is None:
            continue

        all_loaded = (domain_all_base_loaded or {}).get(pack_id)
        pack = _create_pack_instance(pack_factory, loaded, all_loaded=all_loaded)
        _validate_feature_schema(pack, loaded)
        available_packs[pack_id] = pack

        if pack.normalization_profile is not None:
            pack_profiles[pack_id] = pack.normalization_profile
        if pack.merge_normalizer is not None:
            pack_normalizers_for_merge[pack_id] = pack.merge_normalizer

    return available_packs, pack_profiles, pack_normalizers_for_merge
