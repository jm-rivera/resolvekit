"""Compiled OutputSpec value object and apply-time runtime.

``OutputSpec`` is the frozen, validated representation of a ``default_to=``
chain plus its miss policy.

Public symbols
--------------
UNSET               — sentinel distinguishing "omitted" from explicit None
OutputTarget        — one link in an output chain (re-exported from name_grammar)
OutputSpec          — compiled chain + on_missing policy
parse_name_grammar  — parse a ``name[:<lang|kind>][:<script>]`` token (re-exported)
compile_output_spec — validate and compile a raw output spec
apply_output        — walk a chain and apply miss policy
apply_name          — resolve a name-kind target against entity.names (re-exported)
_validate_grammar_only — grammar-only validation (used by configure())
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from resolvekit.core.errors import (
    AmbiguousResolutionError,
    OutputMissingError,
    UnknownOutputError,
)
from resolvekit.core.model.entity_attributes import KNOWN_PIVOTS, dispatch_pivot
from resolvekit.core.model.name_grammar import (
    KNOWN_KINDS,  # noqa: F401 — re-export; tests import KNOWN_KINDS from here
    OutputTarget,
    apply_name,
    parse_name_grammar,
)

if TYPE_CHECKING:
    from resolvekit.core.model.entity import EntityRecord
    from resolvekit.core.model.result import ResolutionResult

# ---------------------------------------------------------------------------
# UNSET sentinel
# ---------------------------------------------------------------------------


class _Unset:
    """Singleton sentinel for omitted ``to=`` / ``default_to=`` arguments.

    Identity checks (``x is UNSET``) distinguish "omitted" from explicit None.
    """

    _instance: _Unset | None = None

    def __new__(cls) -> _Unset:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "UNSET"


UNSET: _Unset = _Unset()

# Type alias for the ``to=`` / ``output=`` argument family.
_ToArg = "str | list[str] | type[EntityRecord] | None | _Unset"

# Miss-policy literal shared by OutputSpec and the compile/coerce helpers.
OnMissing = Literal["raise", "null", "auto"]


def _coerce_on_missing(on_missing: str) -> OnMissing:
    """Narrow an arbitrary miss-policy string to the ``OnMissing`` literal.

    Unrecognised values fall back to ``"auto"`` (the safe default policy).
    """
    if on_missing == "raise":
        return "raise"
    if on_missing == "null":
        return "null"
    return "auto"


# ---------------------------------------------------------------------------
# OutputSpec dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OutputSpec:
    """A compiled, validated output chain plus its miss policy.

    Attributes:
        chain: Ordered sequence of targets; first non-miss value wins.
        on_missing: Miss policy — ``"raise"``, ``"null"``, or ``"auto"``
            (``"auto"`` = raise for scalar resolve/snap, null for bulk).
    """

    chain: tuple[OutputTarget, ...]
    on_missing: OnMissing


# ---------------------------------------------------------------------------
# Internal miss sentinel
# ---------------------------------------------------------------------------

_MISS = object()

# ---------------------------------------------------------------------------
# compile_output_spec
# ---------------------------------------------------------------------------


def compile_output_spec(
    output: str | list[str],
    on_missing: str,
    *,
    known_systems: frozenset[str],
) -> OutputSpec:
    """Normalize, parse, classify, and validate a raw output spec.

    ``output`` is normalised to a list (single string → one-element list).
    Each token is classified as ``"computed"``, ``"code"``, or ``"name"``:

    - ``"name"`` or ``"name:..."`` tokens → ``parse_name_grammar``.
    - Token in ``KNOWN_PIVOTS`` → ``kind="computed"``.
    - Otherwise → ``kind="code"``; validated against
      ``known_systems | KNOWN_PIVOTS``; raises ``UnknownOutputError`` with
      did-you-mean on failure.

    Args:
        output: One token or a list of tokens.
        on_missing: Miss policy string (``"raise"``, ``"null"``, or ``"auto"``).
        known_systems: Code systems available in the resolver scope.

    Returns:
        A frozen ``OutputSpec``.

    Raises:
        UnknownOutputError: On bad name grammar or unknown code system.
    """
    tokens: list[str] = [output] if isinstance(output, str) else list(output)
    targets: list[OutputTarget] = []
    valid_codes = known_systems | KNOWN_PIVOTS

    for raw in tokens:
        if raw == "name" or raw.startswith("name:"):
            targets.append(parse_name_grammar(raw))
        elif raw in KNOWN_PIVOTS:
            targets.append(OutputTarget(raw=raw, kind="computed"))
        else:
            # Code-system target — validate.
            if raw not in known_systems:
                available = sorted(valid_codes)
                suggestions = difflib.get_close_matches(raw, available, n=3, cutoff=0.6)
                hint = (
                    f"did you mean: {suggestions}; available: {available}"
                    if suggestions
                    else f"available: {available}"
                )
                raise UnknownOutputError(raw, available, hint=hint)
            targets.append(OutputTarget(raw=raw, kind="code"))

    return OutputSpec(chain=tuple(targets), on_missing=_coerce_on_missing(on_missing))


# ---------------------------------------------------------------------------
# _validate_grammar_only
# ---------------------------------------------------------------------------


def _validate_grammar_only(output: str | list[str] | None) -> None:
    """Grammar-only validation for configure(): None → no-op; str → one token; list → each token.

    Raises ``UnknownOutputError`` on malformed ``name:`` grammar.  Does NOT
    check code systems (deferred to resolver build time).

    Args:
        output: The raw ``default_to=`` value passed to ``configure()``.

    Raises:
        UnknownOutputError: When a ``name:...`` token has invalid grammar.
    """
    if output is None:
        return
    tokens: list[str] = [output] if isinstance(output, str) else list(output)
    for raw in tokens:
        if raw == "name" or raw.startswith("name:"):
            # Will raise UnknownOutputError on bad grammar.
            parse_name_grammar(raw)
        # Non-name tokens: code-system check deferred — accept.


# ---------------------------------------------------------------------------
# _resolve_target
# ---------------------------------------------------------------------------


def _resolve_target(entity: EntityRecord, target: OutputTarget) -> str | object:
    """Dispatch one target; return ``_MISS`` on per-entity absence.

    Three distinct branches — no ``UnknownCodeSystemError`` escapes on the spec
    path (compile-time validation already rejected typo'd code systems; a
    missing code here is a legitimate per-entity miss, not an error):

    - ``"name"``    → ``apply_name``; ``None`` → ``_MISS``.
    - ``"code"``    → direct ``entity.codes_dict.get``; missing → ``_MISS``.
    - ``"computed"``→ ``dispatch_pivot``; returns ``None`` on absence, never raises.

    Args:
        entity: The resolved entity.
        target: One ``OutputTarget`` from the chain.

    Returns:
        The resolved value string, or ``_MISS`` on per-entity absence.
    """
    if target.kind == "name":
        v = apply_name(entity, target)
        return _MISS if v is None else v

    if target.kind == "code":
        v = entity.codes_dict.get(target.raw)
        return _MISS if (v is None or v == "") else v

    # kind == "computed" (KNOWN_PIVOTS, incl. bare "name"): dispatch_pivot
    # returns None on absence for attribute-backed pivots; never raises on the
    # computed path.
    v = dispatch_pivot(entity, target.raw)
    return _MISS if (v is None or v == "") else v


# ---------------------------------------------------------------------------
# apply_output
# ---------------------------------------------------------------------------


def apply_output(
    entity: EntityRecord,
    spec: OutputSpec,
    *,
    scalar: bool,
) -> str | None:
    """Walk the chain; first non-miss target value wins; whole-chain miss → on_missing.

    ``None`` return and ``_MISS`` internal sentinel both advance the chain —
    they differ only for internal clarity (``_MISS`` = per-target absence;
    ``None`` = apply_name found nothing).  Callers see only ``str | None``.

    on_missing resolution:
    - ``"auto"`` + scalar=True  → ``"raise"``
    - ``"auto"`` + scalar=False → ``"null"``
    - explicit ``"raise"`` / ``"null"`` → used as-is

    Args:
        entity: The resolved entity to pivot.
        spec: Compiled output spec (chain + miss policy).
        scalar: True for single-row resolve/snap; False for bulk rows.

    Returns:
        The first chain value that is non-None and non-empty, or ``None``
        when the whole chain misses and the effective policy is ``"null"``.

    Raises:
        OutputMissingError: When the whole chain misses and the effective
            policy is ``"raise"`` (scalar=True with ``"auto"``, or explicit
            ``on_missing="raise"``).
    """
    if spec.on_missing == "auto":
        effective = "raise" if scalar else "null"
    else:
        effective = spec.on_missing

    for target in spec.chain:
        v = _resolve_target(entity, target)
        if v is not _MISS and v is not None:
            return str(v)

    # Whole chain missed.
    if effective == "raise":
        raise OutputMissingError(
            entity_id=entity.entity_id,
            requested=spec.chain[-1].raw,
            available_codes=sorted(entity.codes_dict),
        )
    return None


# ---------------------------------------------------------------------------
# apply_resolved_output
# ---------------------------------------------------------------------------


def apply_resolved_output(
    result: ResolutionResult,
    *,
    to: object = UNSET,
    spec: OutputSpec | None = None,
) -> object:
    """Apply the active output path to a completed resolution result.

    Centralises the three duplicated terminal guard+dispatch blocks that appear
    in ``Resolver.resolve()`` (explicit ``to=`` path and spec path) and
    ``Resolver._resolve_with_spec()``.  No import cycle — ``UNSET`` is defined
    here; ``AmbiguousResolutionError`` comes from ``core.errors``.

    Args:
        result: The completed ``ResolutionResult``.
        to: The explicit ``to=`` value from the caller, or ``UNSET`` when the
            spec path is active.
        spec: Compiled ``OutputSpec`` (used when ``to is UNSET``).

    Returns:
        - ``None`` if the result is not resolved and not ambiguous.
        - The pivot value from ``dispatch_pivot`` when ``to is not UNSET``.
        - The spec output from ``apply_output`` when ``to is UNSET`` and spec
          is set.

    Raises:
        AmbiguousResolutionError: When the result is ambiguous (regardless of
            which path is active).
    """
    if not result.is_resolved or result.entity is None:
        if result.is_ambiguous:
            raise AmbiguousResolutionError(candidates=list(result.candidates))
        return None

    entity = result.entity

    if to is not UNSET:
        return dispatch_pivot(entity, to)  # type: ignore[arg-type]  # ty: ignore[invalid-argument-type]

    assert spec is not None, "spec must be set when to is UNSET"
    return apply_output(entity, spec, scalar=True)
