"""Tests for hybrid routing."""


class TestHybridRouter:
    """Tests for hybrid routing mode."""

    def test_always_routes_to_all_packs(self):
        from resolvekit.core.engine import HybridRouter
        from resolvekit.core.model import NormalizedText, Query, ResolutionContext

        router = HybridRouter(packs=["geo", "org"])

        query = Query(
            raw_text="EU",
            normalized=NormalizedText(original="EU", normalized="eu"),
        )

        decision = router.route(query, ResolutionContext())

        assert set(decision.target_packs) == {"geo", "org"}
        assert decision.reason == "Hybrid mode: running all packs"

    def test_respects_explicit_request(self):
        from resolvekit.core.engine import HybridRouter
        from resolvekit.core.model import NormalizedText, Query, ResolutionContext

        router = HybridRouter(packs=["geo", "org"])

        query = Query(
            raw_text="Paris",
            normalized=NormalizedText(original="Paris", normalized="paris"),
            domains={"geo"},  # Explicit
        )

        decision = router.route(query, ResolutionContext())

        # Explicit request should be honored even in hybrid
        assert decision.target_packs == ["geo"]
