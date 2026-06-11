"""AugmentResult — diagnostics dataclass returned by Resolver.augment."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resolvekit.core.api.resolver import Resolver


@dataclass(frozen=True)
class AugmentResult:
    """Diagnostics from an augment() call, with the composed resolver attached.

    Attributes:
        resolver: New ``Resolver`` composing the base + the built overlay.
        linked: Number of rows successfully linked to a base entity.
        minted: Number of rows that became new entities (``on_miss="mint"``).
        skipped: Number of unlinked rows silently dropped (``on_miss="skip"``).
        ambiguous: Number of rows with >1 base match (always skipped).
        errors: List of error messages for rows that raised (``on_miss="error"``
            is unusual to reach here — those rows raise immediately; this list
            collects any non-fatal diagnostic strings the orchestrator may emit).

    Note:
        When ``augment`` reuses a previously cached overlay (``cache=True`` and
        identical inputs), the tally fields ``linked``, ``minted``, ``skipped``,
        and ``ambiguous`` are read from a ``byod_tally.json`` sidecar persisted
        alongside the pack at build time.  The values are identical to those
        returned by the original fresh build.  Pre-version-2 cached directories
        without a sidecar return zeros; those entries will be rebuilt on the
        next call due to the cache-version bump.
    """

    resolver: Resolver
    linked: int
    minted: int
    skipped: int
    ambiguous: int
    errors: list[str]
