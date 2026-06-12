"""Tests for CountryRelevanceConstraint."""


class TestCountryRelevanceConstraint:
    """Tests for CountryRelevanceConstraint soft constraint."""

    def test_boosts_matching_country(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            NormalizedText,
            Query,
            ResolutionContext,
            RetrievalSummary,
            ScoreSummary,
            Severity,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.org.constraints.country_relevance import (
            CountryRelevanceConstraint,
        )

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                from resolvekit.core.model import EntityRecord

                return EntityRecord(
                    entity_id=entity_id,
                    entity_type="org.ngo",
                    canonical_name="Test Org",
                    canonical_name_norm="test org",
                    attributes={"country_code": "US" if "US" in entity_id else "DE"},
                )

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {eid: self.get_entity(eid) for eid in entity_ids}

        constraint = CountryRelevanceConstraint()
        query = Query(
            raw_text="Test Org",
            normalized=NormalizedText(original="Test Org", normalized="test org"),
        )
        context = ResolutionContext(country="US")

        candidates = [
            Candidate(
                entity_id="org/TestOrg_US",
                sources=[
                    CandidateEvidence(
                        entity_id="org/TestOrg_US",
                        source_name="org_exact_name",
                        raw_score=1.0,
                    )
                ],
                retrieval=RetrievalSummary(best_source="org_exact_name"),
                scores=ScoreSummary(raw_score=0.85, calibrated_score=0.85),
            ),
            Candidate(
                entity_id="org/TestOrg_DE",
                sources=[
                    CandidateEvidence(
                        entity_id="org/TestOrg_DE",
                        source_name="org_exact_name",
                        raw_score=1.0,
                    )
                ],
                retrieval=RetrievalSummary(best_source="org_exact_name"),
                scores=ScoreSummary(raw_score=0.85, calibrated_score=0.85),
            ),
        ]

        result = constraint.apply(
            query, context, candidates, MockStore(), NullTraceSink()
        )

        # Both should remain (soft constraint)
        assert len(result) == 2

        # US org should have passed=True, DE should have passed=False
        us_outcomes = result[0].constraint_outcomes
        de_outcomes = result[1].constraint_outcomes

        us_country = next(
            co for co in us_outcomes if co.constraint_name == "org_country_relevance"
        )
        de_country = next(
            co for co in de_outcomes if co.constraint_name == "org_country_relevance"
        )

        assert us_country.passed is True
        assert us_country.severity == Severity.SOFT
        assert de_country.passed is False
        assert de_country.severity == Severity.SOFT

    def test_alpha3_hint_matches_alpha2_country_code(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            NormalizedText,
            Query,
            ResolutionContext,
            RetrievalSummary,
            ScoreSummary,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.org.constraints.country_relevance import (
            CountryRelevanceConstraint,
        )

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                from resolvekit.core.model import EntityRecord

                return EntityRecord(
                    entity_id=entity_id,
                    entity_type="org.ngo",
                    canonical_name="Test Org",
                    canonical_name_norm="test org",
                    attributes={"country_code": "US" if "US" in entity_id else "DE"},
                )

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {eid: self.get_entity(eid) for eid in entity_ids}

        constraint = CountryRelevanceConstraint()
        query = Query(
            raw_text="Test Org",
            normalized=NormalizedText(original="Test Org", normalized="test org"),
        )
        context = ResolutionContext(country="USA")  # alpha-3 for United States

        candidates = [
            Candidate(
                entity_id="org/TestOrg_US",
                sources=[
                    CandidateEvidence(
                        entity_id="org/TestOrg_US",
                        source_name="org_exact_name",
                        raw_score=1.0,
                    )
                ],
                retrieval=RetrievalSummary(best_source="org_exact_name"),
                scores=ScoreSummary(raw_score=0.85, calibrated_score=0.85),
            ),
            Candidate(
                entity_id="org/TestOrg_DE",
                sources=[
                    CandidateEvidence(
                        entity_id="org/TestOrg_DE",
                        source_name="org_exact_name",
                        raw_score=1.0,
                    )
                ],
                retrieval=RetrievalSummary(best_source="org_exact_name"),
                scores=ScoreSummary(raw_score=0.85, calibrated_score=0.85),
            ),
        ]

        result = constraint.apply(
            query, context, candidates, MockStore(), NullTraceSink()
        )

        # Both should remain (soft constraint)
        assert len(result) == 2

        us_country = next(
            co
            for co in result[0].constraint_outcomes
            if co.constraint_name == "org_country_relevance"
        )
        de_country = next(
            co
            for co in result[1].constraint_outcomes
            if co.constraint_name == "org_country_relevance"
        )

        # "USA" (alpha-3) should resolve to "US" (alpha-2) and match the US org
        assert us_country.passed is True
        assert de_country.passed is False

    def test_no_filter_without_context(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            NormalizedText,
            Query,
            ResolutionContext,
            RetrievalSummary,
            ScoreSummary,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.org.constraints.country_relevance import (
            CountryRelevanceConstraint,
        )

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

        constraint = CountryRelevanceConstraint()
        query = Query(
            raw_text="Test",
            normalized=NormalizedText(original="Test", normalized="test"),
        )

        candidates = [
            Candidate(
                entity_id="org/Test",
                sources=[
                    CandidateEvidence(
                        entity_id="org/Test", source_name="test", raw_score=0.1
                    )
                ],
                retrieval=RetrievalSummary(best_source="test"),
                scores=ScoreSummary(raw_score=0.1, calibrated_score=0.1),
            )
        ]

        result = constraint.apply(
            query, ResolutionContext(), candidates, MockStore(), NullTraceSink()
        )

        assert len(result) == 1
        assert len(result[0].constraint_outcomes) == 0
