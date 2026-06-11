"""Shared SymSpell-based typo-tolerant source implementation.

Provides typo correction using SymSpell dictionary lookup.
The index is built lazily on first use so resolver construction stays fast;
most queries hit exact-code/exact-name/FTS tiers and never need SymSpell.
"""

import logging
import threading
import time
from importlib import import_module
from pathlib import Path
from typing import Any

from resolvekit.core.engine import CandidateSource
from resolvekit.core.explain import emit_candidates_generated
from resolvekit.core.model import (
    CandidateEvidence,
    GenerationContext,
)
from resolvekit.core.store import EntityStore

logger = logging.getLogger(__name__)

# SymSpell scoring constants
SYMSPELL_BASE_SCORE = 0.9
SYMSPELL_DISTANCE_PENALTY = 0.15
SYMSPELL_MIN_SCORE = 0.5


def _load_symspell_class() -> Any | None:
    """Load the optional SymSpell class at runtime."""
    try:
        return import_module("symspellpy").SymSpell
    except ImportError:
        return None


def _load_symspell_verbosity() -> Any | None:
    """Load the optional SymSpell verbosity enum at runtime."""
    try:
        return import_module("symspellpy").Verbosity
    except ImportError:
        return None


class SymSpellSource(CandidateSource):
    """SymSpell-based typo correction source.

    Uses a pre-built dictionary of names for fast edit-distance correction.
    Falls back gracefully if dictionary unavailable or symspellpy not installed.

    The SymSpell index is built **lazily** on the first query that reaches
    this source.  Construction is guarded by a per-instance lock so concurrent
    first queries (if the resolver is shared across threads) never double-build.
    Most resolutions terminate at exact-code/exact-name/FTS tiers and never
    trigger the build at all.

    Configurable parameters:
    - name: Source name for tracing
    - domain: Domain pack ID this source supports
    - dictionary_path: Path to SymSpell dictionary file
    - max_edit_distance: Maximum edit distance for corrections (default: 2)
    - prefix_length: Prefix length for SymSpell index (default: 7)
    - min_query_length: Minimum query length to process (default: 3)
    - matched_field: Field name for evidence (default: "symspell")
    - name_kinds: Set of name kinds to search (default: None = all)

    Subclasses can override:
    - _generate_fallback: Called when SymSpell is unavailable
    """

    def __init__(
        self,
        name: str,
        domain: str,
        dictionary_path: str | None = None,
        max_edit_distance: int = 2,
        prefix_length: int = 7,
        min_query_length: int = 3,
        matched_field: str = "symspell",
        name_kinds: set[str] | None = None,
    ) -> None:
        """Create a SymSpell source.

        The dictionary is NOT loaded here; it is loaded on first use.

        Args:
            name: Unique name for this source
            domain: Domain pack ID this source supports
            dictionary_path: Path to SymSpell dictionary file
            max_edit_distance: Maximum edit distance for corrections
            prefix_length: Prefix length for SymSpell index
            min_query_length: Minimum query length to process
            matched_field: Field name for evidence
            name_kinds: Set of name kinds to search when looking up corrected terms
        """
        self._name = name
        self._domain = domain
        self._dict_path = dictionary_path
        # Additional dictionary paths queued via load_additional_dictionary()
        # before the index has been built.  Drained on first build.
        self._extra_dict_paths: list[str] = []
        self._max_edit = max_edit_distance
        self._prefix_len = prefix_length
        self._min_query_length = min_query_length
        self._matched_field = matched_field
        self._name_kinds = name_kinds
        # _sym_spell is None until the first query that needs it.
        self._sym_spell: Any | None = None
        # Guards the one-time lazy build.
        self._build_lock = threading.Lock()
        # _build_attempted: set True inside the lock once a build attempt starts
        # (success or failure).  Prevents retries; callers that see _sym_spell=None
        # after a failed build degrade gracefully via the None-guard in generate().
        self._build_attempted = False
        # _built: set True inside the lock ONLY after _do_build() (or the
        # share_symspell_from borrow) completes successfully.  This is the flag
        # guarding the lock-free fast-path so no thread ever observes a half-built
        # index.
        self._built = False

    # ------------------------------------------------------------------
    # Lazy build
    # ------------------------------------------------------------------

    def share_symspell_from(self, provider: "SymSpellSource") -> None:
        """Share the SymSpell instance from *provider* instead of building one.

        After this call, ``_ensure_built()`` will trigger *provider*'s lazy
        build and then borrow its ``_sym_spell`` instance.  The two sources
        share one in-memory index (no duplication).

        Raises ``ValueError`` if the index has already been built on this source.
        """
        if self._build_attempted:
            raise ValueError(
                "share_symspell_from() called after the index was already built"
            )
        self._symspell_provider: SymSpellSource | None = provider

    def _ensure_built(self) -> None:
        """Build the SymSpell index if it hasn't been built yet.

        Double-checked locking: cheap lock-free fast-path once the index is
        fully built (``_built=True``).  The flag is set inside the lock ONLY
        after a successful build so no thread ever sees a half-built index.

        Failure handling: if ``_do_build()`` raises, ``_build_attempted`` is
        set True (preventing retries) but ``_built`` stays False.  Callers
        that reach this source after a failed build see ``_sym_spell=None``
        and fall through to the graceful no-index path.

        When a provider is set (via ``share_symspell_from``), the provider
        builds first and this source borrows its instance.
        """
        if self._built:
            return
        with self._build_lock:
            if self._built:
                return
            if self._build_attempted:
                # A previous attempt failed; degrade without retrying.
                return
            self._build_attempted = True
            provider = getattr(self, "_symspell_provider", None)
            if provider is not None:
                # Delegate to the provider; share its live instance.
                provider._ensure_built()
                self._sym_spell = provider._sym_spell
                # Mark built only after the borrow succeeds.
                self._built = True
            else:
                self._do_build()
                # Mark built only after _do_build() returns without raising.
                self._built = True

    def _do_build(self) -> None:
        """Actually construct the SymSpell instance and load all queued dicts."""
        all_paths: list[str] = []
        if self._dict_path:
            all_paths.append(self._dict_path)
        all_paths.extend(self._extra_dict_paths)
        self._extra_dict_paths = []  # consumed

        if not all_paths:
            return

        symspell_class = _load_symspell_class()
        if symspell_class is None:
            return

        t0 = time.perf_counter()
        self._sym_spell = symspell_class(
            max_dictionary_edit_distance=self._max_edit,
            prefix_length=self._prefix_len,
        )
        for raw_path in all_paths:
            p = Path(raw_path)
            if p.exists():
                self._load_dictionary_from_path(p)
        elapsed = time.perf_counter() - t0
        logger.debug(
            "SymSpell index built for '%s': %d paths, %.2fs",
            self._name,
            len(all_paths),
            elapsed,
        )

    def _init_symspell(self) -> None:
        """No-op: kept for any subclasses that call super()._init_symspell()."""

    def _load_dictionary_from_path(self, path: Path) -> None:
        """Load dictionary file, auto-detecting separator.

        Supports:
        - Tab-separated: term<TAB>frequency
        - Space-separated: term frequency (last token is numeric)
        - Single column: term (uses frequency=1)
        """
        sym_spell = self._sym_spell
        if sym_spell is None:
            return

        # Read only first line to detect format (streaming, memory-safe)
        with open(path, encoding="utf-8") as f:
            first_line = f.readline()

        if "\t" in first_line:
            # Tab-separated: term<TAB>frequency
            sym_spell.load_dictionary(
                str(path),
                term_index=0,
                count_index=1,
                separator="\t",
                encoding="utf-8",
            )
        elif self._is_space_delimited_with_count(first_line):
            # Space-separated: term count (last token is numeric)
            # Must use rsplit to handle multi-word terms like "world bank 123"
            self._load_space_delimited_dictionary(path)
        else:
            # Single column dictionary - create entries with default frequency
            with open(path, encoding="utf-8") as f:
                for line in f:
                    term = line.strip()
                    if term:
                        sym_spell.create_dictionary_entry(term, 1)

    def _is_space_delimited_with_count(self, line: str) -> bool:
        """Check if line appears to be space-delimited with numeric count."""
        parts = line.strip().split()
        if len(parts) >= 2:
            try:
                int(parts[-1])
                return True
            except ValueError:
                pass
        return False

    def _load_space_delimited_dictionary(self, path: Path) -> None:
        """Load space-delimited dictionary where last token is frequency."""
        sym_spell = self._sym_spell
        if sym_spell is None:
            return

        with open(path, encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                parts = line.rsplit(maxsplit=1)
                if len(parts) == 2:
                    term, count_str = parts
                    try:
                        count = int(count_str)
                        sym_spell.create_dictionary_entry(term, count)
                    except ValueError:
                        # Not a valid count, treat as single-column
                        sym_spell.create_dictionary_entry(line, 1)
                else:
                    # Single word, no count
                    sym_spell.create_dictionary_entry(line, 1)

    def load_dictionary(self, dict_path: str) -> None:
        """Replace the primary dictionary path.

        If the index has already been built (first query has happened), the
        new dictionary is loaded immediately into the live instance.
        Otherwise the path is queued for the next lazy build.

        Args:
            dict_path: Path to symspell dictionary file
        """
        if self._built and self._sym_spell is not None:
            # Already built — load immediately into the live instance.
            path = Path(dict_path)
            if path.exists():
                self._load_dictionary_from_path(path)
        else:
            # Not yet built — replace the primary path; extra paths stay.
            self._dict_path = dict_path
            # Reset so the next _ensure_built() triggers a fresh build.
            with self._build_lock:
                self._build_attempted = False
                self._built = False
                self._sym_spell = None

    def load_additional_dictionary(self, dict_path: str) -> None:
        """Queue an additional dictionary file for merging.

        If the index has already been built, the new dictionary is loaded
        immediately.  Otherwise the path is queued to be merged during the
        lazy build triggered by the first query.

        Args:
            dict_path: Path to an additional symspell dictionary file
        """
        if self._built and self._sym_spell is not None:
            # Already built — load immediately.
            path = Path(dict_path)
            if path.exists():
                self._load_dictionary_from_path(path)
        else:
            # Queue for lazy build.
            self._extra_dict_paths.append(dict_path)

    @property
    def name(self) -> str:
        return self._name

    def supports(self, domain_pack_id: str) -> bool:
        return domain_pack_id == self._domain

    def spelling_suggestions(
        self, text: str, *, max_edit_distance: int | None = None
    ) -> list[Any]:
        """Return SymSpell suggestions for *text*, or [] if unavailable.

        Public interface used by the runner to produce ``DID_YOU_MEAN`` hints
        without reaching into the source's internal dictionary.
        Triggers the lazy build on first call.
        """
        self._ensure_built()
        if self._sym_spell is None:
            return []
        verbosity = _load_symspell_verbosity()
        if verbosity is None:
            return []
        distance = self._max_edit if max_edit_distance is None else max_edit_distance
        try:
            return list(
                self._sym_spell.lookup(
                    text, verbosity.CLOSEST, max_edit_distance=distance
                )
            )
        except Exception:
            return []

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        text_norm = ctx.text_norm

        if len(text_norm) < self._min_query_length:
            return []

        deadline = ctx.deadline
        if deadline is not None and time.monotonic() >= deadline:
            return []

        # Trigger the lazy build on first query that reaches this source.
        self._ensure_built()

        # Use SymSpell if available, otherwise try fallback
        if self._sym_spell is not None:
            evidence = self._generate_with_symspell(
                text_norm, ctx.store, ctx.budget, deadline=deadline
            )
        else:
            evidence = self._generate_fallback(text_norm, ctx.store, ctx.budget)
            if not evidence:
                emit_candidates_generated(
                    ctx.trace,
                    self.name,
                    0,
                    entity_ids=[],
                    query=text_norm,
                    reason="no_symspell",
                )
                return []

        emit_candidates_generated(
            ctx.trace,
            self.name,
            len(evidence),
            entity_ids=[e.entity_id for e in evidence],
            query=text_norm,
        )

        return evidence

    def _process_suggestion(
        self,
        *,
        corrected: str,
        edit_distance: int,
        entity_id: str,
        text_norm: str,
        rank: int,
    ) -> list[CandidateEvidence]:
        """Build evidence record(s) for one (corrected term → entity_id) pair.

        Base emits a single record. Subclasses override to stamp tiers / add
        signals / emit synthetic promotion records.
        """
        score = max(
            SYMSPELL_MIN_SCORE,
            SYMSPELL_BASE_SCORE - (edit_distance * SYMSPELL_DISTANCE_PENALTY),
        )
        return [
            CandidateEvidence(
                entity_id=entity_id,
                source_name=self.name,
                raw_score=score,
                rank=rank,
                matched_field=self._matched_field,
                matched_value=corrected,
            )
        ]

    def _suggestions_to_evidence(
        self,
        suggestions: list,
        text_norm: str,
        store: EntityStore,
        budget: int,
        start_rank: int,
        deadline: float | None = None,
    ) -> tuple[list[CandidateEvidence], int]:
        """Convert SymSpell suggestions into candidate evidence.

        Deadline checks are cooperative — they occur between iterations, not
        within a single SymSpell lookup call. A blocking C-level lookup cannot
        be preempted mid-call.

        Returns:
            Tuple of (evidence list, final rank counter).
        """
        evidence: list[CandidateEvidence] = []
        rank = start_rank
        for i, suggestion in enumerate(suggestions):
            if i % 4 == 0 and deadline is not None and time.monotonic() >= deadline:
                break
            corrected = suggestion.term
            edit_distance = suggestion.distance
            if corrected == text_norm:
                continue
            entity_ids = store.lookup_name_exact(corrected, name_kinds=self._name_kinds)
            for entity_id in entity_ids:
                rank += 1
                evidence.extend(
                    self._process_suggestion(
                        corrected=corrected,
                        edit_distance=edit_distance,
                        entity_id=entity_id,
                        text_norm=text_norm,
                        rank=rank,
                    )
                )
                if rank >= budget:
                    break
            if rank >= budget:
                break
        return evidence, rank

    def _generate_with_symspell(
        self,
        text_norm: str,
        store: EntityStore,
        budget: int,
        deadline: float | None = None,
    ) -> list[CandidateEvidence]:
        """Generate candidates using SymSpell typo correction."""
        try:
            verbosity = _load_symspell_verbosity()
            if self._sym_spell is None or verbosity is None:
                return []

            evidence: list[CandidateEvidence] = []

            suggestions = self._sym_spell.lookup(
                text_norm,
                verbosity.CLOSEST,
                max_edit_distance=self._max_edit,
            )

            evidence, rank = self._suggestions_to_evidence(
                suggestions[:budget], text_norm, store, budget, 0, deadline=deadline
            )

            # Fallback: for multi-word queries where lookup() found nothing,
            # try lookup_compound() which corrects each word independently.
            if not evidence and " " in text_norm:
                lookup_compound = getattr(self._sym_spell, "lookup_compound", None)
                if lookup_compound is not None:
                    try:
                        compound_suggestions = lookup_compound(
                            text_norm, max_edit_distance=self._max_edit
                        )
                        compound_ev, rank = self._suggestions_to_evidence(
                            compound_suggestions[:budget],
                            text_norm,
                            store,
                            budget,
                            rank,
                            deadline=deadline,
                        )
                        evidence.extend(compound_ev)
                    except Exception as e:
                        logger.debug(
                            "SymSpell lookup_compound failed for query '%s': %s",
                            text_norm,
                            e,
                        )

            return evidence

        except Exception as e:
            logger.warning(
                "SymSpell lookup failed for query '%s': %s",
                text_norm,
                e,
                exc_info=True,
            )
            return []

    def _generate_fallback(
        self, text_norm: str, store: EntityStore, budget: int
    ) -> list[CandidateEvidence]:
        """Fallback when SymSpell is unavailable.

        Override in subclasses to provide domain-specific fallback behavior.
        Default implementation returns empty list.
        """
        return []
