"""Core value objects for the benchmark pipeline.

Query — a single benchmark row (``text`` is the query string).
Response — a tool's resolved answer.
Observation — a (query, response, latency_ms) triple.
Status — the four possible response statuses.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Status = Literal["match", "no_match", "ambiguous", "error"]


@dataclass(frozen=True)
class Query:
    """A single benchmark evaluation row.

    `text` is the human-readable query string (column name in Parquet stays `query`).
    `expected_ids` is the authoritative answer set:
      - Empty tuple      → the tool SHOULD abstain (no_match).
      - Single element   → unambiguous match.
      - Multiple elements → ambiguous; any intersection with match_ids counts.
    """

    query_id: str
    text: str
    expected_ids: tuple[str, ...]
    language: str
    entity_type: str
    category: str
    difficulty: str
    capabilities: tuple[str, ...]
    source: str
    notes: str | None


@dataclass(frozen=True)
class Response:
    """Normalized output from an adapter's resolve() call.

    Adapters only emit match / no_match / ambiguous / error. The runner
    derives `wrong_match` post-hoc by comparing `match_ids` to the
    query's `expected_ids`.
    """

    status: Status
    match_ids: tuple[str, ...] = ()
    canonical_name: str | None = None
    confidence: float | None = None
    error: str | None = None


@dataclass(frozen=True)
class Observation:
    """A single measured (query, response, latency_ms) triple."""

    query: Query
    response: Response
    latency_ms: float
