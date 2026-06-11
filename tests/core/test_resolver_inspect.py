"""Tests for Resolver.inspect and the _run_inspection helper."""

import pytest

from resolvekit.core.api import Resolver
from resolvekit.core.engine import CandidateSource, PipelineRunner
from resolvekit.core.engine.decision import ThresholdDecisionPolicy
from resolvekit.core.explain import NullTraceSink
from resolvekit.core.model import (
    CandidateEvidence,
    EntityRecord,
    GenerationContext,
)
from resolvekit.core.model.entity import CodeRecord
from resolvekit.core.model.inspection import InspectionReport, InspectMatch
from resolvekit.core.util import TextNormalizer
from tests.conftest import MockEntityStore

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class MockEntityStoreWithSystems(MockEntityStore):
    """MockEntityStore that also reports code systems, enabling inspect() code-match tests."""

    def code_systems(self) -> frozenset[str]:
        return frozenset(system for system, _ in self._codes)


class FuzzyFTSSource(CandidateSource):
    """Returns near-match candidates regardless of exact text."""

    @property
    def name(self) -> str:
        return "mock_fts"

    def supports(self, domain_pack_id: str) -> bool:
        return True

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        return [
            CandidateEvidence(
                entity_id="country/USA",
                source_name=self.name,
                raw_score=0.82,
                rank=1,
                matched_field="fts",
                matched_value="united states",
            ),
            CandidateEvidence(
                entity_id="country/GBR",
                source_name=self.name,
                raw_score=0.51,
                rank=2,
                matched_field="fts",
                matched_value="united kingdom",
            ),
        ]


def _make_geo_store() -> MockEntityStoreWithSystems:
    """Minimal geo store with USA + GBR."""
    usa = EntityRecord(
        entity_id="country/USA",
        entity_type="geo.country",
        canonical_name="United States",
        canonical_name_norm="united states",
        codes=[
            CodeRecord(system="iso2", value="US", value_norm="us"),
            CodeRecord(system="iso3", value="USA", value_norm="usa"),
        ],
    )
    gbr = EntityRecord(
        entity_id="country/GBR",
        entity_type="geo.country",
        canonical_name="United Kingdom",
        canonical_name_norm="united kingdom",
        codes=[
            CodeRecord(system="iso2", value="GB", value_norm="gb"),
            CodeRecord(system="iso3", value="GBR", value_norm="gbr"),
        ],
    )
    return MockEntityStoreWithSystems(
        entities={"country/USA": usa, "country/GBR": gbr},
        codes={
            ("iso2", "us"): ["country/USA"],
            ("iso3", "usa"): ["country/USA"],
            ("iso2", "gb"): ["country/GBR"],
            ("iso3", "gbr"): ["country/GBR"],
        },
        names={
            "united states": ["country/USA"],
            "united kingdom": ["country/GBR"],
        },
    )


def _make_resolver(store: MockEntityStoreWithSystems | None = None) -> Resolver:
    store = store or _make_geo_store()
    runner = PipelineRunner(
        trace_sink=NullTraceSink(),
        store=store,
        sources=[FuzzyFTSSource()],
        pack_id="geo",
        decision_policy=ThresholdDecisionPolicy(
            confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
        ),
    )
    return Resolver(runner=runner, normalizer=TextNormalizer())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_inspect_returns_report_for_known_query():
    resolver = _make_resolver()
    report = resolver.diagnostics.inspect("United States")

    assert isinstance(report, InspectionReport)
    assert report.query == "United States"
    assert report.normalized != ""


def test_inspect_includes_code_matches():
    resolver = _make_resolver()
    report = resolver.diagnostics.inspect("us")

    entity_ids = [m.entity_id for m in report.exact_code_matches]
    assert "country/USA" in entity_ids


def test_inspect_includes_exact_name_matches():
    resolver = _make_resolver()
    report = resolver.diagnostics.inspect("United States")

    entity_ids = [m.entity_id for m in report.exact_name_matches]
    assert "country/USA" in entity_ids


def test_inspect_code_match_carries_system():
    resolver = _make_resolver()
    report = resolver.diagnostics.inspect("us")

    usa_matches = [m for m in report.exact_code_matches if m.entity_id == "country/USA"]
    assert usa_matches
    fields = {m.matched_field for m in usa_matches if m.matched_field}
    assert any("iso2" in f for f in fields)


def test_inspect_code_match_carries_pack_id():
    """Code matches preserve pack attribution via lookup_code_attributed.

    A single-pack resolver attributes every code hit to its pack id rather
    than reporting None.
    """
    resolver = _make_resolver()
    report = resolver.diagnostics.inspect("us")

    usa_matches = [m for m in report.exact_code_matches if m.entity_id == "country/USA"]
    assert usa_matches
    assert all(m.pack_id == "geo" for m in usa_matches)


def test_inspect_unfiltered_fuzzy_candidates():
    """Fuzzy candidates appear even for queries below the decision threshold."""
    resolver = _make_resolver()
    report = resolver.diagnostics.inspect("Unted Stats")

    # FuzzyFTSSource always returns candidates, so we must see them here
    # even though the pipeline would normally reject them below threshold.
    assert len(report.fuzzy_candidates) > 0


def test_inspect_str_renders_human_text():
    resolver = _make_resolver()
    report = resolver.diagnostics.inspect("US")

    text = str(report)
    assert text
    assert "\n" not in text, "summary must be a single line"
    # Should mention that a match was found
    assert "inspect:" in text


def test_inspect_str_non_empty_for_known_query():
    resolver = _make_resolver()
    report = resolver.diagnostics.inspect("United States")

    text = str(report)
    assert len(text) > 0
    # as_text() and summary both delegate to the same implementation
    assert report.as_text() == text
    assert report.summary == text


def test_inspect_invalid_input_returns_empty_report():
    resolver = _make_resolver()
    report = resolver.diagnostics.inspect("")

    assert isinstance(report, InspectionReport)
    assert report.exact_code_matches == []
    assert report.exact_name_matches == []
    assert report.fuzzy_candidates == []
    assert "no input" in str(report)


def test_inspect_whitespace_only_returns_empty_report():
    resolver = _make_resolver()
    report = resolver.diagnostics.inspect("   ")

    assert report.exact_code_matches == []
    assert report.exact_name_matches == []
    assert report.fuzzy_candidates == []


def test_inspect_match_is_frozen_pydantic_model():
    match = InspectMatch(entity_id="country/USA")
    with pytest.raises(
        Exception
    ):  # frozen=True raises ValidationError or AttributeError
        match.entity_id = "country/GBR"  # type: ignore[misc]


def test_inspect_report_is_frozen_pydantic_model():
    report = InspectionReport(query="test", normalized="test")
    with pytest.raises(Exception):
        report.query = "other"  # type: ignore[misc]


def test_inspect_fuzzy_candidates_capped_at_five():
    """fuzzy_candidates field has max_length=5."""
    resolver = _make_resolver()
    report = resolver.diagnostics.inspect("US")

    assert len(report.fuzzy_candidates) <= 5


def test_inspect_closed_resolver_raises():
    resolver = _make_resolver()
    resolver.close()

    with pytest.raises(RuntimeError, match="closed"):
        resolver.diagnostics.inspect("US")
