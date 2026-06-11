"""Tests for GeoFuzzySource."""


class TestGeoFuzzySource:
    """Tests for GeoFuzzySource."""

    def test_source_properties(self):
        from resolvekit.packs.geo.sources.fuzzy import GeoFuzzySource

        source = GeoFuzzySource()
        assert source.name == "geo_fuzzy"
        assert source.supports("geo") is True
        assert source.supports("org") is False
        assert source.requires_existing_candidates is True

    def test_reranks_candidates_with_fuzzy_scores(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            EntityRecord,
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
            RetrievalSummary,
            ScoreSummary,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.sources.fuzzy import GeoFuzzySource

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                if entity_id == "country/USA":
                    return EntityRecord(
                        entity_id="country/USA",
                        entity_type="geo.country",
                        canonical_name="United States of America",
                        canonical_name_norm="united states of america",
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

        source = GeoFuzzySource()
        query = Query(
            raw_text="Untied States",  # Typo
            normalized=NormalizedText(
                original="Untied States", normalized="untied states"
            ),
        )

        # Existing candidates from other sources
        existing_candidates = [
            Candidate(
                entity_id="country/USA",
                sources=[
                    CandidateEvidence(
                        entity_id="country/USA", source_name="fts", raw_score=0.6
                    )
                ],
                retrieval=RetrievalSummary(best_source="fts"),
                scores=ScoreSummary(raw_score=0.6, calibrated_score=0.6),
            )
        ]

        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(),
            store=MockStore(),
            budget=10,
            trace=NullTraceSink(),
            existing_candidates=existing_candidates,
        )
        evidence = source.generate(ctx)

        # Should produce fuzzy evidence for USA
        assert len(evidence) >= 1
        assert evidence[0].source_name == "geo_fuzzy"
        assert evidence[0].raw_score > 0  # Has a fuzzy similarity score

    def test_returns_empty_without_existing_candidates(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.sources.fuzzy import GeoFuzzySource

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

        source = GeoFuzzySource()
        query = Query(
            raw_text="test",
            normalized=NormalizedText(original="test", normalized="test"),
        )

        # No existing candidates
        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(),
            store=MockStore(),
            budget=10,
            trace=NullTraceSink(),
        )
        evidence = source.generate(ctx)

        assert len(evidence) == 0

    def test_fuzzy_score_higher_for_closer_match(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            EntityRecord,
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
            RetrievalSummary,
            ScoreSummary,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.sources.fuzzy import GeoFuzzySource

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                entities = {
                    "country/USA": EntityRecord(
                        entity_id="country/USA",
                        entity_type="geo.country",
                        canonical_name="United States",
                        canonical_name_norm="united states",
                    ),
                    "country/GBR": EntityRecord(
                        entity_id="country/GBR",
                        entity_type="geo.country",
                        canonical_name="United Kingdom",
                        canonical_name_norm="united kingdom",
                    ),
                }
                return entities.get(entity_id)

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

        source = GeoFuzzySource()
        # Query closer to "united states" than "united kingdom"
        query = Query(
            raw_text="United Staets",  # Typo in "States"
            normalized=NormalizedText(
                original="United Staets", normalized="united staets"
            ),
        )

        existing_candidates = [
            Candidate(
                entity_id="country/USA",
                sources=[
                    CandidateEvidence(
                        entity_id="country/USA", source_name="fts", raw_score=0.5
                    )
                ],
                retrieval=RetrievalSummary(best_source="fts"),
                scores=ScoreSummary(raw_score=0.5, calibrated_score=0.5),
            ),
            Candidate(
                entity_id="country/GBR",
                sources=[
                    CandidateEvidence(
                        entity_id="country/GBR", source_name="fts", raw_score=0.5
                    )
                ],
                retrieval=RetrievalSummary(best_source="fts"),
                scores=ScoreSummary(raw_score=0.5, calibrated_score=0.5),
            ),
        ]

        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(),
            store=MockStore(),
            budget=10,
            trace=NullTraceSink(),
            existing_candidates=existing_candidates,
        )
        evidence = source.generate(ctx)

        # Find scores for USA and GBR
        usa_score = next(e.raw_score for e in evidence if e.entity_id == "country/USA")
        gbr_score = next(e.raw_score for e in evidence if e.entity_id == "country/GBR")

        # USA should have higher score (closer match)
        assert usa_score > gbr_score

    def test_scores_against_all_name_variants(self):
        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            Candidate,
            CandidateEvidence,
            EntityRecord,
            GenerationContext,
            NameRecord,
            NormalizedText,
            Query,
            ResolutionContext,
            RetrievalSummary,
            ScoreSummary,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.sources.fuzzy import GeoFuzzySource

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                if entity_id == "country/USA":
                    return EntityRecord(
                        entity_id="country/USA",
                        entity_type="geo.country",
                        canonical_name="United States of America",
                        canonical_name_norm="united states of america",
                        names=[
                            NameRecord(
                                value="America",
                                value_norm="america",
                                kind="alias",
                            )
                        ],
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

        source = GeoFuzzySource()
        query = Query(
            raw_text="America",
            normalized=NormalizedText(original="America", normalized="america"),
        )

        existing_candidates = [
            Candidate(
                entity_id="country/USA",
                sources=[
                    CandidateEvidence(
                        entity_id="country/USA", source_name="fts", raw_score=0.5
                    )
                ],
                retrieval=RetrievalSummary(best_source="fts"),
                scores=ScoreSummary(raw_score=0.5, calibrated_score=0.5),
            )
        ]

        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(),
            store=MockStore(),
            budget=10,
            trace=NullTraceSink(),
            existing_candidates=existing_candidates,
        )
        evidence = source.generate(ctx)

        assert len(evidence) == 1
        ev = evidence[0]

        # The alias "america" should be the best match, not the canonical
        assert ev.matched_value == "america"

        # edit_sim against "america" vs "america" should be perfect (1.0)
        assert ev.signals["fuzzy_edit_sim"] == 1.0

        # Overall score should be very high (near 1.0)
        assert ev.raw_score > 0.9
