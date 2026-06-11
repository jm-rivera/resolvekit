"""Per-pack Aho-Corasick automaton for entity surface-form detection.

``PackAutomaton`` builds lazily from ``EntityStore.iter_names()``, matches
against the normalized form of free text, and maps normalized-string spans
back to raw-string offsets via ``normalize_aligned``.  SMALL/LARGE tier gating
ensures a country-only request never forces the city (LARGE) automaton resident.

``ahocorasick_rs`` is an optional dependency.  Importing this module always
succeeds; the guard fires only when an automaton is actually built.

Verified against ahocorasick_rs 1.0.3:
  - Constructor:  AhoCorasick(patterns, matchkind=MatchKind.LeftmostLongest)
  - Match method: find_matches_as_indexes(text) -> list[(pattern_index, start, end)]
  - Index semantics: Unicode codepoint indices (confirmed via lib.rs
    get_byte_to_code_point), indexing directly into the normalized Python str.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterator
from typing import Any, NamedTuple, cast

from resolvekit.core.parse.offsets import normalize_aligned
from resolvekit.core.store.interface import EntityStore
from resolvekit.core.util.normalization import NormalizationProfile
from resolvekit.packs.geo.sources._short_input import _SHORT_ALPHA_MAX_LEN
from resolvekit.packs.geo.sources.symspell import (
    _SMALL_ENTITY_TYPE_PREFIXES,
    _is_small_only_entity_types,
)


def _load_ac():  # type: ignore[return]
    """Lazy loader for ahocorasick_rs — raises with install hint if absent."""
    try:
        import ahocorasick_rs
    except ImportError as exc:
        raise ImportError(
            "parse()/parse_bulk() require the 'ahocorasick_rs' package. "
            "Install with: pip install 'resolvekit[parsing]'"
        ) from exc
    return ahocorasick_rs


# Unicode categories whose presence at a span boundary indicates the span
# is glued to a word.  L* = letters, N* = numbers, Pc = connector punct.
def _is_word_char(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return cat[0] in {"L", "N"} or cat == "Pc"


class _RawHit(NamedTuple):
    """One surface-form detection in the raw input.

    Attributes:
        start: Start offset into the raw input string.
        end: End offset (exclusive) into the raw input string.
        surface: ``raw[start:end]`` — the raw text at this span.
        entity_ids: Entity IDs that share this normalized surface form.
        pack_id: The pack this automaton was built from.
        code_shaped: True when every name row contributing to this pattern
            is a code-shaped alias — an all-uppercase ASCII ``alias``
            whose length is ≤ ``_SHORT_ALPHA_MAX_LEN``.  Used by
            ``link_span`` to gate the case-sensitive code channel.
    """

    start: int
    end: int
    surface: str
    entity_ids: list[str]
    pack_id: str
    code_shaped: bool = False


# ---------------------------------------------------------------------------
# Module-level automaton cache
# ---------------------------------------------------------------------------

# cache_key → PackAutomaton. invalidate(store) clears entries for a given
# store so a remote-tier fetch triggers a rebuild.
_AUTOMATON_CACHE: dict[tuple, PackAutomaton] = {}


def build_or_get_automaton(
    *,
    store: EntityStore,
    profile: NormalizationProfile,
    pack_id: str,
    small_or_full: str,
    small_prefixes: frozenset[str] | None,
    data_version_summary: str,
) -> PackAutomaton:
    """Return a cached ``PackAutomaton`` or build and cache a new one.

    The cache key is ``(id(store), data_version_summary, small_or_full)``
    so the same store object reuses the automaton across ``parse()`` calls.
    A store swap (remote-tier fetch) creates a new store object → new
    ``id(store)`` → automatic rebuild.  Call ``invalidate(store)`` to force
    eviction when the store object is reused after a data change.

    Args:
        store: EntityStore to enumerate names from.
        profile: Normalization profile for the pack.
        pack_id: Pack identifier (e.g. ``"geo"``).
        small_or_full: ``"small"`` or ``"full"`` — included in the key.
        small_prefixes: Entity-type prefixes for the SMALL tier, or
            ``None`` for the full build.
        data_version_summary: Opaque version string from the caller (e.g.
            ``Resolver._summary_data_version()``); keyed as-is.

    Returns:
        A built (and cached) :class:`PackAutomaton`.
    """
    key = (id(store), data_version_summary, small_or_full)
    if key not in _AUTOMATON_CACHE:
        _AUTOMATON_CACHE[key] = PackAutomaton(
            store=store,
            profile=profile,
            pack_id=pack_id,
            small_prefixes=small_prefixes,
        )
    return _AUTOMATON_CACHE[key]


def invalidate(store: EntityStore) -> None:
    """Evict all cached automata keyed on *store*.

    Useful when a remote-tier fetch replaces data within the same store
    object without creating a new one.
    """
    evict = [k for k in _AUTOMATON_CACHE if k[0] == id(store)]
    for k in evict:
        del _AUTOMATON_CACHE[k]


# ---------------------------------------------------------------------------
# PackAutomaton
# ---------------------------------------------------------------------------


class PackAutomaton:
    """Lazily-built Aho-Corasick matcher + side-table for one pack (per tier group).

    AC carries no native payload, so a parallel side-table maps
    pattern_index -> list[entity_id]. Built from store.iter_names(); the build is
    cached and reused across parse() calls. SMALL/LARGE gating mirrors SymSpell:
    a country-only request never forces the city (LARGE) automaton resident.

    Args:
        store: Entity data store to enumerate surface forms from.
        profile: Normalization profile for this pack; used both to build
            the pattern set and to normalize query text at match time.
        pack_id: Pack identifier carried through to ``_RawHit.pack_id``.
        small_prefixes: When provided, only entity types starting with one
            of these prefixes are enumerated (SMALL tier).  ``None``
            enumerates all (full build).
    """

    def __init__(
        self,
        *,
        store: EntityStore,
        profile: NormalizationProfile,
        pack_id: str,
        small_prefixes: frozenset[str] | None,
    ) -> None:
        self._store = store
        self._profile = profile
        self._pack_id = pack_id
        self._small_prefixes = small_prefixes
        self._ac: Any | None = None
        self._side_table: list[list[str]] = []  # pattern_index → [entity_id, ...]
        self._code_shaped: list[bool] = []  # pattern_index → code_shaped flag
        self._build()

    def _build(self) -> None:
        """Enumerate names, build side-table, construct the AC automaton."""
        ac_mod = _load_ac()

        # Group by value_norm so the AC pattern set is deduplicated.
        # _code_shaped_flags tracks whether ALL contributing (name_kind, value)
        # rows for a pattern satisfy the code-shaped predicate:
        #   name_kind == "alias" AND value is all-uppercase ASCII alpha AND
        #   1 <= len(value) <= _SHORT_ALPHA_MAX_LEN.
        # A pattern is code_shaped only when every contributing row passes.
        pattern_to_ids: dict[str, list[str]] = {}
        # value_norm → True while every row seen so far is code-shaped.
        _code_shaped_flags: dict[str, bool] = {}

        for value_norm, entity_id, name_kind, value in cast(
            Iterator[tuple[str, str, str, str]],
            self._store.iter_names(
                entity_type_prefixes=self._small_prefixes,
                with_name_meta=True,
            ),
        ):
            pattern_to_ids.setdefault(value_norm, []).append(entity_id)
            row_is_code_shaped = (
                name_kind == "alias"
                and value.isascii()
                and value.isalpha()
                and value == value.upper()
                and 1 <= len(value) <= _SHORT_ALPHA_MAX_LEN
            )
            # AND-fold over rows: one non-code-shaped row taints the pattern.
            # The default True makes the first row's flag equal to its own value.
            _code_shaped_flags[value_norm] = (
                _code_shaped_flags.get(value_norm, True) and row_is_code_shaped
            )

        # Pattern list and parallel side-tables share dict insertion order
        # (pattern_index → entity_ids / code_shaped).
        patterns = list(pattern_to_ids)
        self._side_table = list(pattern_to_ids.values())
        self._code_shaped = [_code_shaped_flags[p] for p in patterns]

        if not patterns:
            self._ac = None
            return

        self._ac = ac_mod.AhoCorasick(
            patterns,
            matchkind=ac_mod.MatchKind.LeftmostLongest,
        )

    @property
    def pattern_count(self) -> int:
        """Number of unique normalized surface patterns in this automaton."""
        return len(self._side_table)

    def find(self, raw: str) -> list[_RawHit]:
        """Detect surface forms in raw text, returning raw-offset hits.

        Normalizes raw with this pack's profile (offset-aligned), runs the
        automaton over the normalized string, maps each match back to raw
        offsets, and applies the Unicode word-boundary filter on the RAW
        text.  Returns hits that pass the boundary check; each carries
        (start, end, surface=raw[start:end], entity_ids).

        Args:
            raw: Free-text input string in its original (un-normalized) form.

        Returns:
            List of :class:`_RawHit` instances ordered by match position.
            Leftmost-longest resolution is applied within this pack by the
            AC engine; cross-pack selection is handled by ``arbitrate_cross_pack``.
        """
        if not raw or self._ac is None:
            return []

        normalized, raw_starts, raw_ends = normalize_aligned(raw, self._profile)
        if not normalized:
            return []

        hits: list[_RawHit] = []
        # ahocorasick_rs returns Unicode codepoint indices (not UTF-8 byte indices);
        # they index directly into the normalized Python str, matching raw_starts/ends.
        # Do not treat as byte offsets.
        for pat_idx, ns, ne in self._ac.find_matches_as_indexes(normalized):
            # ns..ne is a half-open normalized span [ns, ne).
            # raw_starts[ns] = first raw char consumed by normalized char ns.
            # raw_ends[ne-1] = one-past the last raw char consumed by normalized char ne-1.
            start = raw_starts[ns]
            end = raw_ends[ne - 1]

            # Word-boundary filter on RAW text.  Reject spans where the
            # preceding or following character is a letter, digit, or
            # connector punctuation — the match is glued to a larger word.
            if start > 0 and _is_word_char(raw[start - 1]):
                continue
            if end < len(raw) and _is_word_char(raw[end]):
                continue

            entity_ids = self._side_table[pat_idx]
            surface = raw[start:end]
            hits.append(
                _RawHit(
                    start=start,
                    end=end,
                    surface=surface,
                    entity_ids=entity_ids,
                    pack_id=self._pack_id,
                    code_shaped=self._code_shaped[pat_idx],
                )
            )

        return hits


# ---------------------------------------------------------------------------
# Re-export small-tier predicate for callers that need it
# ---------------------------------------------------------------------------

__all__ = [
    "_SMALL_ENTITY_TYPE_PREFIXES",
    "PackAutomaton",
    "_RawHit",
    "_is_small_only_entity_types",
    "build_or_get_automaton",
    "invalidate",
]
