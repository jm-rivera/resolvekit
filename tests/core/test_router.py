"""Tests for domain routing."""


class TestRoutingMode:
    """Tests for RoutingMode enum."""

    def test_routing_modes(self):
        from resolvekit.core.engine import RoutingMode

        assert RoutingMode.EXPLICIT == "explicit"
        assert RoutingMode.AUTO == "auto"
        assert RoutingMode.HYBRID == "hybrid"


class TestRoutingDecision:
    """Tests for RoutingDecision."""

    def test_single_pack_decision(self):
        from resolvekit.core.engine import RoutingDecision

        decision = RoutingDecision(
            target_packs=["geo"],
            confidence=0.9,
            reason="Explicit request",
        )

        assert decision.target_packs == ["geo"]
        assert decision.is_single_pack is True

    def test_multi_pack_decision(self):
        from resolvekit.core.engine import RoutingDecision

        decision = RoutingDecision(
            target_packs=["geo", "org"],
            confidence=0.5,
            reason="Ambiguous query",
        )

        assert decision.is_single_pack is False


class TestRouter:
    """Tests for Router interface."""

    def test_explicit_router(self):
        from resolvekit.core.engine import ExplicitRouter
        from resolvekit.core.model import NormalizedText, Query, ResolutionContext

        router = ExplicitRouter(available_packs=["geo"])

        query = Query(
            raw_text="Paris",
            normalized=NormalizedText(original="Paris", normalized="paris"),
            domains={"geo"},
        )

        decision = router.route(query, ResolutionContext())

        assert decision.target_packs == ["geo"]
        assert decision.confidence == 1.0

    def test_explicit_router_no_types_returns_all(self):
        from resolvekit.core.engine import ExplicitRouter
        from resolvekit.core.model import NormalizedText, Query, ResolutionContext

        router = ExplicitRouter(available_packs=["geo", "org"])

        query = Query(
            raw_text="Paris",
            normalized=NormalizedText(original="Paris", normalized="paris"),
        )

        decision = router.route(query, ResolutionContext())

        # No explicit request → all packs
        assert set(decision.target_packs) == {"geo", "org"}
