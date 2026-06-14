"""BYOD prep helpers — free functions for standalone and overlay pack preparation.

``prepare_standalone_pack`` and ``prepare_augment_pack`` own the imperative
schema-prep work that does not belong in the Resolver facade.  Both functions
take explicit arguments; the facade methods keep their overloads/signatures and
delegate the prep step here.

``_infer_augment_schema`` is a pure helper that derives ``name_col`` and
``all_codes_raw`` from the augment keyword args. It is intentionally
``_``-prefixed and lives in this ``_``-prefixed module; it is not re-exported
from any ``__all__``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from resolvekit.core.byod.build import ByodBuildOutcome


# ---------------------------------------------------------------------------
# AugmentPrep: thin carrier returned by prepare_augment_pack
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AugmentPrep:
    """Outcome of ``prepare_augment_pack``.

    Attributes:
        outcome: Build outcome (pack_dir, tally counters).
        base_dirs: Ordered base datapack directories for the composed resolver.
        prior_overlay_dirs: Ordered prior-overlay datapack directories, oldest
            first.  Empty for a first-generation augment.  Carried forward so
            ``augment()`` can compose ``[*base_dirs, *prior_overlay_dirs, new_overlay]``
            and preserve all earlier overlays.
        domain: The single base domain resolved from the resolver's loaded modules.
    """

    outcome: ByodBuildOutcome
    base_dirs: list[Path]
    prior_overlay_dirs: list[Path]
    domain: str


# ---------------------------------------------------------------------------
# _infer_augment_schema
# ---------------------------------------------------------------------------


def _infer_augment_schema(
    *,
    link_on: list[str],
    add_aliases: str | list[str] | None,
    add_codes: list[str] | dict[str, str] | None,
) -> tuple[str | list[str], list[str] | None]:
    """Derive ``name_col`` and ``all_codes_raw`` for an augment schema resolution.

    The name column for overlay rows is not the canonical-name column (overlays
    don't carry one); instead it is inferred from ``add_aliases`` or from the
    first non-sentinel entry in ``link_on``.  The code schema merges link_on
    code systems with ``add_codes``.

    Args:
        link_on: Ordered list of systems to try for linking (may include the
            sentinel ``"name"`` meaning "match by normalised canonical name").
        add_aliases: Alias column name(s) to add.  When present, the first
            alias column doubles as the schema's name proxy.
        add_codes: Code columns to add.  ``list`` form → system name equals
            column name; ``dict`` form → ``{system: column}``.

    Returns:
        A 2-tuple ``(name_col, all_codes_raw)`` suitable for passing to
        ``RecordSchema.resolve``.

    Raises:
        ValueError: When ``link_on == ["name"]`` and neither ``add_aliases``
            nor ``add_codes`` is provided — there is no way to identify a
            name-proxy column for the schema.
    """
    # Guard: link_on=["name"] with nothing to infer a name column from.
    if link_on == ["name"] and not add_aliases and not add_codes:
        raise ValueError(
            "link_on=['name'] requires add_aliases or add_codes to identify "
            "which column holds the name value.  Pass add_aliases=['<col>'] "
            "to specify the alias column, or add an explicit code column via "
            "add_codes= so the schema resolver can infer the name role."
        )

    name_col: str | list[str]
    if add_aliases:
        name_cols = [add_aliases] if isinstance(add_aliases, str) else list(add_aliases)
        name_col = name_cols[0] if len(name_cols) == 1 else name_cols
    else:
        non_sentinel = [s for s in link_on if s != "name"]
        if non_sentinel:
            name_col = non_sentinel[0]
        else:
            # link_on=["name"] + add_codes present (guarded above: add_codes must be set).
            assert add_codes, "guarded above: add_codes must be set here"
            first_code = (
                next(iter(add_codes)) if isinstance(add_codes, dict) else add_codes[0]
            )
            name_col = first_code

    # Build the merged code schema: link_on code entries + add_codes.
    code_list: list[str] = [s for s in link_on if s != "name"]
    if add_codes:
        if isinstance(add_codes, dict):
            code_list.extend(add_codes.keys())
        else:
            code_list.extend(add_codes)
    all_codes_raw: list[str] | None = code_list if code_list else None

    return name_col, all_codes_raw


# ---------------------------------------------------------------------------
# prepare_standalone_pack
# ---------------------------------------------------------------------------


def prepare_standalone_pack(
    *,
    data: Any,
    domain: str,
    namespace: str | None,
    name: str | list[str],
    id: str | None,
    aliases: str | list[str] | None,
    codes: list[str] | dict[str, str] | None,
    attrs: list[str] | Literal["rest"] | None,
    entity_type: str | None,
    cache: bool,
) -> ByodBuildOutcome:
    """Build a standalone (base) BYOD pack from user-supplied records.

    Owns the namespace guard, ``read_records``, domain ``KNOWN_CODE_SYSTEMS``
    lookup, ``RecordSchema.resolve``, and ``build_byod_pack`` for
    ``pack_type="base"``.

    Args:
        data: Records in any supported form.
        domain: Domain pack (``"custom"``, ``"geo"``, or ``"org"``).
        namespace: Entity-ID prefix; when ``None``, *domain* is used after
            validation.
        name: Canonical name column name(s).
        id: Column whose values become entity-ID seeds; ``None`` → sequential.
        aliases: Alias column name(s).
        codes: Code columns (list or dict form).
        attrs: Attribute columns or ``"rest"`` to keep all unlisted.
        entity_type: Column name or literal to stamp on all entities.
        cache: Cache the built pack on disk.

    Returns:
        ``ByodBuildOutcome`` with the finished pack directory and tally counters.

    Raises:
        ValueError: If *namespace* (or *domain* when *namespace* is None)
            contains disallowed characters.
    """
    from resolvekit.core.byod.build import build_byod_pack
    from resolvekit.core.byod.intake import (
        RecordSchema,
        read_records,
        validate_namespace,
    )

    # Namespace guard is the first act, before any filesystem work.
    # M1: when namespace is not given, validate the domain string and name
    # the parameter that should carry a valid value in the error message.
    if namespace is not None:
        effective_namespace = validate_namespace(namespace)
    else:
        try:
            effective_namespace = validate_namespace(domain)
        except ValueError:
            raise ValueError(
                f"Invalid domain {domain!r}: must match "
                r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$ (no slashes, dots, or leading dashes). "
                "Pass an explicit namespace= if you want a different entity-ID prefix."
            ) from None

    records = read_records(data)

    # Inference hints for known code systems come from the domain's linker.
    known_systems: frozenset[str] = frozenset()
    if domain == "geo":
        from resolvekit.packs.geo.linker import GeoLinker

        known_systems = GeoLinker.KNOWN_CODE_SYSTEMS
    elif domain == "org":
        from resolvekit.packs.org.linker import OrgLinker

        known_systems = OrgLinker.KNOWN_CODE_SYSTEMS

    schema = RecordSchema.resolve(
        records,
        name=name,
        id=id,
        aliases=aliases,
        codes=codes,
        attrs=attrs,
        entity_type=entity_type,
        known_systems=known_systems,
    )

    return build_byod_pack(
        records=records,
        schema=schema,
        domain=domain,
        namespace=effective_namespace,
        pack_type="base",
        base_paths=None,
        link_on=[],
        on_miss="mint",
        cache=cache,
    )


# ---------------------------------------------------------------------------
# prepare_augment_pack
# ---------------------------------------------------------------------------


def prepare_augment_pack(
    *,
    data: Any,
    link_on: list[str],
    columns: dict[str, str] | None,
    add_codes: list[str] | dict[str, str] | None,
    add_aliases: str | list[str] | None,
    add_attrs: list[str] | Literal["rest"] | None,
    on_miss: Literal["mint", "skip", "error"],
    namespace: str | None,
    cache: bool,
    loaded_modules: dict[str, list[Any]],
    loaded_overlays: list[Any],
    available_systems: frozenset[str],
) -> AugmentPrep:
    """Build an overlay BYOD pack from user-supplied records.

    Owns namespace validation, empty-``link_on`` guard, link_on-vs-code_systems
    validation, single-domain resolution from ``loaded_modules``,
    base-dir/base-identity assembly, ``read_records``, schema inference,
    ``RecordSchema.resolve``, and ``build_byod_pack`` for ``pack_type="overlay"``.

    Args:
        data: Records in any supported BYOD source.
        link_on: Ordered list of systems to try for linking.
        columns: Role/system → column-name override for the record schema.
        add_codes: Code columns to add.
        add_aliases: Alias column name(s) to add.
        add_attrs: Attribute columns to add, or ``"rest"`` for all unlisted.
        on_miss: Behaviour for rows that do not link.
        namespace: Entity-ID prefix for minted rows.
        cache: Cache the overlay pack on disk.
        loaded_modules: Resolver's ``_loaded_modules`` dict
            (``{pack_id: [LoadedDataPack, ...]}``) — source of base dirs and
            identity tuples.
        loaded_overlays: Resolver's ``_loaded_overlays`` list — prior overlay
            packs from earlier ``augment()`` calls.  Their base_path values are
            carried forward into the composed resolver so that chained augments
            compose rather than replace.
        available_systems: Resolver's current code systems (``self.code_systems()``).

    Returns:
        ``AugmentPrep`` carrying the build outcome, base dirs, prior overlay
        dirs, and domain.

    Raises:
        ValueError: If *namespace* contains disallowed characters.
        ValueError: If *link_on* is empty.
        ValueError: If any *link_on* entry is not ``"name"`` and not in
            ``available_systems``.
        ValueError: If *loaded_modules* has zero or more than one domain.
        ValueError: ``_infer_augment_schema`` footgun guard
            (``link_on=["name"]`` with no aliases/codes).
    """
    from resolvekit.core.byod.build import build_byod_pack
    from resolvekit.core.byod.intake import (
        RecordSchema,
        read_records,
        validate_namespace,
    )

    # Validate namespace before any filesystem work.
    if namespace is not None:
        validate_namespace(namespace)

    # Reject empty link_on: each overlaid row must link via some system.
    if not link_on:
        raise ValueError(
            "link_on cannot be empty; use Resolver.from_records to stand up "
            "a standalone pack"
        )

    # Validate every link_on entry against the live code systems.
    invalid = [s for s in link_on if s != "name" and s not in available_systems]
    if invalid:
        raise ValueError(
            f"link_on contains unknown system(s) {invalid!r}. "
            f"Available: {sorted(available_systems)}"
        )

    # Resolve the single base domain.
    loaded_domains = list(loaded_modules.keys())
    if len(loaded_domains) == 0:
        raise ValueError("resolver has no loaded domain modules")
    if len(loaded_domains) > 1:
        raise ValueError(
            f"resolver has multiple domains {loaded_domains!r}; augment requires "
            "a single-domain base — pass a domain-filtered resolver"
        )
    domain = loaded_domains[0]

    effective_namespace = namespace or domain

    # Collect base module dirs and IDs from loaded_modules.
    base_dirs: list[Path] = []
    base_module_ids: list[str] = []
    base_identity: list[tuple[str, str, int, float]] = []
    for _pack_id, modules in loaded_modules.items():
        for m in modules:
            base_dirs.append(m.base_path)
            base_module_ids.append(m.module_id)
            db = m.db_path
            stat = db.stat() if db.exists() else None
            base_identity.append(
                (
                    m.module_id,
                    m.metadata.datapack_id,
                    stat.st_size if stat else 0,
                    stat.st_mtime if stat else 0.0,
                )
            )

    records = read_records(data)

    # Derive name_col and all_codes_raw (may raise ValueError for the footgun case).
    name_col, all_codes_raw = _infer_augment_schema(
        link_on=link_on,
        add_aliases=add_aliases,
        add_codes=add_codes,
    )

    schema = RecordSchema.resolve(
        records,
        name=name_col,
        codes=all_codes_raw,
        aliases=add_aliases,
        attrs=add_attrs,
        columns=columns,
    )

    # Collect prior overlay dirs (oldest first) from the resolver's tracked
    # overlays.  These are passed back to augment() so it can compose
    # [*base_dirs, *prior_overlay_dirs, new_overlay] rather than dropping them.
    # The new overlay declares only TRUE base module ids so
    # _validate_overlay_relationships doesn't treat prior overlays as missing
    # base deps — prior overlays merge by being in datapack_paths, not via
    # base_module_ids declaration.
    prior_overlay_dirs: list[Path] = [m.base_path for m in loaded_overlays]

    outcome = build_byod_pack(
        records=records,
        schema=schema,
        domain=domain,
        namespace=effective_namespace,
        pack_type="overlay",
        base_paths=base_dirs,
        base_module_ids=base_module_ids,
        link_on=link_on,
        on_miss=on_miss,
        cache=cache,
        cache_extra={"base_identity": base_identity},
    )

    return AugmentPrep(
        outcome=outcome,
        base_dirs=base_dirs,
        prior_overlay_dirs=prior_overlay_dirs,
        domain=domain,
    )
