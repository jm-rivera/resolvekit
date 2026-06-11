"""Deny-list gate for the parse() hot path.

Loads a curated set of terms that should never resolve to an entity, regardless
of how the automaton matched them.  The list covers two categories:

1. **Multi-language function words / conjunctions** — stopwords like "the", "de",
   "et" that carry no entity meaning in any context.
2. **Common-noun surfaces that collide with foreign-language place aliases** —
   e.g. "island"/"islands" match Iceland's Danish/German/Norwegian alias "Island"
   (ISO3166 country/ISL) at high confidence, even in sentences where no country is
   intended.  The long-term fix is alias-language / name_kind labeling in the data;
   the deny-list is the precision lever until that data exists.

The set is loaded ONCE at module import into a module-level frozenset constant.

Why not ``functools.cache``?  ``@cache`` memoizes per argument — calling
``is_denied("the")`` a million times in a long-running process would accumulate
one entry per distinct surface, growing unbounded.  The frozenset lookup is O(1)
and requires no per-call allocation.

The deny-list runs BEFORE the case channel in ``link_span``.  Casefolded matching
means a term in the list blocks ALL casings, so the list must NEVER contain a term
whose UPPERCASE form is a wanted ISO code or org acronym — see the ``note`` field
in ``deny_list.json`` for the full invariant.
"""

from __future__ import annotations

import importlib.resources
import json

# ---------------------------------------------------------------------------
# Module-level constant — loaded once at import, never mutated.
# ---------------------------------------------------------------------------


def _load_deny_set() -> frozenset[str]:
    data_path = importlib.resources.files("resolvekit").joinpath(
        "_data/parse/deny_list.json"
    )
    raw = json.loads(data_path.read_text(encoding="utf-8"))
    return frozenset(term.casefold() for term in raw["terms"])


_DENY_SET: frozenset[str] = _load_deny_set()


# ---------------------------------------------------------------------------
# Public predicate
# ---------------------------------------------------------------------------


def is_denied(surface: str) -> bool:
    """Return True if *surface* matches a deny-listed stopword.

    Matching is casefolded so ``"The"``, ``"THE"``, and ``"the"`` all match
    the deny-listed term ``"the"``.  Returns False for any surface not in the
    curated list, including legitimate entity names and ISO codes.

    Args:
        surface: Raw span surface from the automaton hit.

    Returns:
        True when the casefolded surface is in the deny set.
    """
    return surface.casefold() in _DENY_SET
