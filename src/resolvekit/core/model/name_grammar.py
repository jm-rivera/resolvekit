"""Name-grammar primitives for the ``name[:<lang|kind>][:<script>]`` selector.

These helpers are used by both ``dispatch_pivot`` (model layer, per-call ``to=``
and ``EntityRecord.to()``) and ``_resolve_target`` (api layer, compiled
``OutputSpec`` chain).  Keeping them in the model layer avoids a model→api import.

Public symbols
--------------
KNOWN_KINDS             — closed set of name-kind strings
OutputTarget            — one link in an output chain (name variant fields)
parse_name_grammar      — parse a ``name[:<lang|kind>][:<script>]`` token
apply_name              — resolve a name-kind OutputTarget against entity.names
_raise_bad_name_grammar — raise UnknownOutputError for malformed tokens
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from resolvekit.core.errors import UnknownOutputError

if TYPE_CHECKING:
    from resolvekit.core.model.entity import EntityRecord

# ---------------------------------------------------------------------------
# Known name kinds and aliases
# ---------------------------------------------------------------------------

KNOWN_KINDS: frozenset[str] = frozenset(
    {"canonical", "alias", "endonym", "exonym", "acronym"}
)

# ``abbr`` is a data-side synonym for ``acronym``; fold before the kind test.
_KIND_ALIASES: dict[str, str] = {"abbr": "acronym"}

# ---------------------------------------------------------------------------
# OutputTarget dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OutputTarget:
    """One link in an output chain: a computed pivot, code system, or name selector.

    Attributes:
        raw: Original token string, preserved for error messages.
        kind: Routing category — ``"computed"`` (KNOWN_PIVOTS), ``"code"``
            (code-system dict lookup), or ``"name"`` (name-grammar selector).
        name_lang: ISO 639-1 language code when kind is ``"name"``.
        name_kind: One of ``KNOWN_KINDS`` when kind is ``"name"``.
        name_script: ISO 15924 script code (best-effort) when kind is ``"name"``.
    """

    raw: str
    kind: Literal["computed", "code", "name"]
    name_lang: str | None = None
    name_kind: str | None = None
    name_script: str | None = None


# ---------------------------------------------------------------------------
# Name-grammar parser
# ---------------------------------------------------------------------------


def parse_name_grammar(token: str) -> OutputTarget:
    """Parse a ``name[:<lang|kind>][:<script>]`` token into a name OutputTarget.

    Middle-token disambiguation (kind wins): if the middle segment is in
    ``KNOWN_KINDS`` (after folding ``abbr``→``acronym``), it is treated as a
    kind selector; otherwise it is treated as a language code.  The kind-set
    is closed (5 names) and collision-free with the 10 ISO-639-1 langs present
    in the data (en/fr/es/de/ru/ja/it/pt/zh/ar).

    Args:
        token: A raw token starting with ``"name"`` (e.g. ``"name"``,
            ``"name:fr"``, ``"name:acronym"``, ``"name:zh:Hant"``).

    Returns:
        An ``OutputTarget`` with ``kind="name"`` (or ``kind="computed"`` for
        the bare ``"name"`` terminal, which routes via ``dispatch_pivot``).

    Raises:
        UnknownOutputError: When the token starts with ``"name:"`` but the
            grammar is malformed (e.g. empty segment, too many parts).
    """
    if token == "name":
        # Bare ``name`` — computed terminal, never misses.
        return OutputTarget(raw=token, kind="computed")

    if not token.startswith("name:"):
        raise UnknownOutputError(
            token,
            [],
            hint="name grammar: 'name', 'name:<lang|kind>', 'name:<lang|kind>:<script>'",
        )

    parts = token.split(":")
    # parts[0] == "name", parts[1] == middle segment, parts[2] == optional script
    if len(parts) < 2 or parts[1] == "" or len(parts) > 3:
        _raise_bad_name_grammar(token)

    middle = parts[1]
    script = parts[2] if len(parts) == 3 else None
    if script == "":
        _raise_bad_name_grammar(token)

    # Fold ``abbr``→``acronym`` before kind test.
    folded = _KIND_ALIASES.get(middle, middle)
    if folded in KNOWN_KINDS:
        return OutputTarget(
            raw=token, kind="name", name_kind=folded, name_script=script
        )

    # Treat as language selector.
    return OutputTarget(raw=token, kind="name", name_lang=middle, name_script=script)


def _raise_bad_name_grammar(token: str) -> None:
    """Raise ``UnknownOutputError`` for a malformed name-grammar token."""
    raise UnknownOutputError(
        token,
        sorted(KNOWN_KINDS),
        hint=(
            f"malformed name selector {token!r}; "
            f"valid kinds: {sorted(KNOWN_KINDS)}; "
            f"expected 'name', 'name:<lang|kind>', or 'name:<lang|kind>:<script>'"
        ),
    )


# ---------------------------------------------------------------------------
# apply_name
# ---------------------------------------------------------------------------


def apply_name(entity: EntityRecord, target: OutputTarget) -> str | None:
    """Resolve a name-kind OutputTarget against entity.names.

    Filters ``entity.names`` to records matching the target's lang, kind, and
    script (each filter applied only when the corresponding field is set).
    Returns the first survivor by ``(not is_preferred, original_index)`` — i.e.
    preferred names surface first, then declaration order.  Zero-length values
    are filtered out (treated as a miss).

    ``None`` return means the entity has no matching name (a miss); the caller
    treats this as ``_MISS`` for chain-walk purposes or returns ``None`` for
    per-entity absence.

    Args:
        entity: The resolved entity.
        target: A name-kind ``OutputTarget`` (``kind == "name"``).

    Returns:
        The first matching name value, or ``None`` on miss.
    """
    candidates = [
        (i, nr)
        for i, nr in enumerate(entity.names)
        if (
            # Non-empty value check.
            nr.value
            # Lang filter (only when requested).
            and (target.name_lang is None or nr.lang == target.name_lang)
            # Kind filter (only when requested; _KIND_ALIASES already folded in parse).
            and (
                target.name_kind is None
                or _KIND_ALIASES.get(nr.kind, nr.kind) == target.name_kind
            )
            # Script filter (only when requested).
            and (target.name_script is None or nr.script == target.name_script)
        )
    ]
    if not candidates:
        return None
    # Stable sort: preferred first, then declaration order.
    candidates.sort(key=lambda pair: (not pair[1].is_preferred, pair[0]))
    return candidates[0][1].value
