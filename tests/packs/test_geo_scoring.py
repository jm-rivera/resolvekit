"""Tests for geo scoring and decision."""

from resolvekit.core.model import RetrievalSummary

# The heuristic scorer does not read retrieval, but the base Scorer.score
# signature requires it — use a minimal stub so tests type-check.
_STUB_RETRIEVAL = RetrievalSummary(best_source="test")


class TestGeoScorer:
    def test_heuristic_exact_code(self):
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        features = GeoFeaturesV1(exact_code_hit=True)

        score = scorer.score(features, _STUB_RETRIEVAL)
        assert score >= 0.95

    def test_heuristic_exact_name(self):
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        features = GeoFeaturesV1(exact_name_hit=True)

        score = scorer.score(features, _STUB_RETRIEVAL)
        assert score >= 0.90

    def test_heuristic_fts(self):
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        features = GeoFeaturesV1(fts_bm25_norm=0.8)

        score = scorer.score(features, _STUB_RETRIEVAL)
        assert 0.5 <= score <= 0.9

    def test_heuristic_fuzzy(self):
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        features = GeoFeaturesV1(fuzzy_edit_sim=0.9, fuzzy_token_sim=0.85, query_len=10)

        score = scorer.score(features, _STUB_RETRIEVAL)
        assert 0.5 <= score <= 0.9

    def test_fuzzy_short_query_penalized_when_similarity_low(self):
        # When fuzzy_edit_sim is below the trust threshold, short noisy queries
        # get a length-based discount; long queries do not.
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        short = GeoFeaturesV1(fuzzy_edit_sim=0.6, fuzzy_token_sim=0.6, query_len=3)
        long = GeoFeaturesV1(fuzzy_edit_sim=0.6, fuzzy_token_sim=0.6, query_len=15)

        short_score = scorer.score(short, _STUB_RETRIEVAL)
        long_score = scorer.score(long, _STUB_RETRIEVAL)

        assert short_score < long_score
        assert short_score < 0.75

    def test_fuzzy_high_similarity_trusted_regardless_of_length(self):
        # Strong fuzzy matches (e.g. obvious typos like "Italiy" -> "Italy") must
        # not be crushed by the length penalty: short country names are valid.
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        short = GeoFeaturesV1(fuzzy_edit_sim=0.9, fuzzy_token_sim=0.85, query_len=4)
        long = GeoFeaturesV1(fuzzy_edit_sim=0.9, fuzzy_token_sim=0.85, query_len=15)

        assert scorer.score(short, _STUB_RETRIEVAL) == scorer.score(
            long, _STUB_RETRIEVAL
        )

    def test_fuzzy_cap_allows_high_scores(self):
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        features = GeoFeaturesV1(fuzzy_edit_sim=1.0, fuzzy_token_sim=1.0, query_len=15)

        score = scorer.score(features, _STUB_RETRIEVAL)
        assert 0.85 < score < 0.90

    def test_fuzzy_constraint_penalty(self):
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        no_constraint = GeoFeaturesV1(fuzzy_edit_sim=0.8, query_len=10)
        with_fail = GeoFeaturesV1(
            fuzzy_edit_sim=0.8, query_len=10, containment_pass=False
        )

        assert scorer.score(no_constraint, _STUB_RETRIEVAL) > scorer.score(
            with_fail, _STUB_RETRIEVAL
        )

    def test_fuzzy_constraint_none_no_penalty(self):
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        none_constraint = GeoFeaturesV1(
            fuzzy_edit_sim=0.8, query_len=10, containment_pass=None
        )
        no_constraint = GeoFeaturesV1(fuzzy_edit_sim=0.8, query_len=10)

        assert scorer.score(none_constraint, _STUB_RETRIEVAL) == scorer.score(
            no_constraint, _STUB_RETRIEVAL
        )

    def test_fuzzy_monotonicity(self):
        """Scores are non-decreasing with both edit_sim and query_len."""
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()

        # Non-decreasing with edit_sim (fixed query_len)
        for query_len in [3, 6, 10, 15]:
            prev_score = 0.0
            for edit_sim_x10 in range(5, 11):
                edit_sim = edit_sim_x10 / 10.0
                features = GeoFeaturesV1(fuzzy_edit_sim=edit_sim, query_len=query_len)
                score = scorer.score(features, _STUB_RETRIEVAL)
                assert score >= prev_score, (
                    f"Non-monotonic: query_len={query_len}, "
                    f"edit_sim={edit_sim}, score={score} < prev={prev_score}"
                )
                prev_score = score

        # Non-decreasing with query_len (fixed edit_sim)
        for edit_sim_x10 in [5, 7, 9, 10]:
            edit_sim = edit_sim_x10 / 10.0
            prev_score = 0.0
            for query_len in range(1, 16):
                features = GeoFeaturesV1(fuzzy_edit_sim=edit_sim, query_len=query_len)
                score = scorer.score(features, _STUB_RETRIEVAL)
                assert score >= prev_score, (
                    f"Non-monotonic: edit_sim={edit_sim}, "
                    f"query_len={query_len}, score={score} < prev={prev_score}"
                )
                prev_score = score

    def test_hierarchy_tiebreak_prefers_higher_rank(self):
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        # Country (0.85) vs city (0.4) — same base score via FTS
        country = GeoFeaturesV1(fts_bm25_norm=0.8, hierarchy_rank=0.85)
        city = GeoFeaturesV1(fts_bm25_norm=0.8, hierarchy_rank=0.4)

        country_score = scorer.score(country, _STUB_RETRIEVAL)
        city_score = scorer.score(city, _STUB_RETRIEVAL)

        assert country_score > city_score

    def test_hierarchy_tiebreak_none_no_bonus(self):
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        with_rank = GeoFeaturesV1(fts_bm25_norm=0.8, hierarchy_rank=0.85)
        without_rank = GeoFeaturesV1(fts_bm25_norm=0.8)

        assert scorer.score(with_rank, _STUB_RETRIEVAL) > scorer.score(
            without_rank, _STUB_RETRIEVAL
        )

    def test_calibrate_returns_raw(self):
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        # Calibration currently returns raw score
        calibrated = scorer.calibrate(0.85, None, None)
        assert calibrated == 0.85

    def test_decision_thresholds_heuristic_defaults(self):
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        t = scorer.decision_thresholds
        assert t.confidence_threshold == 0.7
        assert t.min_gap == 0.1
        assert t.exact_code_min_score == 0.9

    def test_decision_thresholds_model_with_thresholds(self):
        from resolvekit.packs.geo.scoring import GeoScorer

        class _MockModel:
            confidence_threshold = 0.6
            min_gap = 0.05
            exact_code_min_score = 0.8

            def predict(self, features):
                return 0.5

            @property
            def model_version(self):
                return "mock"

        scorer = GeoScorer(model=_MockModel())
        t = scorer.decision_thresholds
        assert t.confidence_threshold == 0.6
        assert t.min_gap == 0.05
        assert t.exact_code_min_score == 0.8

    def test_decision_thresholds_model_without_threshold_fields(self):
        from resolvekit.packs.geo.scoring import GeoScorer

        class _MockModel:
            def predict(self, features):
                return 0.5

            @property
            def model_version(self):
                return "mock"

        scorer = GeoScorer(model=_MockModel())
        t = scorer.decision_thresholds
        assert t.confidence_threshold == 0.70
        assert t.min_gap == 0.08
        assert t.exact_code_min_score == 0.75

    def test_decision_thresholds_calibrator(self):
        from resolvekit.packs.geo.scoring import GeoScorer

        class _MockCalibrator:
            def predict(self, raw_score, query_len=None):
                return raw_score

        scorer = GeoScorer(calibrator=_MockCalibrator())
        t = scorer.decision_thresholds
        assert t.confidence_threshold == 0.70
        assert t.min_gap == 0.08
        assert t.exact_code_min_score == 0.75

    def test_prominence_none_is_no_op(self):
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        baseline = GeoFeaturesV1(exact_name_hit=True)
        with_none = GeoFeaturesV1(exact_name_hit=True, candidate_prominence=None)

        assert scorer.score(baseline, _STUB_RETRIEVAL) == scorer.score(
            with_none, _STUB_RETRIEVAL
        )

    def test_prominence_one_vs_zero_gap_is_factor(self):
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.scoring import PROMINENCE_TIEBREAK_FACTOR, GeoScorer

        scorer = GeoScorer()
        high = GeoFeaturesV1(exact_name_hit=True, candidate_prominence=1.0)
        low = GeoFeaturesV1(exact_name_hit=True, candidate_prominence=0.0)

        gap = scorer.score(high, _STUB_RETRIEVAL) - scorer.score(low, _STUB_RETRIEVAL)
        assert abs(gap - PROMINENCE_TIEBREAK_FACTOR) < 1e-9

    def test_prominence_does_not_flip_tier(self):
        # Exact-name + max prominence (0.90 + 0.025 = ~0.925) must not
        # exceed exact-code + min prominence (0.95 - 0.025 = ~0.925).
        # Verify the full case: exact_code+prominence=1.0 beats exact_name+prominence=1.0.
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        exact_code = GeoFeaturesV1(
            exact_code_hit=True, hierarchy_rank=0.85, candidate_prominence=1.0
        )
        exact_name = GeoFeaturesV1(
            exact_name_hit=True, hierarchy_rank=0.85, candidate_prominence=1.0
        )

        assert scorer.score(exact_code, _STUB_RETRIEVAL) > scorer.score(
            exact_name, _STUB_RETRIEVAL
        )

    def test_prominence_fuzzy_can_outrank_weak_exact_name(self):
        # A prominence=1.0 fuzzy match (~0.889 + 0.025 = ~0.914) can outscore
        # a weak exact-name hit (0.90 with no prominence bonus). This is deliberate:
        # a highly prominent fuzzy match should beat a bare exact-name on an obscure entity.
        from resolvekit.packs.geo.features import GeoFeaturesV1
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        # Perfect fuzzy (capped at FUZZY_MAX_SCORE=0.889) + max prominence
        fuzzy_prominent = GeoFeaturesV1(
            fuzzy_edit_sim=1.0,
            fuzzy_token_sim=1.0,
            query_len=15,
            candidate_prominence=1.0,
        )
        # Bare exact-name hit, no prominence
        weak_exact = GeoFeaturesV1(exact_name_hit=True)

        assert scorer.score(fuzzy_prominent, _STUB_RETRIEVAL) > scorer.score(
            weak_exact, _STUB_RETRIEVAL
        )


class TestAcronymAdminBlock:
    def _features(
        self,
        *,
        fuzzy_edit_sim: float | None = None,
        exact_name_hit: bool = False,
        exact_code_hit: bool = False,
        query_is_upper: bool,
        query_len: int,
        hierarchy_rank: float | None,
    ):
        from resolvekit.packs.geo.features import GeoFeaturesV1

        return GeoFeaturesV1(
            fuzzy_edit_sim=fuzzy_edit_sim,
            exact_name_hit=exact_name_hit,
            exact_code_hit=exact_code_hit,
            query_is_upper=query_is_upper,
            query_len=query_len,
            hierarchy_rank=hierarchy_rank,
        )

    def test_fuzzy_admin4_blocked_on_uppercase_acronym(self):
        # "NASA" → geo.admin4 "Nasa" fuzzy match must be suppressed.
        from resolvekit.packs.geo.scoring import FALLBACK_SCORE, GeoScorer

        scorer = GeoScorer()
        features = self._features(
            fuzzy_edit_sim=1.0,
            query_is_upper=True,
            query_len=4,
            hierarchy_rank=0.35,  # geo.admin4
        )
        score = scorer.score(features, _STUB_RETRIEVAL)
        assert score <= FALLBACK_SCORE + 0.01  # clamped, cannot clear 0.7 threshold

    def test_fuzzy_city_blocked_on_uppercase_acronym(self):
        # "SWIFT" → geo.city "Swift" fuzzy match must be suppressed.
        from resolvekit.packs.geo.scoring import FALLBACK_SCORE, GeoScorer

        scorer = GeoScorer()
        features = self._features(
            fuzzy_edit_sim=1.0,
            query_is_upper=True,
            query_len=5,
            hierarchy_rank=0.70,  # geo.city
        )
        score = scorer.score(features, _STUB_RETRIEVAL)
        assert score <= FALLBACK_SCORE + 0.01

    def test_fuzzy_region_blocked_on_uppercase_acronym(self):
        # "FIFA" → fuzzy geo.region IFAD must be suppressed.
        from resolvekit.packs.geo.scoring import FALLBACK_SCORE, GeoScorer

        scorer = GeoScorer()
        features = self._features(
            fuzzy_edit_sim=0.8,
            query_is_upper=True,
            query_len=4,
            hierarchy_rank=0.75,  # geo.region
        )
        score = scorer.score(features, _STUB_RETRIEVAL)
        assert score <= FALLBACK_SCORE + 0.01

    def test_exact_name_region_allowed_on_uppercase_acronym(self):
        # "MENA" → exact_name geo.region (world_region) is a legitimate target.
        from resolvekit.packs.geo.scoring import FALLBACK_SCORE, GeoScorer

        scorer = GeoScorer()
        features = self._features(
            exact_name_hit=True,
            query_is_upper=True,
            query_len=4,
            hierarchy_rank=0.75,  # geo.region / world_region
        )
        score = scorer.score(features, _STUB_RETRIEVAL)
        assert score > FALLBACK_SCORE + 0.01  # NOT clamped — allowed through

    def test_exact_name_admin_blocked_on_uppercase_acronym(self):
        # "NASA" → exact_name geo.admin4 "Nasa" must be suppressed.
        from resolvekit.packs.geo.scoring import FALLBACK_SCORE, GeoScorer

        scorer = GeoScorer()
        features = self._features(
            exact_name_hit=True,
            query_is_upper=True,
            query_len=4,
            hierarchy_rank=0.35,  # geo.admin4
        )
        score = scorer.score(features, _STUB_RETRIEVAL)
        assert score <= FALLBACK_SCORE + 0.01

    def test_exact_name_city_blocked_on_uppercase_acronym(self):
        # "SWIFT" → exact_name geo.city "Swift" must be suppressed.
        from resolvekit.packs.geo.scoring import FALLBACK_SCORE, GeoScorer

        scorer = GeoScorer()
        features = self._features(
            exact_name_hit=True,
            query_is_upper=True,
            query_len=5,
            hierarchy_rank=0.70,  # geo.city
        )
        score = scorer.score(features, _STUB_RETRIEVAL)
        assert score <= FALLBACK_SCORE + 0.01

    def test_fuzzy_organization_allowed_on_uppercase_acronym(self):
        # "NATO" / "ASEAN" → geo.organization candidates must NOT be blocked.
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        features = self._features(
            fuzzy_edit_sim=0.95,
            query_is_upper=True,
            query_len=4,
            hierarchy_rank=0.80,  # geo.organization
        )
        score = scorer.score(features, _STUB_RETRIEVAL)
        assert score > 0.7  # clears confidence threshold

    def test_exact_name_organization_allowed_on_uppercase_acronym(self):
        # Exact-name hits on geo.organization must not be suppressed.
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        features = self._features(
            exact_name_hit=True,
            query_is_upper=True,
            query_len=5,
            hierarchy_rank=0.80,  # geo.organization
        )
        score = scorer.score(features, _STUB_RETRIEVAL)
        assert score >= 0.90  # EXACT_NAME_SCORE unchanged

    def test_exact_code_always_exempt_from_block(self):
        # Exact-code matches are never suppressed regardless of hierarchy rank.
        from resolvekit.packs.geo.scoring import EXACT_CODE_SCORE, GeoScorer

        scorer = GeoScorer()
        features = self._features(
            exact_code_hit=True,
            query_is_upper=True,
            query_len=4,
            hierarchy_rank=0.35,  # would be blocked if not exact-code
        )
        score = scorer.score(features, _STUB_RETRIEVAL)
        assert score >= EXACT_CODE_SCORE

    def test_lowercase_query_not_blocked(self):
        # The block only fires on all-uppercase queries — lowercase is safe.
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        features = self._features(
            fuzzy_edit_sim=1.0,
            query_is_upper=False,  # mixed or lowercase
            query_len=4,
            hierarchy_rank=0.35,  # geo.admin4
        )
        score = scorer.score(features, _STUB_RETRIEVAL)
        assert score > 0.7  # not suppressed

    def test_short_query_below_range_not_blocked(self):
        # 3-char queries (ISO-2-ish) are below the acronym range — not blocked.
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        features = self._features(
            fuzzy_edit_sim=1.0,
            query_is_upper=True,
            query_len=3,  # below ACRONYM_QUERY_MIN_LEN=4
            hierarchy_rank=0.35,
        )
        score = scorer.score(features, _STUB_RETRIEVAL)
        assert score > 0.7  # not suppressed

    def test_long_query_above_range_not_blocked(self):
        # Queries longer than 10 chars are above the acronym range — not blocked.
        from resolvekit.packs.geo.scoring import GeoScorer

        scorer = GeoScorer()
        features = self._features(
            fuzzy_edit_sim=1.0,
            query_is_upper=True,
            query_len=11,  # above ACRONYM_QUERY_MAX_LEN=10
            hierarchy_rank=0.35,
        )
        score = scorer.score(features, _STUB_RETRIEVAL)
        assert score > 0.7  # not suppressed

    def test_exact_name_subregion_allowed_on_uppercase_acronym(self):
        # "MENA"-style exact name on geo.subregion (rank 0.78) must not be
        # suppressed — sub-regions sit in the same region tier (0.75-0.80) that
        # allows exact-name hits through while blocking fuzzy misroutings.
        from resolvekit.packs.geo.scoring import FALLBACK_SCORE, GeoScorer

        scorer = GeoScorer()
        features = self._features(
            exact_name_hit=True,
            query_is_upper=True,
            query_len=4,
            hierarchy_rank=0.78,  # geo.subregion
        )
        score = scorer.score(features, _STUB_RETRIEVAL)
        assert score > FALLBACK_SCORE + 0.01  # NOT clamped — allowed through

    def test_fuzzy_subregion_blocked_on_uppercase_acronym(self):
        # A fuzzy match to geo.subregion (rank 0.78) on an all-uppercase acronym
        # query must be suppressed — same region-tier fuzzy suppression as geo.region.
        from resolvekit.packs.geo.scoring import FALLBACK_SCORE, GeoScorer

        scorer = GeoScorer()
        features = self._features(
            fuzzy_edit_sim=0.8,
            query_is_upper=True,
            query_len=4,
            hierarchy_rank=0.78,  # geo.subregion
        )
        score = scorer.score(features, _STUB_RETRIEVAL)
        assert score <= FALLBACK_SCORE + 0.01  # clamped, cannot clear 0.7 threshold


class TestGeoDecisionPolicy:
    def test_resolves_high_confidence(self):
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
        from resolvekit.packs.geo.decision import GeoDecisionPolicy

        policy = GeoDecisionPolicy()
        query = Query(
            raw_text="USA",
            normalized=NormalizedText(original="USA", normalized="usa"),
        )

        candidates = [
            Candidate(
                entity_id="country/USA",
                sources=[
                    CandidateEvidence(
                        entity_id="country/USA",
                        source_name="geo_exact_code",
                        raw_score=1.0,
                    )
                ],
                retrieval=RetrievalSummary(best_source="geo_exact_code"),
                scores=ScoreSummary(raw_score=0.95, calibrated_score=0.97),
            )
        ]

        result = policy.decide(query, ResolutionContext(), candidates, NullTraceSink())

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"

    def test_ambiguous_when_close_scores(self):
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
        from resolvekit.packs.geo.decision import GeoDecisionPolicy

        policy = GeoDecisionPolicy()
        query = Query(
            raw_text="Springfield",
            normalized=NormalizedText(original="Springfield", normalized="springfield"),
        )

        # Both candidates above the confidence threshold, gap < 0.1 → AMBIGUOUS.
        candidates = [
            Candidate(
                entity_id="city/Springfield_IL",
                sources=[
                    CandidateEvidence(
                        entity_id="city/Springfield_IL",
                        source_name="geo_fts",
                        raw_score=0.85,
                    )
                ],
                retrieval=RetrievalSummary(best_source="geo_fts"),
                scores=ScoreSummary(raw_score=0.84, calibrated_score=0.84),
            ),
            Candidate(
                entity_id="city/Springfield_MO",
                sources=[
                    CandidateEvidence(
                        entity_id="city/Springfield_MO",
                        source_name="geo_fts",
                        raw_score=0.84,
                    )
                ],
                retrieval=RetrievalSummary(best_source="geo_fts"),
                scores=ScoreSummary(raw_score=0.83, calibrated_score=0.83),
            ),
        ]

        result = policy.decide(query, ResolutionContext(), candidates, NullTraceSink())

        assert result.status == ResolutionStatus.AMBIGUOUS

    def _ranked_candidate(self, entity_id, calibrated, hierarchy_rank):
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            RetrievalSummary,
            ScoreSummary,
        )
        from resolvekit.packs.geo.features import GeoFeaturesV1

        return Candidate(
            entity_id=entity_id,
            sources=[
                CandidateEvidence(
                    entity_id=entity_id,
                    source_name="geo_exact_name",
                    raw_score=calibrated,
                )
            ],
            retrieval=RetrievalSummary(best_source="geo_exact_name"),
            features=GeoFeaturesV1(hierarchy_rank=hierarchy_rank),
            scores=ScoreSummary(raw_score=calibrated, calibrated_score=calibrated),
        )

    def test_hierarchy_tiebreak_continent_beats_same_named_region(self):
        """A near-tie is resolved to the higher-ranked geo entity.

        "Antarctica" matches both a continent (rank 1.0) and a same-named UN
        region (rank 0.75) within min_gap; the continent wins.
        """
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            NormalizedText,
            Query,
            ReasonCode,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.packs.geo.decision import GeoDecisionPolicy

        policy = GeoDecisionPolicy()
        query = Query(
            raw_text="Antarctica",
            normalized=NormalizedText(original="Antarctica", normalized="antarctica"),
        )
        candidates = [
            self._ranked_candidate("wikidataId/Q51", 0.909, 1.0),
            self._ranked_candidate("undata-geo/G00000110", 0.907, 0.75),
        ]

        result = policy.decide(query, ResolutionContext(), candidates, NullTraceSink())

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "wikidataId/Q51"
        assert ReasonCode.HIERARCHY_PREFERENCE_TIEBREAK in result.reasons

    def test_hierarchy_tiebreak_skipped_for_equal_ranks(self):
        """Equal-rank near-ties stay AMBIGUOUS (no false hierarchy winner)."""
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.packs.geo.decision import GeoDecisionPolicy

        policy = GeoDecisionPolicy()
        query = Query(
            raw_text="Springfield",
            normalized=NormalizedText(original="Springfield", normalized="springfield"),
        )
        candidates = [
            self._ranked_candidate("city/Springfield_IL", 0.84, 0.70),
            self._ranked_candidate("city/Springfield_MO", 0.83, 0.70),
        ]

        result = policy.decide(query, ResolutionContext(), candidates, NullTraceSink())

        assert result.status == ResolutionStatus.AMBIGUOUS

    def test_no_match_when_empty_candidates(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            NormalizedText,
            Query,
            ResolutionContext,
            ResolutionStatus,
        )
        from resolvekit.packs.geo.decision import GeoDecisionPolicy

        policy = GeoDecisionPolicy()
        query = Query(
            raw_text="Nonexistent",
            normalized=NormalizedText(original="Nonexistent", normalized="nonexistent"),
        )

        result = policy.decide(query, ResolutionContext(), [], NullTraceSink())

        assert result.status == ResolutionStatus.NO_MATCH

    def test_exact_code_min_score_custom(self):
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
        from resolvekit.packs.geo.decision import GeoDecisionPolicy

        # With default (0.9), a score of 0.8 should NOT early-accept
        policy_default = GeoDecisionPolicy()
        # With lower threshold (0.75), a score of 0.8 SHOULD early-accept
        policy_low = GeoDecisionPolicy(exact_code_min_score=0.75)

        query = Query(
            raw_text="USA",
            normalized=NormalizedText(original="USA", normalized="usa"),
        )
        candidates = [
            Candidate(
                entity_id="country/USA",
                sources=[
                    CandidateEvidence(
                        entity_id="country/USA",
                        source_name="geo_exact_code",
                        raw_score=1.0,
                    )
                ],
                retrieval=RetrievalSummary(best_source="geo_exact_code"),
                scores=ScoreSummary(raw_score=0.8, calibrated_score=0.8),
            )
        ]

        result_default = policy_default.decide(
            query, ResolutionContext(), candidates, NullTraceSink()
        )
        result_low = policy_low.decide(
            query, ResolutionContext(), candidates, NullTraceSink()
        )

        # Default (0.9): 0.8 < 0.9, so it goes through normal path -> RESOLVED via threshold check
        assert result_default.status == ResolutionStatus.RESOLVED
        # Low (0.75): 0.8 >= 0.75, early accept via exact code
        assert result_low.status == ResolutionStatus.RESOLVED

    def test_no_match_below_threshold(self):
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
        from resolvekit.packs.geo.decision import GeoDecisionPolicy

        policy = GeoDecisionPolicy()
        query = Query(
            raw_text="Xyz",
            normalized=NormalizedText(original="Xyz", normalized="xyz"),
        )

        candidates = [
            Candidate(
                entity_id="country/XYZ",
                sources=[
                    CandidateEvidence(
                        entity_id="country/XYZ", source_name="geo_fts", raw_score=0.3
                    )
                ],
                retrieval=RetrievalSummary(best_source="geo_fts"),
                scores=ScoreSummary(
                    raw_score=0.3, calibrated_score=0.5
                ),  # Below 0.7 threshold
            ),
        ]

        result = policy.decide(query, ResolutionContext(), candidates, NullTraceSink())

        assert result.status == ResolutionStatus.NO_MATCH

    def test_no_match_below_threshold_beats_ambiguous_gap(self):
        """A candidate just below the confidence threshold yields NO_MATCH.

        The threshold check takes precedence over the gap check: two tied
        candidates below the confidence threshold produce NO_MATCH (with
        BELOW_CONFIDENCE_THRESHOLD), not AMBIGUOUS.
        """
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
        from resolvekit.packs.geo.decision import (
            DEFAULT_CONFIDENCE_THRESHOLD,
            GeoDecisionPolicy,
        )

        policy = GeoDecisionPolicy()
        query = Query(
            raw_text="qwerty",
            normalized=NormalizedText(original="qwerty", normalized="qwerty"),
        )

        below_threshold_score = DEFAULT_CONFIDENCE_THRESHOLD - 0.002

        candidates = [
            Candidate(
                entity_id="geo/FakePlace1",
                sources=[
                    CandidateEvidence(
                        entity_id="geo/FakePlace1",
                        source_name="geo_fuzzy",
                        raw_score=below_threshold_score,
                    )
                ],
                retrieval=RetrievalSummary(best_source="geo_fuzzy"),
                scores=ScoreSummary(
                    raw_score=below_threshold_score,
                    calibrated_score=below_threshold_score,
                ),
            ),
            Candidate(
                entity_id="geo/FakePlace2",
                sources=[
                    CandidateEvidence(
                        entity_id="geo/FakePlace2",
                        source_name="geo_fuzzy",
                        raw_score=below_threshold_score,
                    )
                ],
                retrieval=RetrievalSummary(best_source="geo_fuzzy"),
                scores=ScoreSummary(
                    raw_score=below_threshold_score,
                    calibrated_score=below_threshold_score,
                ),
            ),
        ]

        result = policy.decide(query, ResolutionContext(), candidates, NullTraceSink())

        assert result.status == ResolutionStatus.NO_MATCH
        assert ReasonCode.BELOW_CONFIDENCE_THRESHOLD in result.reasons
