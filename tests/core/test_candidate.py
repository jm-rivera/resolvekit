"""Tests for Candidate and Evidence models."""


class TestCandidateEvidence:
    """Tests for CandidateEvidence model."""

    def test_create_evidence(self):
        from resolvekit.core.model.candidate import CandidateEvidence

        ev = CandidateEvidence(
            entity_id="country/USA",
            source_name="exact_code",
            raw_score=1.0,
            rank=1,
            matched_field="code.iso2",
            matched_value="US",
        )
        assert ev.source_name == "exact_code"
        assert ev.raw_score == 1.0
        assert ev.rank == 1
        assert ev.matched_field == "code.iso2"
        assert ev.matched_value == "US"

    def test_create_evidence_minimal(self):
        from resolvekit.core.model.candidate import CandidateEvidence

        ev = CandidateEvidence(entity_id="country/USA", source_name="fts")
        assert ev.source_name == "fts"
        assert ev.raw_score is None
        assert ev.rank is None


class TestRetrievalSummary:
    """Tests for RetrievalSummary model."""

    def test_create_retrieval_summary(self):
        from resolvekit.core.model.candidate import RetrievalSummary

        rs = RetrievalSummary(
            best_source="exact_code",
            best_rank=1,
            best_raw_score=1.0,
            signals={"exact_hit": 1.0},
        )
        assert rs.best_source == "exact_code"
        assert rs.best_rank == 1
        assert rs.signals["exact_hit"] == 1.0


class TestConstraintOutcome:
    """Tests for ConstraintOutcome model."""

    def test_create_constraint_outcome_passed(self):
        from resolvekit.core.model.candidate import ConstraintOutcome, Severity

        co = ConstraintOutcome(
            constraint_name="type_constraint",
            passed=True,
            severity=Severity.HARD,
        )
        assert co.constraint_name == "type_constraint"
        assert co.passed is True
        assert co.severity == Severity.HARD
        assert co.reason is None

    def test_create_constraint_outcome_failed(self):
        from resolvekit.core.model.candidate import ConstraintOutcome, Severity

        co = ConstraintOutcome(
            constraint_name="temporal_constraint",
            passed=False,
            severity=Severity.SOFT,
            reason="Entity not valid at requested date",
        )
        assert co.passed is False
        assert co.reason == "Entity not valid at requested date"


class TestScoreSummary:
    """Tests for ScoreSummary model."""

    def test_create_score_summary(self):
        from resolvekit.core.model.candidate import ScoreSummary

        ss = ScoreSummary(
            raw_score=0.85,
            calibrated_score=0.92,
        )
        assert ss.raw_score == 0.85
        assert ss.calibrated_score == 0.92


class TestCandidate:
    """Tests for Candidate model."""

    def test_create_candidate_minimal(self):
        from resolvekit.core.model.candidate import (
            Candidate,
            CandidateEvidence,
            RetrievalSummary,
            ScoreSummary,
        )

        c = Candidate(
            entity_id="country/USA",
            sources=[
                CandidateEvidence(
                    entity_id="country/USA", source_name="exact_code", raw_score=1.0
                )
            ],
            retrieval=RetrievalSummary(best_source="exact_code"),
            scores=ScoreSummary(raw_score=0.95, calibrated_score=0.97),
        )
        assert c.entity_id == "country/USA"
        assert len(c.sources) == 1
        assert c.retrieval.best_source == "exact_code"
        assert c.scores.calibrated_score == 0.97
        assert c.features is None
        assert c.constraint_outcomes == []

    def test_candidate_with_multiple_sources(self):
        from resolvekit.core.model.candidate import (
            Candidate,
            CandidateEvidence,
            RetrievalSummary,
            ScoreSummary,
        )

        c = Candidate(
            entity_id="country/USA",
            sources=[
                CandidateEvidence(
                    entity_id="country/USA",
                    source_name="exact_code",
                    raw_score=1.0,
                    rank=1,
                ),
                CandidateEvidence(
                    entity_id="country/USA", source_name="fts", raw_score=0.8, rank=2
                ),
            ],
            retrieval=RetrievalSummary(
                best_source="exact_code",
                best_rank=1,
                best_raw_score=1.0,
            ),
            scores=ScoreSummary(raw_score=0.95, calibrated_score=0.97),
        )
        assert len(c.sources) == 2
