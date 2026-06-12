"""Error types for ResolveKit module loading, linking, and composition."""

from __future__ import annotations

import difflib
from collections.abc import Sequence
from typing import Any

from resolvekit.core.errors_base import ExplainNotAvailableError, ResolverError
from resolvekit.core.model.result import CandidateSummary, ResolutionStatus

__all__ = [
    "ExplainNotAvailableError",
    "ResolverError",
    "UnknownContextKeyError",
]


class DataPackError(Exception):
    """Base exception for all datapack-related errors.

    All datapack modularity errors inherit from this class,
    allowing callers to catch all datapack errors with a single handler.
    """

    pass


class LinkError(DataPackError):
    """Base class for link resolution errors.

    Link errors occur when attempting to resolve overlay rows to base entities.
    """

    pass


class AmbiguousLinkError(LinkError):
    """Multiple base entities match the link key.

    Raised when a link key matches multiple entities and the domain-specific
    tie-breaking rules cannot disambiguate.

    Attributes:
        overlay_row: The overlay row data that caused the ambiguity
        candidates: Tuple of entity_ids that matched
        link_key: The link key that was tried
    """

    def __init__(
        self,
        overlay_row: dict[str, Any],
        candidates: tuple[str, ...],
        link_key: str,
    ) -> None:
        self.overlay_row = overlay_row
        self.candidates = candidates
        self.link_key = link_key
        candidates_str = ", ".join(candidates)
        super().__init__(
            f"ambiguous link for key '{link_key}': "
            f"multiple entities match [{candidates_str}]"
        )


class InvalidKeyError(LinkError):
    """Link key format is invalid or unsupported.

    Raised when a link key value is malformed or the key system
    is not recognized by the domain linker.

    Attributes:
        key: The link key name (e.g., "iso3", "dcid")
        value: The invalid value
    """

    def __init__(self, key: str, value: str, message: str | None = None) -> None:
        self.key = key
        self.value = value
        msg = message or f"invalid link key '{key}' with value '{value}'"
        super().__init__(msg)


class IncompatibleVersionError(DataPackError):
    """Schema versions are incompatible.

    Raised when overlay and base packs have incompatible schema versions
    (major version mismatch).

    Attributes:
        base_version: The base pack's schema version
        overlay_version: The overlay pack's schema version
        field: Which schema field is incompatible (e.g., "entity_schema_version")
    """

    def __init__(
        self,
        base_version: str,
        overlay_version: str,
        field: str,
    ) -> None:
        self.base_version = base_version
        self.overlay_version = overlay_version
        self.field = field
        super().__init__(
            f"incompatible {field}: base has {base_version}, "
            f"overlay has {overlay_version} (major version mismatch)"
        )


class DataPackRuntimeVersionError(DataPackError):
    """DataPack requires a newer resolvekit runtime.

    Raised when ``metadata.min_resolvekit_version`` is set and the installed
    resolvekit version is older than required.

    Attributes:
        required_version: Minimum resolvekit version required by the pack
        installed_version: Currently installed resolvekit version
        module_id: Module that triggered the error
    """

    def __init__(
        self,
        *,
        required_version: str,
        installed_version: str,
        module_id: str,
    ) -> None:
        self.required_version = required_version
        self.installed_version = installed_version
        self.module_id = module_id
        super().__init__(
            f"datapack '{module_id}' requires resolvekit>={required_version}, "
            f"but {installed_version} is installed. "
            f"Upgrade with: pip install 'resolvekit>={required_version}'"
        )


class DataPackNormalizerVersionError(DataPackError):
    """DataPack was built under a different code-normalizer than this runtime expects."""

    def __init__(self, *, expected: str, found: str, module_id: str) -> None:
        self.expected = expected
        self.found = found
        self.module_id = module_id
        super().__init__(
            f"DataPack '{module_id}' was built under code-normalizer version "
            f"'{found}', but this resolvekit runtime expects '{expected}'. Code "
            f"lookups would silently mismatch. Rebuild the pack: for a BYOD/from_records "
            f"pack call from_records()/augment() again (the content-hash cache will "
            f"produce a fresh pack under the current normalizer); for a bundled pack, "
            f"upgrade resolvekit to a matching release."
        )


class IncompatibleFeatureSchemaError(DataPackError):
    """Feature schema versions are incompatible."""

    def __init__(
        self,
        *,
        pack_id: str,
        datapack_version: str,
        extractor_version: str,
    ) -> None:
        self.pack_id = pack_id
        self.datapack_version = datapack_version
        self.extractor_version = extractor_version
        super().__init__(
            f"incompatible feature_schema_version for pack '{pack_id}': "
            f"datapack has {datapack_version}, extractor expects {extractor_version}"
        )


class UnsupportedStoreError(DataPackError):
    """Store type is not implemented.

    Raised when a datapack specifies a store_type that is not supported
    by the current runtime.

    Attributes:
        store_type: The unsupported store type name
    """

    def __init__(self, store_type: str) -> None:
        self.store_type = store_type
        super().__init__(
            f"unsupported store type: '{store_type}'. Supported types: sqlite"
        )


class OverlayConstraintError(DataPackError):
    """Overlay violates its declared constraints."""

    pass


class RegistryError(DataPackError):
    """Pack registry operation failed.

    Raised for registry-related failures such as:
    - Pack ID not found in registry
    - Registry file corrupted
    - Permission errors
    """

    pass


class ModuleRegistryError(RegistryError):
    """Module registry operation failed."""

    pass


class DataModuleNotFoundError(ModuleRegistryError):
    """No installed or registered module was found for the requested module ID."""

    def __init__(self, module_id: str, searched: list[str] | None = None) -> None:
        self.module_id = module_id
        self.searched = searched or []
        locations = ", ".join(self.searched) if self.searched else "none"
        super().__init__(
            f"no module found for '{module_id}'; searched providers: {locations}"
        )


class NoModulesInstalledError(ModuleRegistryError, ResolverError):
    """No resolution modules are installed.

    Raised when the resolver is asked to discover modules but none are
    installed or registered. This typically means no ResolveKit module extra
    or ``resolvekit-*`` module package has been pip-installed.
    """

    def __init__(self) -> None:
        ResolverError.__init__(
            self,
            "no resolution modules installed",
            hint="install at least one data module, e.g.: pip install 'resolvekit[geo]'",
        )


class MissingModuleDependencyError(DataPackError):
    """A datapack composition is missing one or more required modules."""

    def __init__(self, module_id: str, missing_module_ids: list[str]) -> None:
        self.module_id = module_id
        self.missing_module_ids = list(missing_module_ids)
        missing = ", ".join(self.missing_module_ids)
        super().__init__(f"module '{module_id}' requires missing modules: {missing}")


class ModuleConflictError(DataPackError):
    """Loaded base modules for the same domain overlap on entity IDs."""

    def __init__(
        self,
        *,
        domain: str,
        left_module_id: str,
        right_module_id: str,
        overlapping_entity_ids: list[str],
    ) -> None:
        self.domain = domain
        self.left_module_id = left_module_id
        self.right_module_id = right_module_id
        self.overlapping_entity_ids = list(overlapping_entity_ids)
        preview = ", ".join(self.overlapping_entity_ids[:5])
        super().__init__(
            f"conflicting base modules for domain '{domain}': "
            f"'{left_module_id}' overlaps '{right_module_id}' on entity IDs "
            f"[{preview}]"
        )


class DataPackNotAvailableError(DataPackError, ResolverError):
    """Remote data pack is not available locally and auto-download is disabled.

    Raised when a resolver needs a remote module's SQLite data but it hasn't
    been downloaded yet.

    Attributes:
        module_ids: Module IDs that are missing
        total_size_mb: Combined download size in MB
    """

    def __init__(
        self,
        module_ids: list[str],
        total_size_mb: float | None = None,
    ) -> None:
        self.module_ids = list(module_ids)
        self.total_size_mb = total_size_mb

        if len(module_ids) == 1:
            size_str = f" ({total_size_mb:.0f} MB)" if total_size_mb else ""
            modules_str = f"module '{module_ids[0]}'{size_str}"
        else:
            size_str = f" (total: {total_size_mb:.0f} MB)" if total_size_mb else ""
            listing = ", ".join(f"'{m}'" for m in module_ids)
            modules_str = f"modules {listing}{size_str}"

        msg = (
            f"Data for {modules_str} is not available locally.\n"
            "\n"
            "These modules' data is too large to bundle in the PyPI package\n"
            "and must be downloaded separately.\n"
            "\n"
            "To download:\n"
            "    import resolvekit\n"
        )
        if len(module_ids) == 1:
            msg += f'    resolvekit.download("{module_ids[0]}")\n'
        else:
            msg += "    resolvekit.download_all()  # all remote modules\n"
            for mid in module_ids:
                msg += f'    resolvekit.download("{mid}")  # individual\n'
        msg += (
            "\n"
            "To enable auto-download:\n"
            "    resolvekit.configure(auto_download=True)\n"
            "\n"
            "Environment variables:\n"
            "    RESOLVEKIT_AUTO_DOWNLOAD=1    Enable automatic downloads\n"
            "    RESOLVEKIT_CACHE_DIR=/path    Custom cache location\n"
            "    RESOLVEKIT_OFFLINE=1          Never attempt downloads"
        )
        super().__init__(msg)


class CrosswalkError(ResolverError):
    """Raised at apply time when a crosswalk maps values to unknown entity-ids.

    Attributes:
        offenders: The entity-id strings that could not be found in the loaded data.
    """

    def __init__(self, offenders: list[str]) -> None:
        self.offenders = list(offenders)
        preview = ", ".join(repr(o) for o in offenders[:10])
        super().__init__(
            f"crosswalk references {len(offenders)} unknown entity-id(s): [{preview}]",
            hint=(
                "rebuild the crosswalk with strict=False "
                "(Crosswalk.from_dict(..., strict=False) / from_csv(..., strict=False)) "
                "to downgrade these to per-value misses, or regenerate it against the current data"
            ),
        )


class ResolutionError(ResolverError):
    """A resolution attempt did not produce a unique entity.

    Attributes:
        status: The resolution status that triggered the error
        candidates: Candidate summaries (if available)
    """

    def __init__(
        self,
        status: ResolutionStatus,
        candidates: Sequence[CandidateSummary] | None = None,
        message: str | None = None,
        *,
        hint: str | None = None,
    ) -> None:
        self.status = status
        self.candidates = candidates or []
        msg = message or (
            f"resolution failed with status '{status}'; "
            "use resolver.resolve() for full result with candidates and refinement hints"
        )
        super().__init__(msg, hint=hint)


def _single_candidate_type(
    candidates: Sequence[CandidateSummary] | None,
) -> str | None:
    """Return an entity type carried by exactly one candidate, else ``None``.

    Such a type uniquely identifies one candidate, so narrowing to it reduces
    the set to that single entry — the precise condition under which an
    ``entity_types`` filter is a proven fix. Shared by the HTML disambiguation
    hint (``explain.result_html``) and reused for candidate-aware error advice.
    """
    if not candidates:
        return None
    type_counts: dict[str, int] = {}
    for c in candidates:
        if c.entity_type:
            type_counts[c.entity_type] = type_counts.get(c.entity_type, 0) + 1
    return next((t for t, n in type_counts.items() if n == 1), None)


def entity_types_would_disambiguate(
    candidates: Sequence[CandidateSummary] | None,
) -> bool:
    """True when an ``entity_types`` filter could break the *contended* tie.

    The ambiguity is driven by the two highest-ranked, near-tied candidates,
    not the long tail. A type filter only helps when those finalists carry
    different entity types. When they share a type (e.g. ``country/COD`` vs
    ``country/COG`` for ``"Congo"``, both ``geo.country``) the filter provably
    cannot separate them — even if a lower-ranked outlier carries a different
    type — so we report ``False``.

    Candidates are assumed confidence-ordered, which the pipeline guarantees.
    """
    if not candidates or len(candidates) < 2:
        return False
    first, second = candidates[0], candidates[1]
    if first.entity_type is None or second.entity_type is None:
        return False
    return first.entity_type != second.entity_type


def _ambiguous_resolution_hint(
    candidates: Sequence[CandidateSummary] | None,
) -> str:
    """Candidate-aware disambiguation advice for ``AmbiguousResolutionError``.

    Suggests ``entity_types`` only when a single-type filter would actually
    reduce the candidate set (see :func:`entity_types_would_disambiguate`).
    For same-type ambiguity it points callers at the candidate set itself
    instead of steering them to a filter that cannot help.
    """
    if entity_types_would_disambiguate(candidates):
        return (
            "use context={'entity_types': {...}} to keep the matching type, "
            "or inspect .candidates and pass on_ambiguous='best' to take the top match"
        )
    return (
        "the candidates share one entity type, so entity_types cannot separate them; "
        "inspect .candidates and select an entity_id, refine the query text, or pass "
        "on_ambiguous='best' to take the top match"
    )


def _candidate_preview(
    candidates: Sequence[CandidateSummary], *, limit: int = 3
) -> str:
    """Render ``entity_id (conf)`` for the top *limit* candidates."""
    parts: list[str] = []
    for c in candidates[:limit]:
        conf = f" ({c.confidence:.2f})" if c.confidence is not None else ""
        parts.append(f"{c.entity_id}{conf}")
    suffix = ", ..." if len(candidates) > limit else ""
    return ", ".join(parts) + suffix


class AmbiguousResolutionError(ResolutionError):
    """Multiple plausible entities matched the query.

    Attributes:
        candidates: The ambiguous candidate summaries
    """

    def __init__(
        self,
        candidates: Sequence[CandidateSummary] | None = None,
        *,
        hint: str | None = None,
    ) -> None:
        n = len(candidates) if candidates else 0
        if candidates:
            preview = _candidate_preview(candidates)
            message = (
                f"ambiguous resolution: {n} candidates [{preview}]; "
                "see .candidates for the full set"
            )
        else:
            message = f"ambiguous resolution: {n} candidates"
        super().__init__(
            status=ResolutionStatus.AMBIGUOUS,
            candidates=candidates,
            message=message,
            hint=hint or _ambiguous_resolution_hint(candidates),
        )


class GroupNotFoundError(ResolutionError):
    """Raised when a group string in members_of/is_member resolves to no entity."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(
            status=ResolutionStatus.NO_MATCH,
            message=message,
            hint=hint,
        )


class EntityNotFoundError(ResolutionError):
    """Raised when an entity_or_id string in related()/unresolved_relations()
    resolves to no entity."""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(
            status=ResolutionStatus.NO_MATCH,
            message=message,
            hint=hint,
        )


class UnknownDomainError(ValueError, ResolverError):
    """A requested domain is not available in the resolver.

    Attributes:
        unknown: The unknown domain names
        available: The available domain names
    """

    def __init__(self, unknown: list[str], available: list[str]) -> None:
        self.unknown = unknown
        self.available = available
        close_matches = []
        for name in unknown:
            close = difflib.get_close_matches(name, available, n=1, cutoff=0.5)
            if close:
                close_matches.append(f"'{name}' → did you mean '{close[0]}'?")
        hint = (
            "; ".join(close_matches) + f"; available: {sorted(available)}"
            if close_matches
            else f"available: {sorted(available)}"
        )
        unknown_str = ", ".join(f"'{u}'" for u in unknown)
        ResolverError.__init__(
            self,
            f"unknown domain(s): {unknown_str}",
            hint=hint,
        )


class UnknownContextKeyError(ValueError, ResolverError):
    """A context dict contains one or more unrecognised keys.

    Raised when a ``dict`` passed as ``context=`` carries keys that are not
    fields of :class:`~resolvekit.core.model.ResolutionContext`.

    Attributes:
        unknown: The unrecognised key names.
        valid: The full sorted list of valid keys.
    """

    def __init__(self, unknown: list[str], valid: list[str]) -> None:
        self.unknown = unknown
        self.valid = valid
        close_matches = []
        for name in unknown:
            close = difflib.get_close_matches(name, valid, n=1, cutoff=0.5)
            if close:
                close_matches.append(f"'{name}' → did you mean '{close[0]}'?")
        unknown_str = ", ".join(f"'{u}'" for u in unknown)
        hint = (
            "; ".join(close_matches) + f"; valid keys: {valid}"
            if close_matches
            else f"valid keys: {valid}"
        )
        ResolverError.__init__(
            self,
            f"unknown context key(s): {unknown_str}",
            hint=hint,
        )


class UnknownCodeSystemError(ValueError, ResolverError):
    """The requested code system is not available.

    Raised when an entity is found but lacks a code in the requested
    ``to`` target, and by ``Resolver.members_of`` when the requested
    ``as_codes`` is not loaded by any pack.

    Attributes:
        system: The requested code system name.
        available: Code system names available in the relevant scope.
    """

    def __init__(
        self,
        system: str,
        available: list[str] | None = None,
        *,
        hint: str | None = None,
    ) -> None:
        self.system = system
        self.available = available or []
        if hint is None and available:
            suggestions = difflib.get_close_matches(system, available, n=3, cutoff=0.6)
            hint = (
                f"did you mean: {suggestions}; available: {available}"
                if suggestions
                else f"available: {available}"
            )
        ResolverError.__init__(
            self,
            f"code system {system!r} not available",
            hint=hint,
        )


class UnknownOutputError(ValueError, ResolverError):
    """A default_to / to= token is an unknown code system or malformed name grammar.

    Attributes:
        token: The unrecognised token.
        available: Code and pivot names available in the relevant scope.
    """

    def __init__(
        self,
        token: str,
        available: list[str],
        *,
        hint: str | None = None,
    ) -> None:
        self.token = token
        self.available = available
        if hint is None:
            suggestions = difflib.get_close_matches(token, available, n=3, cutoff=0.6)
            hint = (
                f"did you mean: {suggestions}; available: {available}"
                if suggestions
                else f"available: {available}"
            )
        ResolverError.__init__(
            self,
            f"unknown output token {token!r}",
            hint=hint,
        )


class OutputMissingError(ResolverError):
    """A resolved entity (and the whole fallback chain) lacks the requested output.

    Raised at runtime when a scalar resolve() or snap() call exhausts the
    fallback chain with on_missing='raise'.

    Attributes:
        entity_id: The entity that was resolved but lacked the output.
        requested: The output token that was requested (last in chain).
        available_codes: Code systems the entity does carry.
    """

    def __init__(
        self,
        *,
        entity_id: str,
        requested: str,
        available_codes: list[str],
        hint: str | None = None,
    ) -> None:
        self.entity_id = entity_id
        self.requested = requested
        self.available_codes = available_codes
        if hint is None and available_codes:
            hint = f"entity has: {available_codes}"
        ResolverError.__init__(
            self,
            f"entity {entity_id!r} has no output for {requested!r}",
            hint=hint,
        )
