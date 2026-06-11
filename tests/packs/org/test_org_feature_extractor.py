"""Tests for OrgFeatureExtractor."""


class TestOrgFeatureExtractor:
    def test_extracts_acronym_features(self):
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
        from resolvekit.packs.org.feature_extractor import OrgFeatureExtractor
        from resolvekit.packs.org.features import OrgFeaturesV1

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                from resolvekit.core.model import EntityRecord

                if entity_id == "org/EU":
                    return EntityRecord(
                        entity_id="org/EU",
                        entity_type="org.igo",
                        canonical_name="European Union",
                        canonical_name_norm="european union",
                    )
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {eid: self.get_entity(eid) for eid in entity_ids}

        extractor = OrgFeatureExtractor()
        query = Query(
            raw_text="EU",
            normalized=NormalizedText(original="EU", normalized="eu"),
        )

        candidate = Candidate(
            entity_id="org/EU",
            sources=[
                CandidateEvidence(
                    entity_id="org/EU",
                    source_name="org_acronym",
                    raw_score=1.0,
                    matched_field="name.acronym",
                ),
            ],
            retrieval=RetrievalSummary(best_source="org_acronym"),
            scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
        )

        features = extractor.extract(
            query, ResolutionContext(), candidate, MockStore(), NullTraceSink()
        )

        assert isinstance(features, OrgFeaturesV1)
        assert features.acronym_hit is True
        assert features.acronym_exact is True
        assert features.query_is_acronym_like is True

    def test_extracts_context_alignment_features(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            ConstraintOutcome,
            ConstraintRole,
            NormalizedText,
            Query,
            ResolutionContext,
            RetrievalSummary,
            ScoreSummary,
            Severity,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.org.feature_extractor import OrgFeatureExtractor

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                from resolvekit.core.model import EntityRecord

                return EntityRecord(
                    entity_id="org/IDA",
                    entity_type="org.igo",
                    canonical_name="International Development Association",
                    canonical_name_norm="international development association",
                )

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {eid: self.get_entity(eid) for eid in entity_ids}

        extractor = OrgFeatureExtractor()
        query = Query(
            raw_text="IDA",
            normalized=NormalizedText(original="IDA", normalized="ida"),
        )
        context = ResolutionContext(parent_ids=["org/WorldBankGroup"])

        candidate = Candidate(
            entity_id="org/IDA",
            sources=[
                CandidateEvidence(
                    entity_id="org/IDA", source_name="org_acronym", raw_score=1.0
                )
            ],
            retrieval=RetrievalSummary(best_source="org_acronym"),
            scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
            constraint_outcomes=[
                ConstraintOutcome(
                    constraint_name="org_parent_constraint",
                    passed=True,
                    severity=Severity.SOFT,
                    role=ConstraintRole.PARENT_SCOPE,
                ),
            ],
        )

        features = extractor.extract(
            query, context, candidate, MockStore(), NullTraceSink()
        )

        assert features.parent_org_match is True
