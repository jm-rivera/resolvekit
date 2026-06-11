"""Tests for schema-driven Data Commons org source behavior."""

from __future__ import annotations

from types import MethodType, SimpleNamespace
from typing import Any, cast

from resolvekit.builder.sources.datacommons.client import DataCommons
from resolvekit.builder.sources.datacommons.models import FetchedName
from resolvekit.builder.sources.datacommons.org import DataCommonsOrgSourceAdapter
from resolvekit.builder.sources.datacommons.org.dc_api import OrgDcApi
from resolvekit.builder.sources.datacommons.org.discovery import (
    discover_entities,
    discover_entities_filtered,
)


class _FakeRuntime:
    def __init__(
        self,
        payload: dict[str, dict[str, list[Any]]],
        *,
        classes: list[str] | None = None,
        property_labels: dict[str, list[str]] | None = None,
    ) -> None:
        self._payload = payload
        self._classes = classes or []
        self._property_labels = property_labels or {}

    def fetch_property_values(self, entity_ids, properties, chunk_size=1000, **kwargs):
        _ = (entity_ids, properties, chunk_size, kwargs)
        return self._payload

    def fetch_entity_names(self, entity_ids, *, lang="en"):
        _ = entity_ids
        if lang == "fr":
            return {"provider/IMF": "Fonds monetaire international"}
        return {"provider/IMF": "International Monetary Fund"}

    def fetch_entity_name_rows(self, entity_ids, *, lang="en", fallback_lang=None):
        _ = (entity_ids, fallback_lang)
        if lang == "fr":
            return {
                "provider/IMF": FetchedName(
                    value="Fonds monetaire international",
                    language="fr",
                    property="nameWithLanguage",
                )
            }
        return {
            "provider/IMF": FetchedName(
                value="International Monetary Fund",
                language="en",
                property="name",
            )
        }

    def fetch_all_classes(self):
        return list(self._classes)

    def fetch_property_labels(self, entity_ids, *, out=True, chunk_size=1000):
        _ = (out, chunk_size)
        return {
            entity_id: self._property_labels.get(entity_id, [])
            for entity_id in entity_ids
        }


def test_get_entities_by_type_reads_inbound_type_members() -> None:
    runtime = _FakeRuntime(
        {
            "DevelopmentFinanceProviderEnum": {
                "typeOf": [
                    SimpleNamespace(dcid="provider/IMF"),
                    SimpleNamespace(value="provider/IDA"),
                ]
            }
        }
    )
    api = OrgDcApi(cast(DataCommons, runtime))

    result = api.get_entities_by_type(raw_type="DevelopmentFinanceProviderEnum")

    assert result == ["provider/IMF", "provider/IDA"]


def test_get_aliases_uses_short_display_name_and_multilingual_names() -> None:
    runtime = _FakeRuntime(
        {
            "provider/IMF": {
                "shortDisplayName": [
                    SimpleNamespace(value="IMF", provenanceId="source/a"),
                ],
                "alternateName": [
                    SimpleNamespace(value="The Fund", provenanceId="source/b"),
                ],
            }
        }
    )
    api = OrgDcApi(cast(DataCommons, runtime))

    aliases = api.get_aliases(["provider/IMF"], languages=["fr"])

    assert aliases["provider/IMF"] == [
        {
            "language": "en",
            "alias_text": "The Fund",
            "alias_type": "alias",
            "source": "source/b",
        },
        {
            "language": "en",
            "alias_text": "IMF",
            "alias_type": "acronym",
            "source": "source/a",
        },
        {
            "language": "fr",
            "alias_text": "Fonds monetaire international",
            "alias_type": "alias",
            "source": "datacommons",
        },
    ]


def test_get_relations_maps_parent_and_membership_properties() -> None:
    runtime = _FakeRuntime(
        {
            "provider/IDA": {
                "parentOrganization": [SimpleNamespace(dcid="org/WorldBank")],
                "memberOf": [SimpleNamespace(value="org/UNSystem")],
            }
        }
    )
    api = OrgDcApi(cast(DataCommons, runtime))

    relations = api.get_relations(["provider/IDA"])

    assert relations["provider/IDA"] == [
        {
            "relation_type": "subsidiary_of",
            "target_id": "org/WorldBank",
        },
        {
            "relation_type": "member_of",
            "target_id": "org/UNSystem",
        },
    ]


def test_get_entity_types_prefers_supported_type_over_provisional_node() -> None:
    runtime = _FakeRuntime(
        {
            "provider/IDA": {
                "typeOf": [
                    SimpleNamespace(value="ProvisionalNode"),
                    SimpleNamespace(value="DevelopmentFinanceProviderEnum"),
                ]
            },
            "Organization": {"subClassOf": []},
            "PoliticalParty": {"subClassOf": []},
            "DevelopmentFinanceProviderEnum": {"subClassOf": []},
            "LendingEntityEnum": {"subClassOf": []},
            "Company": {
                "subClassOf": [SimpleNamespace(value="Organization")],
            },
        },
        classes=[
            "Organization",
            "PoliticalParty",
            "DevelopmentFinanceProviderEnum",
            "LendingEntityEnum",
            "Company",
        ],
    )
    api = OrgDcApi(cast(DataCommons, runtime))

    result = api.get_entity_types(["provider/IDA"])

    assert result == {"provider/IDA": "DevelopmentFinanceProviderEnum"}


class _FakeOrgDcApi:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def get_supported_raw_types(self) -> list[str]:
        return [
            "AirQualitySite",
            "Company",
            "DevelopmentFinanceProviderEnum",
            "LendingEntityEnum",
            "PoliticalParty",
        ]

    def get_entities_by_type(self, *, raw_type: str) -> list[str]:
        self.calls.append(raw_type)
        mapping = {
            "AirQualitySite": ["site/aq-1"],
            "Company": ["org/Acme"],
            "DevelopmentFinanceProviderEnum": ["provider/IMF", "provider/BMGF"],
            "LendingEntityEnum": ["lender/World_Bank_IBRD"],
            "PoliticalParty": ["party/Demo"],
        }
        return mapping.get(raw_type, [])

    def get_relations(self, entity_ids: list[str]) -> dict[str, list[dict[str, str]]]:
        _ = entity_ids
        return {
            "provider/IMF": [
                {"relation_type": "member_of", "target_id": "org/UNSystem"}
            ]
        }


class _FlakySupportedTypesOrgDcApi(_FakeOrgDcApi):
    def __init__(self) -> None:
        super().__init__()
        self.schema_attempts = 0

    def get_supported_raw_types(self) -> list[str]:
        self.schema_attempts += 1
        if self.schema_attempts == 1:
            raise RuntimeError("temporary schema failure")
        return super().get_supported_raw_types()


def test_schema_driven_org_discovery_collects_supported_raw_types() -> None:
    api = _FakeOrgDcApi()

    discovered = discover_entities(
        dc_api=cast(OrgDcApi, api),
        with_retries=lambda fn, **kwargs: fn(**kwargs),
    )

    assert api.calls == [
        "Company",
        "DevelopmentFinanceProviderEnum",
        "LendingEntityEnum",
        "PoliticalParty",
    ]
    assert discovered == [
        "lender/World_Bank_IBRD",
        "org/Acme",
        "party/Demo",
        "provider/BMGF",
        "provider/IMF",
    ]


def test_broad_org_discovery_skips_non_base_org_types() -> None:
    api = _FakeOrgDcApi()

    discovered = discover_entities(
        dc_api=cast(OrgDcApi, api),
        with_retries=lambda fn, **kwargs: fn(**kwargs),
    )

    assert "site/aq-1" not in discovered


def test_filtered_org_discovery_uses_requested_canonical_types() -> None:
    api = _FakeOrgDcApi()

    discovered = discover_entities_filtered(
        dc_api=cast(OrgDcApi, api),
        with_retries=lambda fn, **kwargs: fn(**kwargs),
        include_entity_types=["org.development_finance_provider"],
        include_relation_targets=False,
    )

    assert discovered == ["provider/BMGF", "provider/IMF"]


def test_filtered_org_discovery_can_include_relation_targets() -> None:
    api = _FakeOrgDcApi()

    discovered = discover_entities_filtered(
        dc_api=cast(OrgDcApi, api),
        with_retries=lambda fn, **kwargs: fn(**kwargs),
        include_entity_types=["org.development_finance_provider"],
        include_relation_targets=True,
    )

    assert discovered == ["org/UNSystem", "provider/BMGF", "provider/IMF"]


def test_filtered_org_discovery_retries_supported_type_enumeration() -> None:
    api = _FlakySupportedTypesOrgDcApi()

    def with_retries(fn, **kwargs):
        for _ in range(2):
            try:
                return fn(**kwargs)
            except RuntimeError:
                continue
        raise AssertionError("retry budget exhausted")

    discovered = discover_entities_filtered(
        dc_api=cast(OrgDcApi, api),
        with_retries=with_retries,
        include_entity_types=["org.development_finance_provider"],
        include_relation_targets=False,
    )

    assert discovered == ["provider/BMGF", "provider/IMF"]
    assert api.schema_attempts == 2


def test_filtered_org_discovery_returns_empty_for_unmapped_requested_type() -> None:
    api = _FakeOrgDcApi()

    discovered = discover_entities_filtered(
        dc_api=cast(OrgDcApi, api),
        with_retries=lambda fn, **kwargs: fn(**kwargs),
        include_entity_types=["org.igo"],
        include_relation_targets=False,
    )

    assert discovered == []


def test_org_adapter_filters_discovered_entities_by_canonical_type() -> None:
    adapter = DataCommonsOrgSourceAdapter(languages=[])

    def fake_get_entity_types(self, entity_ids):
        _ = entity_ids
        return {
            "provider/BMGF": "DevelopmentFinanceProviderEnum",
            "lender/World_Bank_IBRD": "LendingEntityEnum",
        }

    adapter._dc_api.get_entity_types = MethodType(
        fake_get_entity_types, adapter._dc_api
    )

    filtered = adapter.filter_discovered_entities(
        "org",
        ["provider/BMGF", "lender/World_Bank_IBRD"],
        ["org.lending_entity"],
    )

    assert filtered == ["lender/World_Bank_IBRD"]
