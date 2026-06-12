"""BYOD build orchestrator.

``build_byod_pack`` is the entry point for both pure-mint (``Resolver.from_records``)
and base-linked overlay (``Resolver.augment``) construction."""

from __future__ import annotations

import itertools
import re
import unicodedata
from pathlib import Path
from typing import Any, NamedTuple

from resolvekit.core.byod.cache import (
    byod_cache_key,
    cached_pack_dir,
    commit_build,
    is_cache_hit,
    prepare_build_dir,
    read_tally,
    write_tally,
)
from resolvekit.core.byod.intake import ByodRecord, RecordSchema

# ---------------------------------------------------------------------------
# Custom build-time normalizer
# ---------------------------------------------------------------------------


class _CustomBuildNormalizer:
    """Build-time normalizer for the custom domain.

    Applies NFC + casefold + whitespace collapse — matching the query-time
    ``CUSTOM_NORMALIZATION_PROFILE`` in ``packs/custom/pack.py`` exactly.
    Using NFKC here would decompose compatibility characters (™ → TM, ² → 2,
    ℠ → SM, etc.) at build time while the query side preserves them, making
    labels with those characters unreachable by their stored form.
    """

    _WHITESPACE = re.compile(r"\s+")

    def normalize_name(self, value: str) -> str:
        result = unicodedata.normalize("NFC", value)
        result = self._WHITESPACE.sub(" ", result).strip()
        return result.casefold()

    def normalize_code(self, system: str, value: str) -> str:
        return value.strip().casefold()


# ---------------------------------------------------------------------------
# Builder registry
# ---------------------------------------------------------------------------


def _builder_class(domain: str) -> type:
    """Return the builder class for *domain*.

    The build-time normalizer must match the domain's query-time normalizer
    so codes round-trip correctly.
    """
    if domain == "geo":
        from resolvekit.packs.geo.build.builder import GeoDataPackBuilder

        return GeoDataPackBuilder
    if domain == "org":
        from resolvekit.packs.org.build.builder import OrgDataPackBuilder

        return OrgDataPackBuilder
    # "custom" and any future domains fall through to the generic builder.
    from resolvekit.core.byod.builder import GenericDataPackBuilder

    return GenericDataPackBuilder


def _domain_normalizer(domain: str) -> Any:
    """Return a normalizer instance for *domain* (used on the pure-mint path).

    Wires only the normalizer without opening a base store.
    """
    if domain == "geo":
        from resolvekit.packs.geo.normalizer import GeoNormalizer

        return GeoNormalizer()
    if domain == "org":
        from resolvekit.packs.org.normalizer import OrgNormalizer

        return OrgNormalizer()
    return _CustomBuildNormalizer()


# ---------------------------------------------------------------------------
# Build outcome
# ---------------------------------------------------------------------------


class ByodBuildOutcome(NamedTuple):
    """Result of a ``build_byod_pack`` call.

    Attributes:
        pack_dir: Path to the finished pack directory.
        linked: Rows linked to an existing base entity.
        minted: Rows minted as new entities.
        skipped: Unlinked rows silently dropped (``on_miss="skip"``).
        ambiguous: Rows with >1 base match (always skipped).
        errors: Diagnostic messages collected during the build.
    """

    pack_dir: Path
    linked: int
    minted: int
    skipped: int
    ambiguous: int
    errors: list[str]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_byod_pack(
    *,
    records: list[dict[str, Any]],
    schema: RecordSchema,
    domain: str,
    namespace: str,
    pack_type: str,
    base_paths: list[Path] | None = None,
    base_module_ids: list[str] | None = None,
    link_on: list[str] | None = None,
    on_miss: str = "skip",
    cache: bool = True,
    cache_extra: dict[str, Any] | None = None,
) -> ByodBuildOutcome:
    """Build a BYOD DataPack directory from normalised records.

    Called by both ``Resolver.from_records`` (``pack_type="base"``,
    ``base_paths=None``, all rows mint) and ``Resolver.augment``
    (``pack_type="overlay"``, ``base_paths`` given).

    Args:
        records: Raw row dicts from ``read_records``.
        schema: Resolved ``RecordSchema`` for the row set.
        domain: Domain string — selects the builder and normalizer.
        namespace: Entity-ID prefix (e.g. ``"my_cities"``).
        pack_type: ``"base"`` or ``"overlay"``.
        base_paths: Datapack directories forming the base composition (overlay
            only; ``None`` for base packs).
        base_module_ids: Module IDs in the base composition (written into
            overlay metadata).
        link_on: Ordered list of systems to try for linking.  ``None`` or
            ``[]`` means pure-mint (all rows become new entities).
        on_miss: ``"mint"`` | ``"skip"`` | ``"error"`` — behaviour for rows
            that don't link.
        cache: Whether to cache the built pack.  ``False`` builds to a fresh
            temp dir kept for the resolver's lifetime.
        cache_extra: Optional extra context included in the cache key (e.g.
            base-identity tuples for overlay packs).

    Returns:
        A ``ByodBuildOutcome`` with the pack directory and tally counters.
    """
    resolved_link_on: list[str] = list(link_on) if link_on else []

    key_options: dict[str, Any] = {
        "link_on": resolved_link_on,
        "on_miss": on_miss,
        "pack_type": pack_type,
    }

    base_identity: list[tuple[str, str, int, float]] | None = None
    if cache_extra and "base_identity" in cache_extra:
        base_identity = cache_extra["base_identity"]

    key = byod_cache_key(
        records=records,
        schema=schema,
        domain=domain,
        namespace=namespace,
        pack_type=pack_type,
        options=key_options,
        base_identity=base_identity,
    )

    # Cache hit — return the existing directory without rebuilding.
    if cache:
        hit_dir = cached_pack_dir(key)
        if is_cache_hit(hit_dir):
            t = read_tally(hit_dir)
            return ByodBuildOutcome(
                pack_dir=hit_dir,
                linked=t.get("linked", 0),
                minted=t.get("minted", 0),
                skipped=t.get("skipped", 0),
                ambiguous=t.get("ambiguous", 0),
                errors=[],
            )

    # Prepare a build directory (temp sibling for cache=True, or system-temp
    # directory for cache=False).
    build_dir, final_dir = prepare_build_dir(key, cache=cache)

    try:
        tally = _run_build(
            records=records,
            schema=schema,
            domain=domain,
            namespace=namespace,
            pack_type=pack_type,
            base_paths=base_paths,
            base_module_ids=base_module_ids,
            resolved_link_on=resolved_link_on,
            on_miss=on_miss,
            build_dir=build_dir,
        )
    except Exception:
        import shutil

        shutil.rmtree(build_dir, ignore_errors=True)
        raise

    if cache and final_dir is not None:
        write_tally(
            build_dir,
            linked=tally.linked,
            minted=tally.minted,
            skipped=tally.skipped,
            ambiguous=tally.ambiguous,
        )
        commit_build(build_dir, final_dir)
        pack_dir = final_dir
    else:
        pack_dir = build_dir

    return ByodBuildOutcome(
        pack_dir=pack_dir,
        linked=tally.linked,
        minted=tally.minted,
        skipped=tally.skipped,
        ambiguous=tally.ambiguous,
        errors=tally.errors,
    )


# ---------------------------------------------------------------------------
# Internal build runner
# ---------------------------------------------------------------------------


class _Tally(NamedTuple):
    linked: int
    minted: int
    skipped: int
    ambiguous: int
    errors: list[str]


def _run_build(
    *,
    records: list[dict[str, Any]],
    schema: RecordSchema,
    domain: str,
    namespace: str,
    pack_type: str,
    base_paths: list[Path] | None,
    base_module_ids: list[str] | None,
    resolved_link_on: list[str],
    on_miss: str,
    build_dir: Path,
) -> _Tally:
    """Execute the build inside *build_dir* and return tallies."""
    is_augment = pack_type == "overlay" and bool(base_paths)

    builder_cls = _builder_class(domain)
    builder = builder_cls(output_dir=build_dir)

    if is_augment:
        assert base_paths is not None
        builder.set_base_modules(base_paths)
        # Pre-compute valid code systems before the row loop.
        assert builder._base_store is not None
        valid_systems: frozenset[str] | None = builder._base_store.code_systems()
    else:
        # Pure-mint: wire only the normalizer (no base store needed).
        builder._normalizer = _domain_normalizer(domain)
        valid_systems = None

    builder.create_database()

    linked = 0
    minted = 0
    skipped = 0
    ambiguous = 0
    errors: list[str] = []

    # Auto-sequence counter for rows without an id.
    counter = itertools.count()

    for row_index, row in enumerate(records):
        record: ByodRecord = schema.row_to_record(row, normalizer=builder._normalizer)

        # Determine the entity_id seed.
        seed = (
            record.entity_id_seed
            if record.entity_id_seed is not None
            else str(next(counter))
        )
        mint_entity_id = f"{namespace}/{seed}"

        # Guard: minting requires a non-empty name. Raise early so the error
        # message names the row and column rather than surfacing an opaque
        # RuntimeError from the builder internals.
        canonical_name = record.canonical_name
        if canonical_name is None and not resolved_link_on:
            name_cols = schema.names
            col_hint = name_cols[0] if len(name_cols) == 1 else str(name_cols)
            raise ValueError(
                f"record {row_index}: {col_hint!r} is empty — "
                "every record must have a non-empty name"
            )

        # Normalise canonical name for the "name" strategy.
        name_value_norm: str | None = None
        if canonical_name is not None:
            name_value_norm = builder._normalizer.normalize_name(canonical_name)

        # Preserve link_on order; include a key only when it is the "name"
        # sentinel or the record actually carries a value for that code system.
        link_keys: list[str] = [
            s for s in resolved_link_on if s == "name" or s in record.codes
        ]

        # Build the alias names list.
        names: list[dict[str, Any]] = [
            {
                "name_kind": "alias",
                "value": alias,
                "value_norm": builder._normalizer.normalize_name(alias),
                "is_preferred": False,
            }
            for alias in record.aliases
        ]

        # Pass raw record.codes; link_and_add and storage layers normalize independently.
        result = builder.link_and_add(
            codes=record.codes,
            names=names if names else None,
            attrs=record.attrs if record.attrs else None,
            canonical_name=canonical_name,
            entity_type=record.entity_type or domain,
            link_keys=link_keys,
            name_value_norm=name_value_norm,
            valid_systems=valid_systems,
            on_miss=on_miss,
            mint_entity_id=mint_entity_id,
        )

        if result.is_success:
            # Minted entities have entity_id == mint_entity_id; otherwise linked.
            if result.entity_id == mint_entity_id:
                minted += 1
            else:
                linked += 1
        elif result.status == "ambiguous":
            ambiguous += 1
        else:
            # not_found / invalid_key with on_miss="skip"
            skipped += 1

    builder.finalize()

    # Write metadata appropriate to the pack type.
    datapack_id = f"{namespace}-byod"
    if pack_type == "overlay":
        builder.build_overlay_metadata(
            datapack_id=datapack_id,
            source_datasets=[namespace],
            link_keys=resolved_link_on,
            base_module_ids=base_module_ids or [],
            allow_new_entities=True,
        )
    else:
        builder.build_metadata(
            datapack_id=datapack_id,
            source_datasets=[namespace],
            module_id=namespace,
        )

    builder.close()

    return _Tally(
        linked=linked,
        minted=minted,
        skipped=skipped,
        ambiguous=ambiguous,
        errors=errors,
    )
