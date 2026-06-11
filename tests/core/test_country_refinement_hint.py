"""Country refinement hint fires only for country-scoped entities.

The hint is offered when an entity carries explicit country metadata (a
``country_code`` attribute or a country relation) or when its type is in the
pack-declared ``country_scoped_type_prefixes``. Non-geographic domains (e.g.
orgs) that declare no country-scoped prefixes are not offered a country hint
they cannot act on.
"""

from resolvekit.core.engine.enrichment import ResultEnricher
from resolvekit.core.model import EntityRecord


def _enricher(
    *,
    country_scoped_type_prefixes: frozenset[str],
    country_relation_prefixes: frozenset[str] = frozenset(),
) -> ResultEnricher:
    return ResultEnricher(
        store=None,
        sources=[],
        pack_id="test",
        candidate_ordering_key=None,
        country_scoped_type_prefixes=country_scoped_type_prefixes,
        country_relation_prefixes=country_relation_prefixes,
    )


def _entity(entity_type: str, **attributes: str) -> EntityRecord:
    return EntityRecord(
        entity_id="e/1",
        entity_type=entity_type,
        canonical_name="Example",
        canonical_name_norm="example",
        attributes=attributes,
    )


def test_org_entity_without_country_metadata_gets_no_hint():
    # Org declares no country-scoped type prefixes (the default).
    enricher = _enricher(country_scoped_type_prefixes=frozenset())
    org_entity = _entity("org.igo")
    assert enricher._should_hint_country([org_entity]) is False


def test_geo_entity_triggers_hint_by_type():
    enricher = _enricher(country_scoped_type_prefixes=frozenset({"geo"}))
    geo_entity = _entity("geo.city")
    assert enricher._should_hint_country([geo_entity]) is True


def test_country_code_attribute_triggers_hint_regardless_of_type():
    # The country_code attribute is a domain-neutral trigger that fires even
    # when no country-scoped type prefixes are declared.
    enricher = _enricher(country_scoped_type_prefixes=frozenset())
    org_entity = _entity("org.ngo", country_code="US")
    assert enricher._should_hint_country([org_entity]) is True
