"""Tests for Linker protocol and LinkResult."""

import pytest

from resolvekit.core.linking import Linker, LinkResult


class TestLinkResult:
    """Tests for LinkResult dataclass."""

    def test_linked_factory(self):
        """linked() creates result with status=linked and entity_id."""
        result = LinkResult.linked("geo/FRA")
        assert result.status == "linked"
        assert result.entity_id == "geo/FRA"
        assert result.candidates == ()
        assert result.message is None

    def test_not_found_factory(self):
        """not_found() creates result with status=not_found."""
        result = LinkResult.not_found()
        assert result.status == "not_found"
        assert result.entity_id is None
        assert result.candidates == ()

    def test_not_found_with_message(self):
        """not_found() can include a message."""
        result = LinkResult.not_found("No match for iso3=XXX")
        assert result.status == "not_found"
        assert result.message == "No match for iso3=XXX"

    def test_ambiguous_factory(self):
        """ambiguous() creates result with status=ambiguous and candidates."""
        result = LinkResult.ambiguous(("geo/USA", "geo/USA-historical"))
        assert result.status == "ambiguous"
        assert result.entity_id is None
        assert result.candidates == ("geo/USA", "geo/USA-historical")

    def test_ambiguous_with_message(self):
        """ambiguous() can include a message."""
        result = LinkResult.ambiguous(
            ("geo/USA", "geo/USA-historical"),
            "Multiple entities match iso3=USA",
        )
        assert result.status == "ambiguous"
        assert result.message == "Multiple entities match iso3=USA"

    def test_invalid_key_factory(self):
        """invalid_key() creates result with status=invalid_key."""
        result = LinkResult.invalid_key("Unknown code system: iso99")
        assert result.status == "invalid_key"
        assert result.entity_id is None
        assert result.message == "Unknown code system: iso99"

    def test_is_frozen(self):
        """LinkResult is immutable."""
        result = LinkResult.linked("geo/FRA")
        with pytest.raises(AttributeError):
            result.entity_id = "geo/USA"

    def test_is_success_property(self):
        """is_success returns True only for linked status."""
        assert LinkResult.linked("geo/FRA").is_success is True
        assert LinkResult.not_found().is_success is False
        assert LinkResult.ambiguous(("a", "b")).is_success is False
        assert LinkResult.invalid_key("error").is_success is False


class TestLinkerProtocol:
    """Tests for Linker protocol compliance."""

    def test_protocol_is_runtime_checkable(self):
        """Linker protocol can be used with isinstance()."""
        # This should not raise
        assert hasattr(Linker, "__protocol_attrs__") or hasattr(Linker, "_is_protocol")

    def test_mock_linker_satisfies_protocol(self):
        """A class implementing resolve_link satisfies Linker protocol."""

        class MockLinker:
            def resolve_link(
                self,
                overlay_row: dict,
                link_keys: list[str],
                base_store,
            ) -> LinkResult:
                return LinkResult.linked("test/entity")

        linker = MockLinker()
        assert isinstance(linker, Linker)

    def test_missing_method_does_not_satisfy(self):
        """A class without resolve_link does not satisfy Linker."""

        class NotALinker:
            pass

        assert not isinstance(NotALinker(), Linker)
