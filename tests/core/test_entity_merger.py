"""Tests for EntityMerger."""

from datetime import date

from resolvekit.core.model.entity import (
    CodeRecord,
    EntityRecord,
    NameRecord,
    RelationRecord,
)


class MockNormalizer:
    """Mock normalizer for testing EntityMerger."""

    def normalize_name(self, value: str) -> str:
        return value.lower().strip()

    def normalize_code(self, system: str, value: str) -> str:
        return value.upper().strip()


class TestEntityMerger:
    """Tests for EntityMerger."""

    def test_merge_replaces_scalar_fields(self):
        """Later pack's scalar fields replace earlier pack's."""
        from resolvekit.core.merge import EntityMerger

        base = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
        )

        overlay = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="French Republic",
            canonical_name_norm="french republic",
        )

        merger = EntityMerger(MockNormalizer())
        merged = merger.merge(base, overlay)

        assert merged.canonical_name == "French Republic"
        assert merged.canonical_name_norm == "french republic"

    def test_merge_unions_names_with_dedup(self):
        """Names from both packs are unioned, duplicates removed."""
        from resolvekit.core.merge import EntityMerger

        base = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            names=[
                NameRecord(
                    value="France", value_norm="france", kind="canonical", lang="en"
                ),
                NameRecord(
                    value="La France", value_norm="la france", kind="endonym", lang="fr"
                ),
            ],
        )

        overlay = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            names=[
                NameRecord(
                    value="France", value_norm="france", kind="canonical", lang="en"
                ),  # Duplicate
                NameRecord(
                    value="République française",
                    value_norm="république française",
                    kind="official",
                    lang="fr",
                ),
            ],
        )

        merger = EntityMerger(MockNormalizer())
        merged = merger.merge(base, overlay)

        # Should have 3 unique names, not 4
        assert len(merged.names) == 3
        name_values = {n.value for n in merged.names}
        assert name_values == {"France", "La France", "République française"}

    def test_merge_unions_codes_with_dedup(self):
        """Codes from both packs are unioned, duplicates removed."""
        from resolvekit.core.merge import EntityMerger

        base = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            codes=[
                CodeRecord(system="iso3", value="FRA", value_norm="FRA"),
                CodeRecord(system="iso2", value="FR", value_norm="FR"),
            ],
        )

        overlay = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            codes=[
                CodeRecord(system="iso3", value="FRA", value_norm="FRA"),  # Duplicate
                CodeRecord(system="geonameid", value="3017382", value_norm="3017382"),
            ],
        )

        merger = EntityMerger(MockNormalizer())
        merged = merger.merge(base, overlay)

        # Should have 3 unique codes
        assert len(merged.codes) == 3
        code_systems = {c.system for c in merged.codes}
        assert code_systems == {"iso3", "iso2", "geonameid"}

    def test_merge_unions_relations_with_dedup(self):
        """Relations from both packs are unioned, duplicates removed."""
        from resolvekit.core.merge import EntityMerger

        base = EntityRecord(
            entity_id="geo/Paris",
            entity_type="geo.city",
            canonical_name="Paris",
            canonical_name_norm="paris",
            relations=[
                RelationRecord(relation_type="contained_in", target_id="geo/FRA"),
            ],
        )

        overlay = EntityRecord(
            entity_id="geo/Paris",
            entity_type="geo.city",
            canonical_name="Paris",
            canonical_name_norm="paris",
            relations=[
                RelationRecord(
                    relation_type="contained_in", target_id="geo/FRA"
                ),  # Duplicate
                RelationRecord(
                    relation_type="contained_in", target_id="geo/IDF"
                ),  # Ile-de-France
            ],
        )

        merger = EntityMerger(MockNormalizer())
        merged = merger.merge(base, overlay)

        # Should have 2 unique relations
        assert len(merged.relations) == 2
        targets = {r.target_id for r in merged.relations}
        assert targets == {"geo/FRA", "geo/IDF"}

    def test_merge_deep_merges_attributes(self):
        """Attributes are deep merged, overlay wins on conflict."""
        from resolvekit.core.merge import EntityMerger

        base = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            attributes={"population": 67000000, "area_km2": 643801},
        )

        overlay = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            attributes={"population": 68000000, "gdp_usd": 2700000000000},  # Updated
        )

        merger = EntityMerger(MockNormalizer())
        merged = merger.merge(base, overlay)

        assert merged.attributes["population"] == 68000000  # Overlay wins
        assert merged.attributes["area_km2"] == 643801  # Base preserved
        assert merged.attributes["gdp_usd"] == 2700000000000  # New from overlay

    def test_merge_preserves_dates_from_overlay(self):
        """Date fields from overlay take precedence."""
        from resolvekit.core.merge import EntityMerger

        base = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            valid_from=date(1789, 1, 1),
        )

        overlay = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            valid_from=date(1958, 10, 4),  # Fifth Republic
        )

        merger = EntityMerger(MockNormalizer())
        merged = merger.merge(base, overlay)

        assert merged.valid_from == date(1958, 10, 4)

    def test_merge_keeps_base_dates_when_overlay_null(self):
        """Base date fields preserved when overlay has None."""
        from resolvekit.core.merge import EntityMerger

        base = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            valid_from=date(1789, 1, 1),
            valid_until=None,
        )

        overlay = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            valid_from=None,  # Not specified
            valid_until=None,
        )

        merger = EntityMerger(MockNormalizer())
        merged = merger.merge(base, overlay)

        # Base date preserved since overlay is None
        assert merged.valid_from == date(1789, 1, 1)

    def test_merge_preserves_entity_id_and_type(self):
        """entity_id and entity_type are preserved from base."""
        from resolvekit.core.merge import EntityMerger

        base = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
        )

        overlay = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="French Republic",
            canonical_name_norm="french republic",
        )

        merger = EntityMerger(MockNormalizer())
        merged = merger.merge(base, overlay)

        assert merged.entity_id == "geo/FRA"
        assert merged.entity_type == "geo.country"

    def test_merge_chain_multiple_overlays(self):
        """Multiple overlays can be merged in sequence."""
        from resolvekit.core.merge import EntityMerger

        base = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            attributes={"population": 65000000},
        )

        overlay1 = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            attributes={"population": 67000000, "gdp_usd": 2500000000000},
        )

        overlay2 = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="French Republic",
            canonical_name_norm="french republic",
            attributes={"gdp_usd": 2700000000000},  # Updated
        )

        merger = EntityMerger(MockNormalizer())
        merged = merger.merge(base, overlay1)
        merged = merger.merge(merged, overlay2)

        assert merged.canonical_name == "French Republic"
        assert merged.attributes["population"] == 67000000
        assert merged.attributes["gdp_usd"] == 2700000000000

    def test_merge_name_dedup_uses_normalizer(self):
        """Name deduplication uses normalizer for comparison."""
        from resolvekit.core.merge import EntityMerger

        base = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            names=[
                NameRecord(
                    value="FRANCE", value_norm="france", kind="canonical", lang="en"
                ),
            ],
        )

        overlay = EntityRecord(
            entity_id="geo/FRA",
            entity_type="geo.country",
            canonical_name="France",
            canonical_name_norm="france",
            names=[
                NameRecord(
                    value="france", value_norm="france", kind="canonical", lang="en"
                ),  # Same normalized
            ],
        )

        merger = EntityMerger(MockNormalizer())
        merged = merger.merge(base, overlay)

        # Should dedupe because normalized values match
        assert len(merged.names) == 1
