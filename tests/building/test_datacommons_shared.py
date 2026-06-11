"""Unit tests for shared Data Commons entity-pipeline helpers."""

from __future__ import annotations

from resolvekit.builder.sources.datacommons import (
    DataCommonsDomainProfile,
    build_raw_chunk,
    normalize_bundle_to_rows,
)
from resolvekit.builder.sources.datacommons.org import ORG_DOMAIN_PROFILE


def test_normalize_bundle_to_rows_builds_canonical_tables() -> None:
    profile = DataCommonsDomainProfile(
        domain="demo",
        entity_type_mapper=lambda value, attrs: f"demo.{value.casefold()}",
        alias_kind_mapper=lambda value: value.casefold(),
        code_system_mapper=lambda value: value.casefold(),
        default_relation_type="related_to",
    )

    raw_chunk = build_raw_chunk(
        entity_ids=["demo/1"],
        canonical_names={"demo/1": "Acme"},
        entity_types={"demo/1": "Company"},
        attrs_by_entity={"demo/1": {"country_code": "US"}},
        aliases_by_entity={
            "demo/1": [
                {
                    "alias_text": "ACME",
                    "language": "en",
                    "alias_type": "short",
                }
            ]
        },
        codes_by_entity={
            "demo/1": [
                {
                    "code_system": "Wikidata",
                    "code_value": "Q123",
                }
            ]
        },
        relations_by_entity={
            "demo/1": [
                {
                    "relation_type": "subsidiary_of",
                    "target_id": "demo/parent",
                }
            ]
        },
    )

    rows = normalize_bundle_to_rows(
        domain="demo",
        raw_chunk=raw_chunk,
        profile=profile,
        text_normalize=str.casefold,
    )
    payload = rows.model_dump(mode="python")

    assert payload["entities"][0]["entity_type"] == "demo.company"
    assert payload["entities"][0]["attrs_json"]["country_code"] == "US"
    assert any(row["name_kind"] == "canonical" for row in payload["names"])
    assert any(row["name_kind"] == "short" for row in payload["names"])
    assert any(row["system"] == "wikidata" for row in payload["codes"])
    # This test exercises normalization only; canonicalization (target_id rewriting
    # and unmodeled-prefix drops) is covered in tests/building/test_datacommons_canonicalize.py.
    assert payload["relations"] == [
        {
            "entity_id": "demo/1",
            "relation_type": "subsidiary_of",
            "target_id": "demo/parent",
            "valid_from": None,
            "valid_until": None,
        }
    ]


def test_normalize_bundle_to_rows_uses_injected_code_normalizer() -> None:
    """The write-side value_norm must match the query-side code normalizer.

    OrgNormalizer strips DUNS dashes; the DataCommons adapter injects it via
    ``code_normalize`` so a dashed DUNS round-trips through ``entity(duns=...)``.
    The default (base, casefold-only) normalizer would store the dashes and miss.
    """
    from resolvekit.core.linking.base_normalizer import BaseNormalizer
    from resolvekit.packs.org.normalizer import OrgNormalizer

    profile = DataCommonsDomainProfile(
        domain="demo",
        entity_type_mapper=lambda value, attrs: f"demo.{value.casefold()}",
        alias_kind_mapper=lambda value: value.casefold(),
        code_system_mapper=lambda value: value.casefold(),
        default_relation_type="related_to",
    )
    raw_chunk = build_raw_chunk(
        entity_ids=["demo/1"],
        canonical_names={"demo/1": "Acme"},
        entity_types={"demo/1": "Company"},
        codes_by_entity={
            "demo/1": [{"code_system": "duns", "code_value": "06-100-7705"}]
        },
    )

    def duns_value_norm(code_normalize) -> str:
        rows = normalize_bundle_to_rows(
            domain="demo",
            raw_chunk=raw_chunk,
            profile=profile,
            text_normalize=str.casefold,
            code_normalize=code_normalize,
        )
        codes = rows.model_dump(mode="python")["codes"]
        return next(row["value_norm"] for row in codes if row["system"] == "duns")

    assert duns_value_norm(OrgNormalizer().normalize_code) == "061007705"
    # Default normalizer keeps the dashes — which is exactly the read/write
    # divergence the adapter's injection prevents.
    assert duns_value_norm(BaseNormalizer().normalize_code) == "06-100-7705"


def test_org_profile_maps_expected_name_kinds() -> None:
    assert ORG_DOMAIN_PROFILE.alias_kind_mapper("short_name") == "short"
    assert ORG_DOMAIN_PROFILE.alias_kind_mapper("legal_name") == "legal"
    assert ORG_DOMAIN_PROFILE.alias_kind_mapper("abbr") == "acronym"


def test_org_profile_maps_bounded_raw_types() -> None:
    assert (
        ORG_DOMAIN_PROFILE.entity_type_mapper("DevelopmentFinanceProviderEnum", {})
        == "org.development_finance_provider"
    )
    assert ORG_DOMAIN_PROFILE.entity_type_mapper("LendingEntityEnum", {}) == (
        "org.lending_entity"
    )


def test_org_profile_maps_new_code_systems() -> None:
    assert ORG_DOMAIN_PROFILE.code_system_mapper("dacCodeStr") == "dac"
    assert ORG_DOMAIN_PROFILE.code_system_mapper("dacCodeInt") == "dac_numeric"
    assert ORG_DOMAIN_PROFILE.code_system_mapper("unDataCode") == "undata"


def test_normalize_bundle_to_rows_falls_back_to_entity_id_for_blank_canonical_name() -> (
    None
):
    profile = DataCommonsDomainProfile(
        domain="demo",
        entity_type_mapper=lambda value, attrs: value,
        alias_kind_mapper=lambda value: value.casefold(),
        code_system_mapper=lambda value: value.casefold(),
        default_relation_type="related_to",
    )

    raw_chunk = build_raw_chunk(
        entity_ids=["wikidataId/Q1"],
        canonical_names={},
        entity_types={"wikidataId/Q1": "Country"},
    )

    rows = normalize_bundle_to_rows(
        domain="demo",
        raw_chunk=raw_chunk,
        profile=profile,
        text_normalize=str.casefold,
    ).model_dump(mode="python")

    assert rows["entities"] == [
        {
            "entity_id": "wikidataId/Q1",
            "entity_type": "Country",
            "canonical_name": "wikidataId/Q1",
            "canonical_name_norm": "wikidataid/q1",
            "valid_from": None,
            "valid_until": None,
            "attrs_json": {},
        }
    ]
    assert any(
        row["entity_id"] == "wikidataId/Q1"
        and row["name_kind"] == "canonical"
        and row["value"] == "wikidataId/Q1"
        for row in rows["names"]
    )


def test_normalize_bundle_to_rows_can_use_attrs_for_entity_classification() -> None:
    profile = DataCommonsDomainProfile(
        domain="demo",
        entity_type_mapper=(
            lambda value, attrs: (
                f"demo.admin{attrs['admin_level']}"
                if value == "AdministrativeArea"
                else f"demo.{value.casefold()}"
            )
        ),
        alias_kind_mapper=lambda value: value.casefold(),
        code_system_mapper=lambda value: value.casefold(),
        default_relation_type="related_to",
    )

    raw_chunk = build_raw_chunk(
        entity_ids=["admin/demo"],
        canonical_names={"admin/demo": "Demo Admin"},
        entity_types={"admin/demo": "AdministrativeArea"},
        attrs_by_entity={"admin/demo": {"admin_level": 2}},
    )

    rows = normalize_bundle_to_rows(
        domain="demo",
        raw_chunk=raw_chunk,
        profile=profile,
        text_normalize=str.casefold,
    ).model_dump(mode="python")

    assert rows["entities"][0]["entity_type"] == "demo.admin2"
