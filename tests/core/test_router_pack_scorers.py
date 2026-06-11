"""Tests for AutoRouter pack-declared scorer wiring.

Verifies that AutoRouter reads scoring_fn from RoutingHints.
"""

from __future__ import annotations

import ast
from pathlib import Path


class TestPackDeclaredScorers:
    """AutoRouter wires scoring_fn from RoutingHints, not from pack-ID strings."""

    def _make_router(self, scoring_fn=None):
        from resolvekit.core.engine import AutoRouter
        from resolvekit.core.registry import RoutingHints

        hints = RoutingHints(
            type_prefixes=["synth"],
            keywords=["synth"],
            scoring_fn=scoring_fn,
        )
        return AutoRouter(
            available_packs=["synth"],
            pack_hints={"synth": hints},
        )

    def test_pack_declared_scorer_is_called(self):
        """A pack that declares scoring_fn should have it invoked by AutoRouter."""
        calls: list[tuple[str, str]] = []

        def my_scorer(text: str, text_lower: str) -> float:
            calls.append((text, text_lower))
            return 0.9

        from resolvekit.core.model import NormalizedText, Query, ResolutionContext

        router = self._make_router(scoring_fn=my_scorer)
        query = Query(
            raw_text="SynthCorp",
            normalized=NormalizedText(original="SynthCorp", normalized="synthcorp"),
        )
        decision = router.route(query, ResolutionContext())

        assert calls, "scoring_fn was never called"
        assert calls[0] == ("SynthCorp", "synthcorp")
        assert decision.target_packs == ["synth"]

    def test_pack_declared_scorer_determines_routing(self):
        """High-confidence pack scorer routes exclusively to that pack."""
        from resolvekit.core.engine import AutoRouter
        from resolvekit.core.model import NormalizedText, Query, ResolutionContext
        from resolvekit.core.registry import RoutingHints

        # alpha always wins; beta always loses
        alpha_hints = RoutingHints(
            type_prefixes=["alpha"], scoring_fn=lambda t, tl: 0.95
        )
        beta_hints = RoutingHints(type_prefixes=["beta"], scoring_fn=lambda t, tl: 0.1)
        router = AutoRouter(
            available_packs=["alpha", "beta"],
            pack_hints={"alpha": alpha_hints, "beta": beta_hints},
        )
        query = Query(
            raw_text="anything",
            normalized=NormalizedText(original="anything", normalized="anything"),
        )
        decision = router.route(query, ResolutionContext())

        assert decision.target_packs == ["alpha"], (
            f"Expected ['alpha'] but got {decision.target_packs}"
        )

    def test_explicit_pack_scorers_override_pack_declared(self):
        """Constructor pack_scorers arg must override RoutingHints.scoring_fn."""
        from resolvekit.core.engine import AutoRouter
        from resolvekit.core.model import NormalizedText, Query, ResolutionContext
        from resolvekit.core.registry import RoutingHints

        declared_calls: list[str] = []
        override_calls: list[str] = []

        def declared_scorer(text: str, text_lower: str) -> float:
            declared_calls.append(text)
            return 0.5

        def override_scorer(text: str, text_lower: str) -> float:
            override_calls.append(text)
            return 0.8

        hints = RoutingHints(type_prefixes=["p"], scoring_fn=declared_scorer)
        router = AutoRouter(
            available_packs=["p"],
            pack_hints={"p": hints},
            pack_scorers={"p": override_scorer},
        )
        query = Query(
            raw_text="test",
            normalized=NormalizedText(original="test", normalized="test"),
        )
        router.route(query, ResolutionContext())

        assert override_calls, "override scorer was not called"
        assert not declared_calls, "declared scorer should have been bypassed"

    def test_pack_without_scoring_fn_falls_back_to_score_pack(self):
        """Packs without scoring_fn fall through to _score_pack (keyword hints)."""
        from resolvekit.core.engine import AutoRouter
        from resolvekit.core.model import NormalizedText, Query, ResolutionContext
        from resolvekit.core.registry import RoutingHints

        # keyword-only hints; no scoring_fn
        hints = RoutingHints(type_prefixes=["kw"], keywords=["foundation"])
        router = AutoRouter(
            available_packs=["kw"],
            pack_hints={"kw": hints},
        )
        # "foundation" is in the query → keyword hit adds 0.2 over base 0.4 = 0.6
        query = Query(
            raw_text="Gates Foundation",
            normalized=NormalizedText(
                original="Gates Foundation", normalized="gates foundation"
            ),
        )
        decision = router.route(query, ResolutionContext())

        assert decision.target_packs == ["kw"]
        assert decision.confidence >= 0.5


class TestNoPackIdLiteralsInRouter:
    """Guard: router.py must contain no pack-ID-literal scorer dispatch."""

    def test_no_geo_org_hardcoded_dispatch(self):
        """router.py must not contain pack_id == 'geo' / 'org' branches."""
        router_src = (
            Path(__file__).parent.parent.parent
            / "src"
            / "resolvekit"
            / "core"
            / "engine"
            / "router.py"
        ).read_text()

        tree = ast.parse(router_src)

        violations: list[str] = []
        for node in ast.walk(tree):
            # Detect comparisons: pack_id == "geo" / "org"
            if isinstance(node, ast.Compare):
                for comparator in node.comparators:
                    if isinstance(comparator, ast.Constant) and comparator.value in (
                        "geo",
                        "org",
                    ):
                        violations.append(
                            f"line {node.lineno}: hardcoded pack-ID comparison"
                        )

        assert not violations, (
            "router.py still contains hardcoded pack-ID dispatch:\n"
            + "\n".join(violations)
        )
