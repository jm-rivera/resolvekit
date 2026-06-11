"""Tests for OrgDecisionPolicy."""


class TestOrgDecisionPolicy:
    """Tests for ambiguity-aware org decision policy."""

    def test_acronym_requires_higher_gap(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
            RetrievalSummary,
            ScoreSummary,
        )
        from resolvekit.packs.org.decision import OrgDecisionPolicy

        policy = OrgDecisionPolicy()
        query = Query(
            raw_text="IDA",
            normalized=NormalizedText(original="IDA", normalized="ida"),
        )

        # Two orgs with same acronym, close scores
        candidates = [
            Candidate(
                entity_id="org/IDA_WorldBank",
                sources=[
                    CandidateEvidence(
                        entity_id="org/IDA_WorldBank",
                        source_name="org_acronym",
                        raw_score=0.88,
                    )
                ],
                retrieval=RetrievalSummary(best_source="org_acronym"),
                scores=ScoreSummary(raw_score=0.85, calibrated_score=0.85),
            ),
            Candidate(
                entity_id="org/IDA_Ireland",
                sources=[
                    CandidateEvidence(
                        entity_id="org/IDA_Ireland",
                        source_name="org_acronym",
                        raw_score=0.87,
                    )
                ],
                retrieval=RetrievalSummary(best_source="org_acronym"),
                scores=ScoreSummary(raw_score=0.84, calibrated_score=0.84),
            ),
        ]

        result = policy.decide(query, ResolutionContext(), candidates, NullTraceSink())

        # Should be AMBIGUOUS due to acronym collision
        assert result.status == ResolutionStatus.AMBIGUOUS

    def test_resolves_with_parent_context(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            ConstraintOutcome,
            ConstraintRole,
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
            RetrievalSummary,
            ScoreSummary,
            Severity,
        )
        from resolvekit.packs.org.decision import OrgDecisionPolicy

        policy = OrgDecisionPolicy()
        query = Query(
            raw_text="IDA",
            normalized=NormalizedText(original="IDA", normalized="ida"),
        )
        context = ResolutionContext(parent_ids=["org/WorldBankGroup"])

        # IDA with parent match should win via tiebreak
        # Gap: 0.88 - 0.80 = 0.08 < required 0.15 → would be ambiguous
        # But parent context tiebreak picks the one with parent match
        candidates = [
            Candidate(
                entity_id="org/IDA_WorldBank",
                sources=[
                    CandidateEvidence(
                        entity_id="org/IDA_WorldBank",
                        source_name="org_acronym",
                        raw_score=0.88,
                    )
                ],
                retrieval=RetrievalSummary(best_source="org_acronym"),
                scores=ScoreSummary(raw_score=0.88, calibrated_score=0.88),
                constraint_outcomes=[
                    ConstraintOutcome(
                        constraint_name="org_parent_constraint",
                        passed=True,
                        severity=Severity.SOFT,
                        role=ConstraintRole.PARENT_SCOPE,
                    )
                ],
            ),
            Candidate(
                entity_id="org/IDA_Ireland",
                sources=[
                    CandidateEvidence(
                        entity_id="org/IDA_Ireland",
                        source_name="org_acronym",
                        raw_score=0.80,
                    )
                ],
                retrieval=RetrievalSummary(best_source="org_acronym"),
                scores=ScoreSummary(raw_score=0.80, calibrated_score=0.80),
                constraint_outcomes=[
                    ConstraintOutcome(
                        constraint_name="org_parent_constraint",
                        passed=False,
                        severity=Severity.SOFT,
                        role=ConstraintRole.PARENT_SCOPE,
                    )
                ],
            ),
        ]

        result = policy.decide(query, context, candidates, NullTraceSink())

        # Should resolve to World Bank IDA due to parent context tiebreak
        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "org/IDA_WorldBank"
        from resolvekit.core.model import ReasonCode

        assert ReasonCode.PARENT_CONTEXT_TIEBREAK in result.reasons

    def test_no_candidates_returns_no_match(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            NormalizedText,
            Query,
            ReasonCode,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.packs.org.decision import OrgDecisionPolicy

        policy = OrgDecisionPolicy()
        query = Query(
            raw_text="Unknown Org",
            normalized=NormalizedText(original="Unknown Org", normalized="unknown org"),
        )

        result = policy.decide(query, ResolutionContext(), [], NullTraceSink())

        assert result.status == ResolutionStatus.NO_MATCH
        assert ReasonCode.NO_CANDIDATES in result.reasons

    def test_below_threshold_returns_no_match(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            NormalizedText,
            Query,
            ReasonCode,
            ResolutionContext,
            ResolutionStatus,
            RetrievalSummary,
            ScoreSummary,
        )
        from resolvekit.packs.org.decision import OrgDecisionPolicy

        policy = OrgDecisionPolicy()
        query = Query(
            raw_text="Some Org",
            normalized=NormalizedText(original="Some Org", normalized="some org"),
        )

        candidates = [
            Candidate(
                entity_id="org/SomeOrg",
                sources=[
                    CandidateEvidence(
                        entity_id="org/SomeOrg",
                        source_name="org_fts",
                        raw_score=0.5,
                    )
                ],
                retrieval=RetrievalSummary(best_source="org_fts"),
                scores=ScoreSummary(
                    raw_score=0.5, calibrated_score=0.5
                ),  # Below threshold
            ),
        ]

        result = policy.decide(query, ResolutionContext(), candidates, NullTraceSink())

        assert result.status == ResolutionStatus.NO_MATCH
        assert ReasonCode.BELOW_CONFIDENCE_THRESHOLD in result.reasons


class TestOrgDecisionGapBoundaries:
    """Characterization: pin exact acronym vs default gap boundaries (B5).

    ``_is_acronym_like`` reads ``query.normalized.original`` (NOT ``.normalized``),
    so acronym queries use ``original="IDA"`` (uppercase) to trigger the 0.15 gap.
    ``context.parent_ids=None`` ensures the parent tiebreak never fires and masks
    the gap behavior being tested.

    Candidate construction follows the existing file's style: CandidateEvidence
    source names determine the resolved reason code (org_acronym → ACRONYM_MATCH,
    org_fts → FTS_MATCH).
    """

    def _make_cand(
        self,
        entity_id: str,
        score: float,
        source_name: str,
    ):  # type: ignore[return]
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            RetrievalSummary,
            ScoreSummary,
        )

        return Candidate(
            entity_id=entity_id,
            sources=[
                CandidateEvidence(
                    entity_id=entity_id,
                    source_name=source_name,
                    raw_score=score,
                )
            ],
            retrieval=RetrievalSummary(best_source=source_name),
            scores=ScoreSummary(raw_score=score, calibrated_score=score),
        )

    def _acronym_query(self):  # type: ignore[return]
        from resolvekit.core.model import NormalizedText, Query

        return Query(
            raw_text="IDA",
            normalized=NormalizedText(original="IDA", normalized="ida"),
        )

    def _non_acronym_query(self):  # type: ignore[return]
        from resolvekit.core.model import NormalizedText, Query

        return Query(
            raw_text="World Bank",
            normalized=NormalizedText(original="World Bank", normalized="world bank"),
        )

    def test_acronym_gap_below_acronym_min_is_ambiguous(self) -> None:
        """Acronym query, gap=0.14 (< ACRONYM_MIN_GAP=0.15) → AMBIGUOUS.

        Sanity check: reason is ACRONYM_MATCH_AMBIGUOUS (not AMBIGUOUS_LOW_GAP),
        confirming the acronym branch was taken.
        """
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            ReasonCode,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.packs.org.decision import OrgDecisionPolicy

        policy = OrgDecisionPolicy()
        # top=0.85, second=0.71, gap=0.14 < 0.15
        candidates = [
            self._make_cand("org/A", 0.85, "org_acronym"),
            self._make_cand("org/B", 0.71, "org_acronym"),
        ]
        result = policy.decide(
            self._acronym_query(),
            ResolutionContext(parent_ids=None),
            candidates,
            NullTraceSink(),
        )

        assert result.status == ResolutionStatus.AMBIGUOUS
        assert ReasonCode.ACRONYM_MATCH_AMBIGUOUS in result.reasons

    def test_acronym_gap_at_acronym_min_resolves(self) -> None:
        """Acronym query, gap=0.15 (== ACRONYM_MIN_GAP, gap < required_gap is False) → RESOLVED.

        Reason is ACRONYM_MATCH because the top candidate's source is org_acronym.
        """
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            ReasonCode,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.packs.org.decision import OrgDecisionPolicy

        policy = OrgDecisionPolicy()
        # top=0.85, second=0.70, gap=0.15 == 0.15 → gap < required_gap is False → RESOLVED
        candidates = [
            self._make_cand("org/A", 0.85, "org_acronym"),
            self._make_cand("org/B", 0.70, "org_acronym"),
        ]
        result = policy.decide(
            self._acronym_query(),
            ResolutionContext(parent_ids=None),
            candidates,
            NullTraceSink(),
        )

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "org/A"
        assert ReasonCode.ACRONYM_MATCH in result.reasons

    def test_non_acronym_gap_at_default_min_resolves(self) -> None:
        """Non-acronym query, gap >= DEFAULT_MIN_GAP (strict < is False) → RESOLVED.

        Uses 0.80/0.70: float subtraction gives 0.10000000000000009 which satisfies
        ``gap < 0.10`` as False → RESOLVED.  Note 0.85 - 0.75 = 0.09999... (float
        rounding) would be AMBIGUOUS; 0.80/0.70 is the float-safe boundary case.
        """
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            ReasonCode,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.packs.org.decision import OrgDecisionPolicy

        policy = OrgDecisionPolicy()
        # top=0.80, second=0.70, float gap=0.10000000000000009 → gap < 0.10 is False → RESOLVED
        candidates = [
            self._make_cand("org/A", 0.80, "org_fts"),
            self._make_cand("org/B", 0.70, "org_fts"),
        ]
        result = policy.decide(
            self._non_acronym_query(),
            ResolutionContext(parent_ids=None),
            candidates,
            NullTraceSink(),
        )

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "org/A"
        assert ReasonCode.FTS_MATCH in result.reasons

    def test_non_acronym_gap_below_default_min_is_ambiguous(self) -> None:
        """Non-acronym query, float gap < DEFAULT_MIN_GAP=0.10 → AMBIGUOUS.

        0.85 - 0.76 = 0.08999... in float, clearly below 0.10.
        """
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            ReasonCode,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.packs.org.decision import OrgDecisionPolicy

        policy = OrgDecisionPolicy()
        # top=0.85, second=0.76, float gap=0.08999... < 0.10 → AMBIGUOUS
        candidates = [
            self._make_cand("org/A", 0.85, "org_fts"),
            self._make_cand("org/B", 0.76, "org_fts"),
        ]
        result = policy.decide(
            self._non_acronym_query(),
            ResolutionContext(parent_ids=None),
            candidates,
            NullTraceSink(),
        )

        assert result.status == ResolutionStatus.AMBIGUOUS
        assert ReasonCode.AMBIGUOUS_LOW_GAP in result.reasons
