"""Tests for EntityRecord and related models."""

from datetime import date


class TestNameRecord:
    def test_create_name_record(self):
        from resolvekit.core.model.entity import NameRecord

        nr = NameRecord(
            value="United States of America",
            value_norm="united states of america",
            kind="canonical",
            lang="en",
            is_preferred=True,
        )
        assert nr.value == "United States of America"
        assert nr.value_norm == "united states of america"
        assert nr.kind == "canonical"
        assert nr.lang == "en"
        assert nr.is_preferred is True

    def test_name_record_minimal(self):
        from resolvekit.core.model.entity import NameRecord

        nr = NameRecord(
            value="USA",
            value_norm="usa",
            kind="abbr",
        )
        assert nr.lang is None
        assert nr.script is None
        assert nr.is_preferred is False


class TestCodeRecord:
    def test_create_code_record(self):
        from resolvekit.core.model.entity import CodeRecord

        cr = CodeRecord(
            system="iso3166-1",
            value="US",
            value_norm="us",
        )
        assert cr.system == "iso3166-1"
        assert cr.value == "US"
        assert cr.value_norm == "us"


class TestRelationRecord:
    def test_create_relation_record(self):
        from resolvekit.core.model.entity import RelationRecord

        rr = RelationRecord(
            relation_type="contained_in",
            target_id="country/USA",
        )
        assert rr.relation_type == "contained_in"
        assert rr.target_id == "country/USA"


class TestEntityRecord:
    def test_create_entity_record_minimal(self):
        from resolvekit.core.model.entity import EntityRecord

        er = EntityRecord(
            entity_id="country/USA",
            entity_type="geo.country",
            canonical_name="United States of America",
            canonical_name_norm="united states of america",
        )
        assert er.entity_id == "country/USA"
        assert er.entity_type == "geo.country"
        assert er.canonical_name == "United States of America"
        assert er.names == []
        assert er.codes == []
        assert er.relations == []
        assert er.attributes == {}

    def test_create_entity_record_full(self):
        from resolvekit.core.model.entity import (
            CodeRecord,
            EntityRecord,
            NameRecord,
            RelationRecord,
        )

        er = EntityRecord(
            entity_id="country/USA",
            entity_type="geo.country",
            canonical_name="United States of America",
            canonical_name_norm="united states of america",
            names=[
                NameRecord(value="USA", value_norm="usa", kind="abbr"),
                NameRecord(value="America", value_norm="america", kind="alias"),
            ],
            codes=[
                CodeRecord(system="iso2", value="US", value_norm="us"),
                CodeRecord(system="iso3", value="USA", value_norm="usa"),
            ],
            relations=[
                RelationRecord(
                    relation_type="contained_in", target_id="continent/NorthAmerica"
                ),
            ],
            valid_from=date(1776, 7, 4),
            valid_until=None,
            attributes={"population": 331000000},
        )
        assert len(er.names) == 2
        assert len(er.codes) == 2
        assert len(er.relations) == 1
        assert er.valid_from == date(1776, 7, 4)
        assert er.attributes["population"] == 331000000
