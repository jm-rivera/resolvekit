"""Tests for scorecard data models, builder, and renderers."""

import json

import pytest
from pydantic import ValidationError

from resolvekit.core.explain import (
    CandidateScorecard,
    ConstraintSummary,
    JSONRenderer,
    MarkdownRenderer,
    PipelineTiming,
    Scorecard,
    ScorecardBuilder,
    ScorecardRenderer,
    SourceContribution,
    TextRenderer,
    Verbosity,
    get_renderer,
)
from resolvekit.core.explain.events import EventType, TraceEvent
from resolvekit.core.model import (
    Candidate,
    CandidateEvidence,
    CandidateEvidenceSummary,
    CandidateSummary,
    ConstraintOutcome,
    MatchTier,
    NormalizedText,
    Query,
    ReasonCode,
    RefinementHint,
    ResolutionResult,
    ResolutionStatus,
    RetrievalSummary,
    ScoreSummary,
    Severity,
)


class TestVerbosityEnum:
    """Tests for Verbosity enum."""

    def test_verbosity_values(self):
        assert Verbosity.MINIMAL == "minimal"
        assert Verbosity.STANDARD == "standard"
        assert Verbosity.FULL == "full"

    def test_verbosity_is_str_enum(self):
        # Should be usable as string
        assert str(Verbosity.MINIMAL) == "minimal"
        assert f"{Verbosity.STANDARD}" == "standard"


class TestDataModels:
    """Tests for scorecard data models."""

    def test_source_contribution_frozen(self):
        src = SourceContribution(
            name="exact_name",
            matched_field="name.canonical",
            score=1.0,
            signals={"fuzzy_sim": 0.95},
        )
        assert src.name == "exact_name"
        assert src.matched_field == "name.canonical"
        assert src.score == 1.0
        assert src.signals == {"fuzzy_sim": 0.95}

        # Frozen - should raise on modification
        with pytest.raises(ValidationError):
            src.name = "other"

    def test_constraint_summary_frozen(self):
        con = ConstraintSummary(
            name="geo_type",
            passed=True,
            severity="hard",
        )
        assert con.name == "geo_type"
        assert con.passed is True
        assert con.severity == "hard"

        with pytest.raises(ValidationError):
            con.passed = False

    def test_candidate_scorecard_frozen(self):
        card = CandidateScorecard(
            entity_id="country/USA",
            confidence=0.985,
            rank=1,
            sources=[SourceContribution(name="exact", score=1.0)],
            constraints=[ConstraintSummary(name="type", passed=True)],
            key_features={"exact_hit": True},
        )
        assert card.entity_id == "country/USA"
        assert card.confidence == 0.985
        assert card.rank == 1

    def test_pipeline_timing_frozen(self):
        timing = PipelineTiming(
            generation_ms=10.5,
            constraints_ms=5.2,
            total_ms=25.0,
        )
        assert timing.generation_ms == 10.5
        assert timing.total_ms == 25.0

    def test_scorecard_frozen(self):
        scorecard = Scorecard(
            query_text="United States",
            normalized_text="united states",
            status=ResolutionStatus.RESOLVED,
            entity_id="country/USA",
            confidence=0.985,
            match_tier=MatchTier.EXACT_NAME,
            reasons=[ReasonCode.EXACT_NAME_MATCH],
            refinement_hints=[RefinementHint.COUNTRY],
        )
        assert scorecard.query_text == "United States"
        assert scorecard.status == ResolutionStatus.RESOLVED
        assert scorecard.entity_id == "country/USA"
        assert scorecard.match_tier == MatchTier.EXACT_NAME
        assert scorecard.refinement_hints == [RefinementHint.COUNTRY]


class TestScorecardBuilder:
    """Tests for ScorecardBuilder."""

    def _make_query(self, text: str = "United States") -> Query:
        """Create a test query."""
        return Query(
            raw_text=text,
            normalized=NormalizedText(original=text, normalized=text.lower()),
        )

    def _make_resolved_result(
        self,
        entity_id: str = "country/USA",
        confidence: float = 0.985,
    ) -> ResolutionResult:
        """Create a resolved result."""
        return ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            entity_id=entity_id,
            confidence=confidence,
            pack_id="geo",
            match_tier=MatchTier.EXACT_NAME,
            reasons=[ReasonCode.EXACT_NAME_MATCH],
            refinement_hints=[RefinementHint.COUNTRY],
            candidates=[
                CandidateSummary(
                    entity_id=entity_id,
                    confidence=confidence,
                    match_tier=MatchTier.EXACT_NAME,
                    top_evidence=[
                        CandidateEvidenceSummary(
                            source_name="geo_exact_name",
                            matched_field="name.canonical",
                        )
                    ],
                    key_features={"exact_name_hit": True, "fts_bm25_norm": 0.892},
                ),
                CandidateSummary(
                    entity_id="country/US-ALT",
                    confidence=0.45,
                ),
            ],
        )

    def _make_no_match_result(self) -> ResolutionResult:
        """Create a no-match result."""
        return ResolutionResult(
            status=ResolutionStatus.NO_MATCH,
            reasons=[ReasonCode.NO_CANDIDATES],
        )

    def test_build_minimal_verbosity(self):
        builder = ScorecardBuilder(verbosity=Verbosity.MINIMAL)
        query = self._make_query()
        result = self._make_resolved_result()

        scorecard = builder.build(query, result)

        # MINIMAL should have basic info
        assert scorecard.query_text == "United States"
        assert scorecard.status == ResolutionStatus.RESOLVED
        assert scorecard.entity_id == "country/USA"
        assert scorecard.confidence == 0.985
        assert scorecard.match_tier == MatchTier.EXACT_NAME
        assert scorecard.refinement_hints == [RefinementHint.COUNTRY]

        # MINIMAL should NOT have alternatives
        assert scorecard.alternatives == []

        # Should have winner (even at minimal)
        assert scorecard.winner is not None
        assert scorecard.winner.entity_id == "country/USA"

    def test_build_standard_verbosity(self):
        builder = ScorecardBuilder(verbosity=Verbosity.STANDARD)
        query = self._make_query()
        result = self._make_resolved_result()

        scorecard = builder.build(query, result)

        # STANDARD should have alternatives
        assert len(scorecard.alternatives) >= 1
        assert scorecard.alternatives[0].entity_id == "country/US-ALT"

        # Should have sources in winner
        assert scorecard.winner is not None
        assert len(scorecard.winner.sources) >= 1
        assert scorecard.winner.sources[0].name == "geo_exact_name"
        assert scorecard.pack_id == "geo"

        # Should have key features
        assert scorecard.winner.key_features.get("exact_name_hit") is True

    def test_build_full_verbosity_with_trace(self):
        builder = ScorecardBuilder(verbosity=Verbosity.FULL)
        query = self._make_query()
        result = self._make_resolved_result()

        trace_events = [
            TraceEvent(
                event_type=EventType.QUERY_NORMALIZED,
                data={"normalized": "united states"},
            ),
            TraceEvent(
                event_type=EventType.CANDIDATES_GENERATED,
                source="geo_exact_name",
                data={"count": 1},
            ),
        ]

        scorecard = builder.build(query, result, trace_events=trace_events)

        # FULL should have trace events
        assert len(scorecard.trace_events) == 2
        assert scorecard.trace_events[0]["event_type"] == "query_normalized"
        assert scorecard.trace_events[1]["source"] == "geo_exact_name"

        # FULL should have timing (even if empty)
        assert scorecard.timing is not None

    def test_build_full_verbosity_with_decision_before_scoring(self):
        """Regression: concurrent sources can interleave so DECIDED appears
        microseconds before the scoring/features events used as its reference.
        Previously this produced a tiny negative `decision_ms` that violated
        PipelineTiming's ge=0 validator."""
        from datetime import datetime, timedelta

        builder = ScorecardBuilder(verbosity=Verbosity.FULL)
        query = self._make_query()
        result = self._make_resolved_result()

        base = datetime(2026, 4, 23, 12, 0, 0)
        trace_events = [
            TraceEvent(
                event_type=EventType.CANDIDATES_GENERATED,
                source="geo_exact_name",
                data={"count": 1},
                timestamp=base,
            ),
            # DECIDED arrives a few microseconds *before* SCORED — the bug case.
            TraceEvent(
                event_type=EventType.DECIDED,
                data={},
                timestamp=base + timedelta(microseconds=500),
            ),
            TraceEvent(
                event_type=EventType.SCORED,
                data={},
                timestamp=base + timedelta(microseconds=1000),
            ),
        ]

        scorecard = builder.build(query, result, trace_events=trace_events)

        assert scorecard.timing is not None
        assert scorecard.timing.decision_ms == 0.0

    def test_build_with_full_candidates(self):
        """Test builder with full Candidate objects for detailed info."""
        builder = ScorecardBuilder(verbosity=Verbosity.STANDARD)
        query = self._make_query()
        result = self._make_resolved_result()

        # Create full candidate with detailed info
        full_candidate = Candidate(
            entity_id="country/USA",
            sources=[
                CandidateEvidence(
                    entity_id="country/USA",
                    source_name="geo_exact_name",
                    raw_score=1.0,
                    matched_field="name.canonical",
                    matched_value="United States",
                    signals={"exact_match": 1.0},
                ),
                CandidateEvidence(
                    entity_id="country/USA",
                    source_name="geo_fts",
                    raw_score=0.892,
                    matched_field="name.all",
                ),
            ],
            retrieval=RetrievalSummary(best_source="geo_exact_name", best_rank=1),
            scores=ScoreSummary(raw_score=5.2, calibrated_score=0.985),
            constraint_outcomes=[
                ConstraintOutcome(
                    constraint_name="geo_type",
                    passed=True,
                    severity=Severity.HARD,
                ),
                ConstraintOutcome(
                    constraint_name="geo_containment",
                    passed=True,
                    severity=Severity.SOFT,
                ),
            ],
        )

        scorecard = builder.build(query, result, candidates=[full_candidate])

        # Should have detailed source info from full candidate
        assert scorecard.winner is not None
        assert len(scorecard.winner.sources) == 2
        assert scorecard.winner.sources[0].score == 1.0
        assert scorecard.winner.sources[0].signals == {"exact_match": 1.0}

        # Should have constraints
        assert len(scorecard.winner.constraints) == 2
        assert scorecard.winner.constraints[0].name == "geo_type"
        assert scorecard.winner.constraints[0].passed is True

    def test_build_no_match(self):
        builder = ScorecardBuilder(verbosity=Verbosity.STANDARD)
        query = self._make_query("XYZ Not Found")
        result = self._make_no_match_result()

        scorecard = builder.build(query, result)

        assert scorecard.status == ResolutionStatus.NO_MATCH
        assert scorecard.entity_id is None
        assert scorecard.winner is None
        assert ReasonCode.NO_CANDIDATES in scorecard.reasons

    def test_max_alternatives_limit(self):
        builder = ScorecardBuilder(verbosity=Verbosity.STANDARD, max_alternatives=2)

        # Create result with many alternatives
        result = ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            entity_id="entity/1",
            confidence=0.9,
            candidates=[
                CandidateSummary(entity_id=f"entity/{i}", confidence=0.9 - i * 0.1)
                for i in range(1, 8)
            ],
        )
        query = self._make_query()

        scorecard = builder.build(query, result)

        # Should limit alternatives
        assert len(scorecard.alternatives) == 2

    def test_extract_key_features_prioritization(self):
        """Test that key features are prioritized by informativeness."""
        builder = ScorecardBuilder(verbosity=Verbosity.STANDARD, max_features=3)

        features = {
            "schema_version": "1.0",  # Should be excluded
            "is_exact_match": True,  # High priority - True bool
            "is_fuzzy": False,  # Low priority - False bool
            "confidence_score": 0.95,  # Medium priority
            "match_count": 0.001,  # Low magnitude
            "none_value": None,  # Should be excluded
        }

        key_features = builder._extract_key_features(features)

        assert "schema_version" not in key_features
        assert "none_value" not in key_features
        assert "is_exact_match" in key_features
        # Should have limited count
        assert len(key_features) <= 3

    def test_pack_id_preserved(self):
        builder = ScorecardBuilder(verbosity=Verbosity.MINIMAL)
        query = self._make_query()
        result = self._make_resolved_result()

        scorecard = builder.build(query, result, pack_id="geo")

        assert scorecard.pack_id == "geo"

    def test_source_contribution_matched_value_from_full_candidate(self):
        """SourceContribution.matched_value is populated from CandidateEvidence."""
        builder = ScorecardBuilder(verbosity=Verbosity.STANDARD)
        query = self._make_query()
        result = self._make_resolved_result()

        full_candidate = Candidate(
            entity_id="country/USA",
            sources=[
                CandidateEvidence(
                    entity_id="country/USA",
                    source_name="geo_fts",
                    raw_score=0.85,
                    matched_field="fts",
                    matched_value="united states",
                    signals={"bm25_raw": -3.2},
                ),
            ],
            retrieval=RetrievalSummary(best_source="geo_fts", best_rank=1),
            scores=ScoreSummary(raw_score=0.85, calibrated_score=0.985),
        )

        scorecard = builder.build(query, result, candidates=[full_candidate])

        assert scorecard.winner is not None
        assert scorecard.winner.sources[0].matched_value == "united states"

    def test_source_contribution_matched_value_from_summary(self):
        """SourceContribution.matched_value falls back to summary.top_evidence."""
        builder = ScorecardBuilder(verbosity=Verbosity.STANDARD)
        query = self._make_query()
        result = ResolutionResult(
            status=ResolutionStatus.RESOLVED,
            entity_id="country/USA",
            confidence=0.985,
            candidates=[
                CandidateSummary(
                    entity_id="country/USA",
                    confidence=0.985,
                    top_evidence=[
                        CandidateEvidenceSummary(
                            source_name="geo_fts",
                            matched_field="fts",
                            matched_value="united states",
                        )
                    ],
                )
            ],
        )

        # No full candidates — forces the summary path
        scorecard = builder.build(query, result)

        assert scorecard.winner is not None
        assert scorecard.winner.sources[0].matched_value == "united states"


class TestTextRenderer:
    """Tests for TextRenderer."""

    def _make_scorecard(self) -> Scorecard:
        return Scorecard(
            query_text="United States",
            normalized_text="united states",
            status=ResolutionStatus.RESOLVED,
            entity_id="country/USA",
            confidence=0.985,
            reasons=[ReasonCode.EXACT_NAME_MATCH],
            primary_source="geo_exact_name",
            winner=CandidateScorecard(
                entity_id="country/USA",
                confidence=0.985,
                rank=1,
                sources=[
                    SourceContribution(
                        name="geo_exact_name",
                        matched_field="name.canonical",
                        score=1.0,
                    )
                ],
                key_features={"exact_name_hit": True, "fts_bm25_norm": 0.892},
                constraints=[
                    ConstraintSummary(name="geo_type", passed=True),
                ],
            ),
            alternatives=[
                CandidateScorecard(
                    entity_id="country/US-ALT",
                    confidence=0.45,
                    rank=2,
                )
            ],
        )

    def test_render_resolved(self):
        renderer = TextRenderer()
        scorecard = self._make_scorecard()

        output = renderer.render(scorecard)

        assert "Resolution Scorecard" in output
        assert 'Query: "United States"' in output
        assert "Status: RESOLVED" in output
        assert "Entity: country/USA" in output
        assert "Confidence: 98.5%" in output
        assert "exact_name_match" in output

    def test_render_includes_match_details(self):
        renderer = TextRenderer()
        scorecard = self._make_scorecard()

        output = renderer.render(scorecard)

        assert "Match Details:" in output
        assert "Primary Source: geo_exact_name" in output
        assert "Sources:" in output
        assert "geo_exact_name" in output
        assert "name.canonical" in output
        assert "Key Features:" in output
        assert "exact_name_hit" in output

    def test_render_includes_alternatives(self):
        renderer = TextRenderer()
        scorecard = self._make_scorecard()

        output = renderer.render(scorecard)

        assert "Alternatives (1):" in output
        assert "country/US-ALT" in output
        assert "45.0%" in output

    def test_render_no_match(self):
        renderer = TextRenderer()
        scorecard = Scorecard(
            query_text="XYZ",
            normalized_text="xyz",
            status=ResolutionStatus.NO_MATCH,
            reasons=[ReasonCode.NO_CANDIDATES],
        )

        output = renderer.render(scorecard)

        assert "Status: NO_MATCH" in output
        assert "Entity:" not in output
        assert "Match Details:" not in output

    def test_render_with_constraints(self):
        renderer = TextRenderer()
        scorecard = self._make_scorecard()

        output = renderer.render(scorecard)

        assert "Constraints:" in output
        assert "geo_type: PASS" in output


class TestMarkdownRenderer:
    """Tests for MarkdownRenderer."""

    def _make_scorecard(self) -> Scorecard:
        return Scorecard(
            query_text="United States",
            normalized_text="united states",
            status=ResolutionStatus.RESOLVED,
            entity_id="country/USA",
            confidence=0.985,
            reasons=[ReasonCode.EXACT_NAME_MATCH],
            winner=CandidateScorecard(
                entity_id="country/USA",
                confidence=0.985,
                rank=1,
                sources=[
                    SourceContribution(
                        name="geo_exact_name",
                        matched_field="name.canonical",
                        score=1.0,
                    )
                ],
                key_features={"exact_name_hit": True},
            ),
            alternatives=[
                CandidateScorecard(
                    entity_id="country/US-ALT",
                    confidence=0.45,
                    rank=2,
                )
            ],
        )

    def test_render_markdown_format(self):
        renderer = MarkdownRenderer()
        scorecard = self._make_scorecard()

        output = renderer.render(scorecard)

        # Check markdown headers
        assert "# Resolution Scorecard" in output
        assert "## Match Details" in output
        assert "## Alternatives" in output

    def test_render_markdown_tables(self):
        renderer = MarkdownRenderer()
        scorecard = self._make_scorecard()

        output = renderer.render(scorecard)

        # Check table formatting
        assert "| Rank | Entity | Confidence |" in output
        assert "|------|--------|------------|" in output
        assert "| 2 | `country/US-ALT` | 45.0% |" in output

    def test_render_markdown_code_formatting(self):
        renderer = MarkdownRenderer()
        scorecard = self._make_scorecard()

        output = renderer.render(scorecard)

        # Entity IDs should be in code blocks
        assert "`country/USA`" in output
        assert "`geo_exact_name`" in output


class TestJSONRenderer:
    """Tests for JSONRenderer."""

    def _make_scorecard(self) -> Scorecard:
        return Scorecard(
            query_text="United States",
            normalized_text="united states",
            status=ResolutionStatus.RESOLVED,
            entity_id="country/USA",
            confidence=0.985,
            reasons=[ReasonCode.EXACT_NAME_MATCH],
        )

    def test_render_valid_json(self):
        renderer = JSONRenderer()
        scorecard = self._make_scorecard()

        output = renderer.render(scorecard)

        # Should be valid JSON
        data = json.loads(output)
        assert data["query_text"] == "United States"
        assert data["status"] == "resolved"
        assert data["entity_id"] == "country/USA"

    def test_render_compact_json(self):
        renderer = JSONRenderer(indent=None)
        scorecard = self._make_scorecard()

        output = renderer.render(scorecard)

        # Should be single line (compact)
        assert "\n" not in output

    def test_render_indented_json(self):
        renderer = JSONRenderer(indent=2)
        scorecard = self._make_scorecard()

        output = renderer.render(scorecard)

        # Should be multi-line (formatted)
        assert "\n" in output


class TestGetRenderer:
    """Tests for get_renderer factory."""

    def test_get_text_renderer(self):
        renderer = get_renderer("text")
        assert isinstance(renderer, TextRenderer)

    def test_get_markdown_renderer(self):
        renderer = get_renderer("markdown")
        assert isinstance(renderer, MarkdownRenderer)

        renderer = get_renderer("md")
        assert isinstance(renderer, MarkdownRenderer)

    def test_get_json_renderer(self):
        renderer = get_renderer("json")
        assert isinstance(renderer, JSONRenderer)

    def test_case_insensitive(self):
        assert isinstance(get_renderer("TEXT"), TextRenderer)
        assert isinstance(get_renderer("Markdown"), MarkdownRenderer)
        assert isinstance(get_renderer("JSON"), JSONRenderer)

    def test_unknown_format_raises(self):
        with pytest.raises(ValueError) as exc_info:
            get_renderer("xml")

        assert "Unknown format" in str(exc_info.value)
        assert "xml" in str(exc_info.value)


class TestScorecardRendererProtocol:
    """Test that renderers implement the protocol correctly."""

    def test_all_renderers_implement_protocol(self):
        renderers: list[ScorecardRenderer] = [
            TextRenderer(),
            MarkdownRenderer(),
            JSONRenderer(),
        ]

        scorecard = Scorecard(
            query_text="test",
            normalized_text="test",
            status=ResolutionStatus.NO_MATCH,
        )

        for renderer in renderers:
            output = renderer.render(scorecard)
            assert isinstance(output, str)
            assert len(output) > 0
