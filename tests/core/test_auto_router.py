"""Tests for auto-routing heuristics."""


def _geo_org_router(available_packs=("geo", "org")):
    """Build an AutoRouter with real geo/org RoutingHints (including scoring_fn)."""
    from resolvekit.core.engine import AutoRouter
    from resolvekit.packs.geo.pack import GeoPack
    from resolvekit.packs.org.pack import OrgPack

    geo_hints = GeoPack().routing_hints
    org_hints = OrgPack().routing_hints
    pack_hints = {"geo": geo_hints, "org": org_hints}
    return AutoRouter(
        available_packs=list(available_packs),
        pack_hints={k: v for k, v in pack_hints.items() if k in available_packs},
    )


class TestAutoRouter:
    """Tests for heuristic-based routing."""

    def test_routes_acronym_to_org(self):
        from resolvekit.core.model import NormalizedText, Query, ResolutionContext

        router = _geo_org_router()

        query = Query(
            raw_text="EU",
            normalized=NormalizedText(original="EU", normalized="eu"),
        )

        decision = router.route(query, ResolutionContext())

        assert "org" in decision.target_packs
        assert decision.confidence >= 0.7

    def test_routes_country_code_to_geo(self):
        from resolvekit.core.model import NormalizedText, Query, ResolutionContext

        router = _geo_org_router()

        query = Query(
            raw_text="US",
            normalized=NormalizedText(original="US", normalized="us"),
        )

        decision = router.route(query, ResolutionContext())

        assert "geo" in decision.target_packs

    def test_routes_place_name_to_geo(self):
        from resolvekit.core.model import NormalizedText, Query, ResolutionContext

        router = _geo_org_router()

        query = Query(
            raw_text="California",
            normalized=NormalizedText(original="California", normalized="california"),
        )

        decision = router.route(query, ResolutionContext())

        assert "geo" in decision.target_packs
        assert decision.confidence >= 0.6

    def test_ambiguous_routes_to_both(self):
        from resolvekit.core.engine import AutoRouter
        from resolvekit.core.model import NormalizedText, Query, ResolutionContext

        router = AutoRouter(available_packs=["geo", "org"])

        query = Query(
            raw_text="Paris",  # Could be city or org name
            normalized=NormalizedText(original="Paris", normalized="paris"),
        )

        decision = router.route(query, ResolutionContext())

        assert len(decision.target_packs) >= 1

    def test_context_hint_influences_routing(self):
        from resolvekit.core.engine import AutoRouter
        from resolvekit.core.model import NormalizedText, Query, ResolutionContext

        router = AutoRouter(available_packs=["geo", "org"])

        query = Query(
            raw_text="IDA",
            normalized=NormalizedText(original="IDA", normalized="ida"),
        )
        context = ResolutionContext(entity_types={"org.igo"})

        decision = router.route(query, context)

        assert "org" in decision.target_packs

    def test_respects_available_packs_constraint(self):
        """AutoRouter should only return packs that are available."""
        from resolvekit.core.engine import AutoRouter
        from resolvekit.core.model import NormalizedText, Query, ResolutionContext

        # Only geo pack available
        router = AutoRouter(available_packs=["geo"])

        # EU looks like an org acronym, but only geo is available
        query = Query(
            raw_text="EU",
            normalized=NormalizedText(original="EU", normalized="eu"),
        )

        decision = router.route(query, ResolutionContext())

        assert decision.target_packs == ["geo"]
        assert "org" not in decision.target_packs

    def test_context_hint_respects_available_packs(self):
        """ResolutionContext hints should be constrained to available packs."""
        from resolvekit.core.engine import AutoRouter
        from resolvekit.core.model import NormalizedText, Query, ResolutionContext

        # Only geo pack available
        router = AutoRouter(available_packs=["geo"])

        query = Query(
            raw_text="IDA",
            normalized=NormalizedText(original="IDA", normalized="ida"),
        )
        # Hint for org, but org is not available
        context = ResolutionContext(entity_types={"org.igo"})

        decision = router.route(query, context)

        assert decision.target_packs == ["geo"]
        assert "org" not in decision.target_packs

    def test_deterministic_routing_order(self):
        """Routing should produce deterministic pack ordering."""
        from resolvekit.core.engine import AutoRouter
        from resolvekit.core.model import NormalizedText, Query, ResolutionContext

        router = AutoRouter(available_packs=["geo", "org"])

        query = Query(
            raw_text="Paris",
            normalized=NormalizedText(original="Paris", normalized="paris"),
        )
        # Multiple hint types
        context = ResolutionContext(entity_types={"org.ngo", "geo.city"})

        # Run multiple times to check determinism
        decisions = [router.route(query, context) for _ in range(10)]

        # All decisions should have the same pack order
        first_packs = decisions[0].target_packs
        for decision in decisions[1:]:
            assert decision.target_packs == first_packs
