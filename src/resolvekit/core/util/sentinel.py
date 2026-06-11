"""Sentinel blocklist for resolver short-circuit.

Inputs that normalize to a known placeholder/junk value (e.g. "unknown",
"n/a", "999") should never resolve to an entity.  They are blocked early,
before the pipeline runs, and return a NO_MATCH / SENTINEL_BLOCKED result.

The default blocklist targets:
- Common placeholder strings ("unknown", "none", "null", "n/a", ...)
- Keyboard-mash / obvious test strings ("qwerty", "test", "foo", ...)
- Pure punctuation / separator sequences ("---", "...", "###", "????")
- Pure-digit patterns that are not valid ISO/OECD codes ("000", "999",
  "00", "9999")

What is explicitly NOT blocked:
- Legitimate 2-3-letter ISO country codes ("US", "DE", "Mali", "Chad")
- Short but real names ("Niue", "Oman", "Iran")
- Any string longer than 20 characters (blocklist is for short junk only)

Matching is performed on the casefold-stripped form so "Unknown",
" unknown ", "UNKNOWN" all hit without extra entries.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Default blocklist — normalized forms (casefold + strip).
# Callers may extend or replace this via ``SentinelBlocklist``.
# ---------------------------------------------------------------------------

_DEFAULT_BLOCKED: frozenset[str] = frozenset(
    {
        # Generic placeholders
        "unknown",
        "none",
        "null",
        "n/a",
        # NOTE: bare "na" is NOT blocked — it is also the ISO 3166-1 alpha-2
        # code for Namibia.  Block the slash form "n/a" only.
        "n.a.",
        "n.a",
        "not applicable",
        "not available",
        "not set",
        "not defined",
        "not specified",
        "undefined",
        "unspecified",
        "unset",
        # Workflow placeholders
        "tbd",
        "tba",
        "tbc",
        "pending",
        "todo",
        "to do",
        # Generic / catch-all values
        "various",
        "other",
        "others",
        "misc",
        "miscellaneous",
        "worldwide",
        "international",
        # Test / dev junk  — multi-word phrases only; bare "foo"/"bar"/"baz"
        # are intentionally omitted: they are too short (≤ 3 chars) and can
        # collide with legitimate ICAO / other short codes (e.g. BAR→Barbados).
        "test",
        "testing",
        "test string",
        "example",
        "sample",
        "placeholder",
        "dummy",
        "foo bar",
        "foobar",
        "lorem ipsum",
        "lorem",
        # Keyboard mash / gibberish
        "qwerty",
        "asdf",
        "asdfghjkl",
        "asdfgh",
        "zxcvbnm",
        "mnbvcxz",
        "lkjhgfdsa",
        "xkcd",
        # Empty-ish punctuation / separator strings
        "---",
        "--",
        "...",
        "..",
        "###",
        "****",
        "????",
        "!!!!",
        "////",
        "----",
        "====",
        "____",
        "~~~~",
    }
)

# Pure-digit strings that should be blocked.
# Ranges chosen to exclude valid ISO numeric codes (001-999) and OECD codes
# while still catching obvious junk: "000", "999", "00", "9999", "0".
# A digit string is blocked when it normalises to one of these exact values.
_DEFAULT_BLOCKED_DIGITS: frozenset[str] = frozenset(
    {
        "0",
        "00",
        "000",
        "0000",
        "9999",
        "999",
        # Note: "999" is a real OECD region code that resolves via oecd:999 —
        # exactly the failure case we want to block.
        # We intentionally do NOT block "001"-"998" because those are valid
        # ISO 3166-1 numeric codes.
    }
)


class SentinelBlocklist:
    """Immutable set of normalized forms that the resolver should never resolve.

    Construct with the defaults::

        blocklist = SentinelBlocklist()

    Extend the defaults::

        blocklist = SentinelBlocklist(extra={"lorem", "ipsum"})

    Replace entirely::

        blocklist = SentinelBlocklist(replace={"only_this"})

    Args:
        extra: Additional normalized forms to block (merged with defaults).
        replace: When given, completely replaces the default set.  ``extra``
            is ignored when ``replace`` is provided.
    """

    def __init__(
        self,
        *,
        extra: frozenset[str] | set[str] | None = None,
        replace: frozenset[str] | set[str] | None = None,
    ) -> None:
        if replace is not None:
            self._blocked = frozenset(t.casefold().strip() for t in replace)
        else:
            base = _DEFAULT_BLOCKED | _DEFAULT_BLOCKED_DIGITS
            if extra:
                base = base | frozenset(t.casefold().strip() for t in extra)
            self._blocked = base

    def is_blocked(self, text: str) -> bool:
        """Return True if *text* normalizes to a blocked sentinel value.

        Matching is case-insensitive and strips leading/trailing whitespace.
        Only strings of 20 characters or fewer (after stripping) are tested —
        longer inputs are never blocked regardless of content.
        """
        stripped = text.strip()
        # Long strings are never sentinels — skip the set lookup.
        if len(stripped) > 20:
            return False
        return stripped.casefold() in self._blocked

    def __contains__(self, item: object) -> bool:
        """Support ``"unknown" in blocklist`` membership syntax."""
        if not isinstance(item, str):
            return False
        return self.is_blocked(item)

    def __repr__(self) -> str:
        return f"SentinelBlocklist(size={len(self._blocked)})"


# Module-level singleton — used by Resolver when no custom blocklist is given.
DEFAULT_BLOCKLIST = SentinelBlocklist()
