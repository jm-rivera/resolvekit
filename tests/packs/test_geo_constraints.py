"""Tests for geo constraints."""

from datetime import date


class TestTypeConstraint:
    """Tests for GeoTypeConstraint."""

    def test_constraint_properties(self):
        from resolvekit.packs.geo.constraints.type_constraint import (
            GeoTypeConstraint,
        )

        constraint = GeoTypeConstraint()
        assert constraint.name == "geo_type_constraint"

    def test_passes_when_no_entity_types(self):
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
        from resolvekit.packs.geo.constraints.type_constraint import (
            GeoTypeConstraint,
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

        constraint = GeoTypeConstraint()
        query = Query(
            raw_text="Test",
            normalized=NormalizedText(original="Test", normalized="test"),
        )
        context = ResolutionContext()  # No entity_types

        candidates = [
            Candidate(
                entity_id="state/California",
                sources=[
                    CandidateEvidence(
                        entity_id="state/California", source_name="test", raw_score=1.0
                    )
                ],
                retrieval=RetrievalSummary(best_source="test"),
                scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
            )
        ]

        result = constraint.apply(
            query, context, candidates, MockStore(), NullTraceSink()
        )

        # Should pass through all candidates when no entity_types
        assert len(result) == 1

    def test_filters_wrong_type(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            EntityRecord,
            NormalizedText,
            Query,
            ResolutionContext,
            RetrievalSummary,
            ScoreSummary,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.constraints.type_constraint import (
            GeoTypeConstraint,
        )

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                if entity_id == "state/California":
                    return EntityRecord(
                        entity_id="state/California",
                        entity_type="geo.state",
                        canonical_name="California",
                        canonical_name_norm="california",
                    )
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {
                    eid: self.get_entity(eid)
                    for eid in entity_ids
                    if self.get_entity(eid)
                }

        constraint = GeoTypeConstraint()
        query = Query(
            raw_text="Test",
            normalized=NormalizedText(original="Test", normalized="test"),
        )
        context = ResolutionContext(
            entity_types={"geo.country"}
        )  # Looking for countries

        candidates = [
            Candidate(
                entity_id="state/California",  # This is a state, not country
                sources=[
                    CandidateEvidence(
                        entity_id="state/California", source_name="test", raw_score=1.0
                    )
                ],
                retrieval=RetrievalSummary(best_source="test"),
                scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
            )
        ]

        result = constraint.apply(
            query, context, candidates, MockStore(), NullTraceSink()
        )

        # Should be filtered (hard constraint)
        assert len(result) == 0

    def test_keeps_correct_type(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            EntityRecord,
            NormalizedText,
            Query,
            ResolutionContext,
            RetrievalSummary,
            ScoreSummary,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.constraints.type_constraint import (
            GeoTypeConstraint,
        )

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                if entity_id == "country/USA":
                    return EntityRecord(
                        entity_id="country/USA",
                        entity_type="geo.country",
                        canonical_name="United States",
                        canonical_name_norm="united states",
                    )
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {
                    eid: self.get_entity(eid)
                    for eid in entity_ids
                    if self.get_entity(eid)
                }

        constraint = GeoTypeConstraint()
        query = Query(
            raw_text="Test",
            normalized=NormalizedText(original="Test", normalized="test"),
        )
        context = ResolutionContext(entity_types={"geo.country"})

        candidates = [
            Candidate(
                entity_id="country/USA",
                sources=[
                    CandidateEvidence(
                        entity_id="country/USA", source_name="test", raw_score=1.0
                    )
                ],
                retrieval=RetrievalSummary(best_source="test"),
                scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
            )
        ]

        result = constraint.apply(
            query, context, candidates, MockStore(), NullTraceSink()
        )

        # Should keep the country
        assert len(result) == 1
        assert result[0].constraint_outcomes[0].passed is True


class TestTemporalConstraint:
    """Tests for GeoTemporalConstraint."""

    def test_constraint_properties(self):
        from resolvekit.packs.geo.constraints.temporal import (
            GeoTemporalConstraint,
        )

        constraint = GeoTemporalConstraint()
        assert constraint.name == "geo_temporal_constraint"

    def test_passes_when_no_as_of(self):
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
        from resolvekit.packs.geo.constraints.temporal import (
            GeoTemporalConstraint,
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

        constraint = GeoTemporalConstraint()
        query = Query(
            raw_text="Soviet Union",
            normalized=NormalizedText(
                original="Soviet Union", normalized="soviet union"
            ),
        )
        context = ResolutionContext()  # No as_of

        candidates = [
            Candidate(
                entity_id="country/SU",
                sources=[
                    CandidateEvidence(
                        entity_id="country/SU", source_name="test", raw_score=1.0
                    )
                ],
                retrieval=RetrievalSummary(best_source="test"),
                scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
            )
        ]

        result = constraint.apply(
            query, context, candidates, MockStore(), NullTraceSink()
        )

        # Should pass through unchanged
        assert len(result) == 1

    def test_drops_invalid_at_date(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            EntityRecord,
            NormalizedText,
            Query,
            ResolutionContext,
            RetrievalSummary,
            ScoreSummary,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.constraints.temporal import (
            GeoTemporalConstraint,
        )

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                if entity_id == "country/SU":
                    return EntityRecord(
                        entity_id="country/SU",
                        entity_type="geo.country",
                        canonical_name="Soviet Union",
                        canonical_name_norm="soviet union",
                        valid_until=date(1991, 12, 26),
                    )
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {
                    eid: self.get_entity(eid)
                    for eid in entity_ids
                    if self.get_entity(eid)
                }

        constraint = GeoTemporalConstraint()
        query = Query(
            raw_text="Soviet Union",
            normalized=NormalizedText(
                original="Soviet Union", normalized="soviet union"
            ),
        )
        context = ResolutionContext(as_of=date(2024, 1, 1))  # After dissolution

        candidates = [
            Candidate(
                entity_id="country/SU",
                sources=[
                    CandidateEvidence(
                        entity_id="country/SU", source_name="test", raw_score=1.0
                    )
                ],
                retrieval=RetrievalSummary(best_source="test"),
                scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
            )
        ]

        result = constraint.apply(
            query, context, candidates, MockStore(), NullTraceSink()
        )

        # Hard constraint - an expired entity is dropped when as_of is set.
        assert len(result) == 0

    def test_marks_valid_at_date(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            EntityRecord,
            NormalizedText,
            Query,
            ResolutionContext,
            RetrievalSummary,
            ScoreSummary,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.constraints.temporal import (
            GeoTemporalConstraint,
        )

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                if entity_id == "country/SU":
                    return EntityRecord(
                        entity_id="country/SU",
                        entity_type="geo.country",
                        canonical_name="Soviet Union",
                        canonical_name_norm="soviet union",
                        valid_until=date(1991, 12, 26),
                    )
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {
                    eid: self.get_entity(eid)
                    for eid in entity_ids
                    if self.get_entity(eid)
                }

        constraint = GeoTemporalConstraint()
        query = Query(
            raw_text="Soviet Union",
            normalized=NormalizedText(
                original="Soviet Union", normalized="soviet union"
            ),
        )
        context = ResolutionContext(as_of=date(1980, 1, 1))  # Before dissolution

        candidates = [
            Candidate(
                entity_id="country/SU",
                sources=[
                    CandidateEvidence(
                        entity_id="country/SU", source_name="test", raw_score=1.0
                    )
                ],
                retrieval=RetrievalSummary(best_source="test"),
                scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
            )
        ]

        result = constraint.apply(
            query, context, candidates, MockStore(), NullTraceSink()
        )

        # Should pass
        assert len(result) == 1
        assert any(
            co.constraint_name == "geo_temporal_constraint" and co.passed is True
            for co in result[0].constraint_outcomes
        )


class TestContainmentConstraint:
    """Tests for GeoContainmentConstraint."""

    def test_constraint_properties(self):
        from resolvekit.packs.geo.constraints.containment import (
            GeoContainmentConstraint,
        )

        constraint = GeoContainmentConstraint()
        assert constraint.name == "geo_containment_constraint"

    def test_passes_when_no_parent_ids(self):
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
        from resolvekit.packs.geo.constraints.containment import (
            GeoContainmentConstraint,
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

        constraint = GeoContainmentConstraint()
        query = Query(
            raw_text="California",
            normalized=NormalizedText(original="California", normalized="california"),
        )
        context = ResolutionContext()  # No parent_ids

        candidates = [
            Candidate(
                entity_id="state/California",
                sources=[
                    CandidateEvidence(
                        entity_id="state/California", source_name="test", raw_score=1.0
                    )
                ],
                retrieval=RetrievalSummary(best_source="test"),
                scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
            )
        ]

        result = constraint.apply(
            query, context, candidates, MockStore(), NullTraceSink()
        )

        # Should pass through unchanged
        assert len(result) == 1

    def test_uses_country_as_parent_filter(self):
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
        from resolvekit.packs.geo.constraints.containment import (
            GeoContainmentConstraint,
        )

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                if system == "iso2" and value_norm == "gt":
                    return ["country/GTM"]
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

            def get_relations(self, entity_id, relation_type=None):
                if relation_type != "contained_in":
                    return []
                if entity_id == "city/ConcepcionGT":
                    return ["country/GTM"]
                if entity_id == "city/ConcepcionCL":
                    return ["country/CHL"]
                return []

        constraint = GeoContainmentConstraint()
        query = Query(
            raw_text="concepcion",
            normalized=NormalizedText(original="concepcion", normalized="concepcion"),
        )
        context = ResolutionContext(country="GT")

        gt_candidate = Candidate(
            entity_id="city/ConcepcionGT",
            sources=[
                CandidateEvidence(
                    entity_id="city/ConcepcionGT", source_name="test", raw_score=0.9
                )
            ],
            retrieval=RetrievalSummary(best_source="test"),
            scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
        )
        cl_candidate = Candidate(
            entity_id="city/ConcepcionCL",
            sources=[
                CandidateEvidence(
                    entity_id="city/ConcepcionCL", source_name="test", raw_score=0.9
                )
            ],
            retrieval=RetrievalSummary(best_source="test"),
            scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
        )
        candidates = [gt_candidate, cl_candidate]

        result = constraint.apply(
            query, context, candidates, MockStore(), NullTraceSink()
        )

        assert len(result) == 1
        assert result[0].entity_id == "city/ConcepcionGT"
        assert any(
            co.constraint_name == "geo_containment_constraint" and co.passed is False
            for co in cl_candidate.constraint_outcomes
        )

    def test_uses_alpha3_country_as_parent_filter(self):
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
        from resolvekit.packs.geo.constraints.containment import (
            GeoContainmentConstraint,
        )

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                if system == "iso3" and value_norm == "gtm":
                    return ["country/GTM"]
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

            def get_relations(self, entity_id, relation_type=None):
                if relation_type != "contained_in":
                    return []
                if entity_id == "city/ConcepcionGT":
                    return ["country/GTM"]
                if entity_id == "city/ConcepcionCL":
                    return ["country/CHL"]
                return []

        constraint = GeoContainmentConstraint()
        query = Query(
            raw_text="concepcion",
            normalized=NormalizedText(original="concepcion", normalized="concepcion"),
        )
        context = ResolutionContext(country="GTM")

        gt_candidate = Candidate(
            entity_id="city/ConcepcionGT",
            sources=[
                CandidateEvidence(
                    entity_id="city/ConcepcionGT", source_name="test", raw_score=0.9
                )
            ],
            retrieval=RetrievalSummary(best_source="test"),
            scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
        )
        cl_candidate = Candidate(
            entity_id="city/ConcepcionCL",
            sources=[
                CandidateEvidence(
                    entity_id="city/ConcepcionCL", source_name="test", raw_score=0.9
                )
            ],
            retrieval=RetrievalSummary(best_source="test"),
            scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
        )

        result = constraint.apply(
            query, context, [gt_candidate, cl_candidate], MockStore(), NullTraceSink()
        )

        assert len(result) == 1
        assert result[0].entity_id == "city/ConcepcionGT"

    def test_country_without_match_does_not_filter(self):
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
        from resolvekit.packs.geo.constraints.containment import (
            GeoContainmentConstraint,
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

        constraint = GeoContainmentConstraint()
        query = Query(
            raw_text="concepcion",
            normalized=NormalizedText(original="concepcion", normalized="concepcion"),
        )
        context = ResolutionContext(country="GT")
        candidates = [
            Candidate(
                entity_id="city/ConcepcionAny",
                sources=[
                    CandidateEvidence(
                        entity_id="city/ConcepcionAny",
                        source_name="test",
                        raw_score=0.9,
                    )
                ],
                retrieval=RetrievalSummary(best_source="test"),
                scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
            )
        ]

        result = constraint.apply(
            query, context, candidates, MockStore(), NullTraceSink()
        )

        assert len(result) == 1
        assert len(result[0].constraint_outcomes) == 0

    def test_filters_not_contained(self):
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
        from resolvekit.packs.geo.constraints.containment import (
            GeoContainmentConstraint,
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

            def get_relations(self, entity_id, relation_type=None):
                # California is contained in USA
                if entity_id == "state/California" and relation_type == "contained_in":
                    return ["country/USA"]
                return []

        constraint = GeoContainmentConstraint()
        query = Query(
            raw_text="California",
            normalized=NormalizedText(original="California", normalized="california"),
        )
        # Looking for places in Canada
        context = ResolutionContext(parent_ids=["country/CAN"])

        candidates = [
            Candidate(
                entity_id="state/California",  # In USA, not Canada
                sources=[
                    CandidateEvidence(
                        entity_id="state/California", source_name="test", raw_score=1.0
                    )
                ],
                retrieval=RetrievalSummary(best_source="test"),
                scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
            )
        ]

        result = constraint.apply(
            query, context, candidates, MockStore(), NullTraceSink()
        )

        # Should be filtered (hard constraint)
        assert len(result) == 0

    def test_keeps_contained(self):
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
        from resolvekit.packs.geo.constraints.containment import (
            GeoContainmentConstraint,
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

            def get_relations(self, entity_id, relation_type=None):
                # California is contained in USA
                if entity_id == "state/California" and relation_type == "contained_in":
                    return ["country/USA"]
                return []

        constraint = GeoContainmentConstraint()
        query = Query(
            raw_text="California",
            normalized=NormalizedText(original="California", normalized="california"),
        )
        # Looking for places in USA
        context = ResolutionContext(parent_ids=["country/USA"])

        candidates = [
            Candidate(
                entity_id="state/California",
                sources=[
                    CandidateEvidence(
                        entity_id="state/California", source_name="test", raw_score=1.0
                    )
                ],
                retrieval=RetrievalSummary(best_source="test"),
                scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
            )
        ]

        result = constraint.apply(
            query, context, candidates, MockStore(), NullTraceSink()
        )

        # Should keep the state
        assert len(result) == 1
        assert result[0].constraint_outcomes[0].passed is True

    def test_multi_parent_bfs_traversal(self):
        """Test that BFS explores all parent paths, not just the first."""
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
        from resolvekit.packs.geo.constraints.containment import (
            GeoContainmentConstraint,
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

            def get_relations(self, entity_id, relation_type=None):
                # City has two parent paths:
                # 1. city -> region/A -> country/WRONG
                # 2. city -> region/B -> country/CORRECT
                if entity_id == "city/MultiParent" and relation_type == "contained_in":
                    return ["region/A", "region/B"]  # Two parents
                if entity_id == "region/A" and relation_type == "contained_in":
                    return ["country/WRONG"]  # First path leads to wrong country
                if entity_id == "region/B" and relation_type == "contained_in":
                    return ["country/CORRECT"]  # Second path leads to correct country
                return []

        constraint = GeoContainmentConstraint()
        query = Query(
            raw_text="MultiParent City",
            normalized=NormalizedText(
                original="MultiParent City", normalized="multiparent city"
            ),
        )
        # Looking for places in CORRECT country (reachable only via second parent)
        context = ResolutionContext(parent_ids=["country/CORRECT"])

        candidates = [
            Candidate(
                entity_id="city/MultiParent",
                sources=[
                    CandidateEvidence(
                        entity_id="city/MultiParent", source_name="test", raw_score=1.0
                    )
                ],
                retrieval=RetrievalSummary(best_source="test"),
                scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
            )
        ]

        result = constraint.apply(
            query, context, candidates, MockStore(), NullTraceSink()
        )

        # Should keep the city - BFS must explore both parent paths
        assert len(result) == 1
        assert result[0].constraint_outcomes[0].passed is True


class TestMembershipConstraint:
    """Tests for GeoMembershipConstraint."""

    def test_constraint_properties(self):
        from resolvekit.packs.geo.constraints.membership import (
            GeoMembershipConstraint,
        )

        constraint = GeoMembershipConstraint()
        assert constraint.name == "geo_membership_constraint"

    def test_passes_when_no_membership_org(self):
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
        from resolvekit.packs.geo.constraints.membership import (
            GeoMembershipConstraint,
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

        constraint = GeoMembershipConstraint()
        query = Query(
            raw_text="Germany",
            normalized=NormalizedText(original="Germany", normalized="germany"),
        )
        context = ResolutionContext()  # No membership_org

        candidates = [
            Candidate(
                entity_id="country/DEU",
                sources=[
                    CandidateEvidence(
                        entity_id="country/DEU", source_name="test", raw_score=1.0
                    )
                ],
                retrieval=RetrievalSummary(best_source="test"),
                scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
            )
        ]

        result = constraint.apply(
            query, context, candidates, MockStore(), NullTraceSink()
        )

        # Should pass through unchanged (no outcomes added)
        assert len(result) == 1
        assert len(result[0].constraint_outcomes) == 0

    def test_marks_member(self):
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
        from resolvekit.packs.geo.constraints.membership import (
            GeoMembershipConstraint,
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

            def get_relations(self, entity_id, relation_type=None):
                # Germany is member of EU
                if entity_id == "country/DEU" and relation_type == "member_of":
                    return ["org/EU"]
                return []

        constraint = GeoMembershipConstraint()
        query = Query(
            raw_text="Germany",
            normalized=NormalizedText(original="Germany", normalized="germany"),
        )
        context = ResolutionContext(attributes={"membership_org": "org/EU"})

        candidates = [
            Candidate(
                entity_id="country/DEU",
                sources=[
                    CandidateEvidence(
                        entity_id="country/DEU", source_name="test", raw_score=1.0
                    )
                ],
                retrieval=RetrievalSummary(best_source="test"),
                scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
            )
        ]

        result = constraint.apply(
            query, context, candidates, MockStore(), NullTraceSink()
        )

        # Soft constraint - should keep candidate and mark as member
        assert len(result) == 1
        assert any(
            co.constraint_name == "geo_membership_constraint" and co.passed is True
            for co in result[0].constraint_outcomes
        )

    def test_marks_non_member(self):
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
        from resolvekit.packs.geo.constraints.membership import (
            GeoMembershipConstraint,
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

            def get_relations(self, entity_id, relation_type=None):
                # Norway is not member of EU
                return []

        constraint = GeoMembershipConstraint()
        query = Query(
            raw_text="Norway",
            normalized=NormalizedText(original="Norway", normalized="norway"),
        )
        context = ResolutionContext(attributes={"membership_org": "org/EU"})

        candidates = [
            Candidate(
                entity_id="country/NOR",
                sources=[
                    CandidateEvidence(
                        entity_id="country/NOR", source_name="test", raw_score=1.0
                    )
                ],
                retrieval=RetrievalSummary(best_source="test"),
                scores=ScoreSummary(raw_score=0.9, calibrated_score=0.9),
            )
        ]

        result = constraint.apply(
            query, context, candidates, MockStore(), NullTraceSink()
        )

        # Soft constraint - should keep candidate but mark as non-member
        assert len(result) == 1
        assert any(
            co.constraint_name == "geo_membership_constraint" and co.passed is False
            for co in result[0].constraint_outcomes
        )
