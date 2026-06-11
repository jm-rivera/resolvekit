"""Tests for engine interfaces (CandidateSource, Constraint, etc.)."""


class TestCandidateSourceInterface:
    def test_interface_defines_required_methods(self):
        from resolvekit.core.engine.interfaces import CandidateSource

        # Check required attributes/methods
        assert hasattr(CandidateSource, "name")
        assert hasattr(CandidateSource, "supports")
        assert hasattr(CandidateSource, "generate")

    def test_mock_source_implements_interface(self):
        from resolvekit.core.engine.interfaces import CandidateSource
        from resolvekit.core.explain import TraceSink
        from resolvekit.core.model import CandidateEvidence, Query, ResolutionContext
        from resolvekit.core.store import EntityStore

        class MockCodeSource(CandidateSource):
            @property
            def name(self) -> str:
                return "mock_code"

            def supports(self, domain_pack_id: str) -> bool:
                return domain_pack_id == "geo"

            @property
            def requires_existing_candidates(self) -> bool:
                return False

            def generate(
                self,
                query: Query,
                context: ResolutionContext,
                store: EntityStore,
                budget: int,
                trace: TraceSink,
                existing_candidates=None,
            ) -> list[CandidateEvidence]:
                return [
                    CandidateEvidence(
                        entity_id="country/USA",
                        source_name=self.name,
                        raw_score=1.0,
                        rank=1,
                        matched_field="code.iso2",
                        matched_value="US",
                    )
                ]

        source = MockCodeSource()
        assert source.name == "mock_code"
        assert source.supports("geo") is True
        assert source.supports("org") is False


class TestConstraintInterface:
    def test_interface_defines_required_methods(self):
        from resolvekit.core.engine.interfaces import Constraint

        assert hasattr(Constraint, "name")
        assert hasattr(Constraint, "apply")


class TestDecisionPolicyInterface:
    def test_interface_defines_required_methods(self):
        from resolvekit.core.engine.interfaces import DecisionPolicy

        assert hasattr(DecisionPolicy, "decide")
