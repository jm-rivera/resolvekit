"""Tests for Normalizer protocol."""

from resolvekit.core.linking import Normalizer


class TestNormalizerProtocol:
    """Tests for Normalizer protocol compliance."""

    def test_protocol_is_runtime_checkable(self):
        """Normalizer protocol can be used with isinstance()."""
        assert hasattr(Normalizer, "__protocol_attrs__") or hasattr(
            Normalizer, "_is_protocol"
        )

    def test_mock_normalizer_satisfies_protocol(self):
        """A class implementing both methods satisfies Normalizer protocol."""

        class MockNormalizer:
            def normalize_name(self, value: str) -> str:
                return value.lower()

            def normalize_code(self, system: str, value: str) -> str:
                return value.upper()

        normalizer = MockNormalizer()
        assert isinstance(normalizer, Normalizer)

    def test_partial_implementation_does_not_satisfy(self):
        """A class with only normalize_name does not satisfy Normalizer."""

        class PartialNormalizer:
            def normalize_name(self, value: str) -> str:
                return value.lower()

        assert not isinstance(PartialNormalizer(), Normalizer)

    def test_empty_class_does_not_satisfy(self):
        """An empty class does not satisfy Normalizer."""

        class Empty:
            pass

        assert not isinstance(Empty(), Normalizer)
