"""End-to-end tests for CustomFuzzyRetrievalSource via the custom pack pipeline.

All tests build a resolver from two records (the reference repro fixture) and
exercise the full pipeline so ordering and rerank interactions are validated.
"""

from __future__ import annotations

import statistics
import time

import pytest

from resolvekit import Resolver
from resolvekit.core.model import ResolutionStatus

# ---------------------------------------------------------------------------
# Shared fixture
# ---------------------------------------------------------------------------

_RECS = [
    {
        "id": "A2",
        "name": "Riverbend Foundation",
        "aliases": "Riverbend;RBF",
        "code": "RBF",
    },
    {
        "id": "A5",
        "name": "Andean Water Trust",
        "aliases": "AWT;Andean Water",
        "code": "AWT",
    },
]


@pytest.fixture(scope="module")
def resolver() -> Resolver:
    """Build and warm a resolver over the two-record reference pack."""
    return Resolver.from_records(
        _RECS,
        name="name",
        id="id",
        aliases="aliases",
        codes=["code"],
        warm=True,
    )


# ---------------------------------------------------------------------------
# Core correctness tests
# ---------------------------------------------------------------------------


class TestCustomFuzzyRetrieval:
    def test_typo_resolves(self, resolver: Resolver) -> None:
        """Within-token typo 'Watr' must resolve to A5."""
        r = resolver.resolve("Andean Watr Trust")
        assert r.status == ResolutionStatus.RESOLVED, r
        assert r.entity_id == "custom/A5", r
        assert r.confidence is not None and r.confidence >= 0.7, r

    def test_degenerate_inputs_abstain(self, resolver: Resolver) -> None:
        """Degenerate / short tokens must NOT resolve to A2 or A5."""
        for q in ["NA", "#N/A", "--", "x", "ab"]:
            r = resolver.resolve(q)
            assert r.entity_id not in {"custom/A2", "custom/A5"}, (
                f"Query {q!r} should not resolve to a real entity; got {r}"
            )

    def test_code_only_not_displaced(self, resolver: Resolver) -> None:
        """'AWT' resolves via the EXACT_CODE path at ≥ 0.9, not the 0.89 FUZZY cap.

        The fuzzy-skip guard does NOT cover EXACT_CODE evidence, so
        CustomFuzzyRetrievalSource still runs — assert it does NOT displace the
        exact-code match.
        """
        r = resolver.resolve("AWT")
        assert r.status == ResolutionStatus.RESOLVED, r
        assert r.entity_id == "custom/A5", r
        assert r.confidence is not None and r.confidence >= 0.9, (
            f"Expected exact-code confidence ≥ 0.9, got {r.confidence}"
        )

    def test_exact_still_exact(self, resolver: Resolver) -> None:
        """Canonical name resolves via exact path; fuzzy source must not displace it."""
        r = resolver.resolve("Andean Water Trust")
        assert r.status == ResolutionStatus.RESOLVED, r
        assert r.entity_id == "custom/A5", r
        assert r.confidence is not None and r.confidence >= 0.9, r

    def test_new_source_surfaces(self, resolver: Resolver) -> None:
        """'custom_fuzzy_retrieval' must appear in resolve_detailed candidates.

        PipelineResult.candidates is list[Candidate]; each Candidate.sources is
        list[CandidateEvidence] with a source_name field.
        """
        det = resolver.resolve_detailed("Andean Watr Trust")
        assert det.candidates is not None, "resolve_detailed returned no candidates"
        source_names = {ev.source_name for c in det.candidates for ev in c.sources}
        assert "custom_fuzzy_retrieval" in source_names, (
            f"Expected 'custom_fuzzy_retrieval' in sources; saw: {source_names}"
        )

    def test_perf_code_only_residual(self, resolver: Resolver) -> None:
        """'AWT' code-only resolve median latency must be < 5 ms on 2-record pack.

        The generating source runs on code-only queries (not skip-guarded for
        EXACT_CODE).  With a cached name list and RapidFuzz's C++ score_cutoff=70
        the residual brute-force must remain negligible.
        """
        iterations = 500
        times: list[float] = []
        for _ in range(iterations):
            t0 = time.perf_counter()
            resolver.resolve("AWT")
            times.append(time.perf_counter() - t0)

        median_ms = statistics.median(times) * 1000
        # Ceiling is generous (5 ms) — the intent is to catch accidental
        # re-materialization or quadratic behaviour, not micro-benchmark.
        assert median_ms < 5.0, (
            f"Median resolve('AWT') latency {median_ms:.2f} ms exceeded 5 ms ceiling"
        )
