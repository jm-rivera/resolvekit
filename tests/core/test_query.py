"""Tests for Query and ResolutionContext models."""

from datetime import date

import pytest
from pydantic import ValidationError


class TestNormalizedText:
    """Tests for NormalizedText value object."""

    def test_create_normalized_text(self):
        from resolvekit.core.model.query import NormalizedText

        nt = NormalizedText(original="United States", normalized="united states")
        assert nt.original == "United States"
        assert nt.normalized == "united states"

    def test_normalized_text_immutable(self):
        from resolvekit.core.model.query import NormalizedText

        nt = NormalizedText(original="Test", normalized="test")
        with pytest.raises(ValidationError):
            nt.original = "Changed"


class TestQuery:
    """Tests for Query model."""

    def test_create_query_minimal(self):
        from resolvekit.core.model.query import NormalizedText, Query

        q = Query(
            raw_text="USA",
            normalized=NormalizedText(original="USA", normalized="usa"),
        )
        assert q.raw_text == "USA"
        assert q.normalized.normalized == "usa"
        assert q.query_id is not None  # Auto-generated
        assert q.domains is None

    def test_create_query_with_types(self):
        from resolvekit.core.model.query import NormalizedText, Query

        q = Query(
            raw_text="Paris",
            normalized=NormalizedText(original="Paris", normalized="paris"),
            domains={"geo"},
        )
        assert q.domains == {"geo"}

    def test_query_id_is_unique(self):
        from resolvekit.core.model.query import NormalizedText, Query

        q1 = Query(
            raw_text="A",
            normalized=NormalizedText(original="A", normalized="a"),
        )
        q2 = Query(
            raw_text="B",
            normalized=NormalizedText(original="B", normalized="b"),
        )
        assert q1.query_id != q2.query_id


class TestContext:
    """Tests for ResolutionContext model."""

    def test_create_context_empty(self):
        from resolvekit.core.model.query import ResolutionContext

        ctx = ResolutionContext()
        assert ctx.as_of is None
        assert ctx.entity_types is None
        assert ctx.parent_ids is None
        assert ctx.country is None
        assert ctx.languages is None
        assert ctx.attributes == {}

    def test_create_context_with_values(self):
        from resolvekit.core.model.query import ResolutionContext

        ctx = ResolutionContext(
            as_of=date(2024, 1, 15),
            entity_types={"geo.country"},
            parent_ids=["country/USA"],
            country="US",
            languages=["en", "es"],
            attributes={"custom_key": "custom_value"},
        )
        assert ctx.as_of == date(2024, 1, 15)
        assert ctx.entity_types == {"geo.country"}
        assert ctx.parent_ids == ["country/USA"]
        assert ctx.country == "US"
        assert ctx.languages == ["en", "es"]
        assert ctx.attributes == {"custom_key": "custom_value"}

    def test_context_attributes_type_restricted(self):
        from resolvekit.core.model.query import ResolutionContext

        # Valid attribute types
        ctx = ResolutionContext(
            attributes={
                "str_val": "hello",
                "int_val": 42,
                "float_val": 3.14,
                "bool_val": True,
            }
        )
        assert ctx.attributes["int_val"] == 42

    def test_entity_types_is_frozenset(self):
        from resolvekit.core.model.query import ResolutionContext

        ctx = ResolutionContext(entity_types={"geo.country", "geo.state"})
        assert isinstance(ctx.entity_types, frozenset)
        assert "geo.country" in ctx.entity_types

    def test_entity_types_coerced_from_set(self):
        from resolvekit.core.model.query import ResolutionContext

        ctx = ResolutionContext(entity_types={"a", "b"})
        assert isinstance(ctx.entity_types, frozenset)

    def test_replace_returns_new_instance(self):
        from resolvekit.core.model.query import ResolutionContext

        ctx = ResolutionContext(country="US")
        ctx2 = ctx.replace(country="GB")
        assert ctx2.country == "GB"
        assert ctx.country == "US"

    def test_replace_preserves_other_fields(self):
        from resolvekit.core.model.query import ResolutionContext

        ctx = ResolutionContext(country="US", languages=["en"])
        ctx2 = ctx.replace(country="GB")
        assert ctx2.languages == ["en"]

    def test_replace_with_entity_types(self):
        from resolvekit.core.model.query import ResolutionContext

        ctx = ResolutionContext()
        ctx2 = ctx.replace(entity_types={"geo.country"})
        assert isinstance(ctx2.entity_types, frozenset)
        assert "geo.country" in ctx2.entity_types

    def test_replace_rejects_invalid_types(self):
        from resolvekit.core.model.query import ResolutionContext

        ctx = ResolutionContext()
        with pytest.raises(ValidationError):
            ctx.replace(country=123)

    def test_replace_rejects_bare_string_entity_types(self):
        from resolvekit.core.model.query import ResolutionContext

        ctx = ResolutionContext()
        with pytest.raises(ValidationError):
            ctx.replace(entity_types="geo.country")

    def test_context_constructor_rejects_bare_string_entity_types(self):
        from resolvekit.core.model.query import ResolutionContext

        with pytest.raises(ValidationError):
            ResolutionContext(entity_types="geo.country")

    def test_replace_deep_copies_mutable_fields(self):
        from resolvekit.core.model.query import ResolutionContext

        ctx = ResolutionContext(
            parent_ids=["country/USA"],
            languages=["en"],
            attributes={"source": "crm"},
        )
        ctx2 = ctx.replace(country="GB")

        assert ctx2.parent_ids is not None and ctx2.languages is not None
        ctx2.parent_ids.append("country/GBR")
        ctx2.languages.append("fr")
        ctx2.attributes["source"] = "api"

        assert ctx.parent_ids == ["country/USA"]
        assert ctx.languages == ["en"]
        assert ctx.attributes == {"source": "crm"}

    def test_country_alpha2_accepted(self):
        from resolvekit.core.model.query import ResolutionContext

        ctx = ResolutionContext(country="US")
        assert ctx.country == "US"

    def test_country_alpha3_accepted(self):
        from resolvekit.core.model.query import ResolutionContext

        ctx = ResolutionContext(country="USA")
        assert ctx.country == "USA"

    def test_country_lowercase_normalised_to_upper(self):
        from resolvekit.core.model.query import ResolutionContext

        ctx2 = ResolutionContext(country="us")
        assert ctx2.country == "US"
        ctx3 = ResolutionContext(country="usa")
        assert ctx3.country == "USA"

    def test_country_single_char_rejected(self):
        from resolvekit.core.model.query import ResolutionContext

        with pytest.raises(ValidationError):
            ResolutionContext(country="U")

    def test_country_empty_string_rejected(self):
        from resolvekit.core.model.query import ResolutionContext

        with pytest.raises(ValidationError):
            ResolutionContext(country="")

    def test_country_nonalpha_rejected(self):
        from resolvekit.core.model.query import ResolutionContext

        with pytest.raises(ValidationError):
            ResolutionContext(country="1!")

    def test_country_four_char_rejected(self):
        from resolvekit.core.model.query import ResolutionContext

        with pytest.raises(ValidationError):
            ResolutionContext(country="USAA")
