"""Tests for the Explainer protocol.

Asserts that a live Resolver structurally satisfies Explainer via
runtime_checkable isinstance, and that a bare object does not.
"""

from resolvekit.core.explain.protocol import Explainer


class TestExplainerProtocol:
    """Structural isinstance checks via runtime_checkable Protocol."""

    def test_bare_object_does_not_satisfy_explainer(self):
        assert not isinstance(object(), Explainer)

    def test_object_without_resolve_explained_does_not_satisfy(self):
        class NotAnExplainer:
            def resolve(self, text: str) -> None: ...

        assert not isinstance(NotAnExplainer(), Explainer)

    def test_object_with_resolve_explained_satisfies_explainer(self):
        """Structural conformance: any object with the right method qualifies."""

        class FakeExplainer:
            def resolve_explained(self, text: str, **kwargs): ...

        assert isinstance(FakeExplainer(), Explainer)

    def test_resolver_satisfies_explainer(self):
        """Live Resolver satisfies Explainer structurally (no pack load needed)."""
        from unittest.mock import MagicMock

        from resolvekit.core.api.resolver import Resolver

        runner = MagicMock()
        runner.available_packs.return_value = []
        resolver = Resolver(runner=runner)
        assert isinstance(resolver, Explainer)
