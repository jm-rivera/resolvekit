"""Shared module catalog for presets, package metadata, and dependency mapping."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import lru_cache

from resolvekit.builder.models import (
    BuildOptions,
    BuildPlan,
    EntityFilter,
    ModuleRecipe,
)

GEO_MAX_ADMIN_DEPTH = 6


class DistributionStrategy(Enum):
    """How a data module is distributed to end users."""

    BUNDLED = "bundled"
    REMOTE = "remote"


# Manually curated — update when a module's built sqlite reliably exceeds 15 MB.
REMOTE_MODULE_IDS: frozenset[str] = frozenset(
    {
        "geo.admin1",
        "geo.admin2",
        "geo.admin3",
        "geo.admin4",
        "geo.admin5",
        "geo.cities",
    }
)


@dataclass(frozen=True, slots=True)
class ModuleCatalogEntry:
    """One installable module family owned by the repo."""

    module_id: str
    domain: str
    include_entity_types: tuple[str, ...]
    include_in_geo_base: bool = False
    include_in_geo: bool = False
    include_in_org: bool = False
    default_module_dependencies: tuple[str, ...] = ()
    include_calibrator: bool = False
    # Specific entity IDs to drop at packaging — a curated dedup list for
    # discovered entities that duplicate ones already owned elsewhere in the
    # graph (or are source noise).
    exclude_entity_ids: tuple[str, ...] = ()

    @property
    def distribution(self) -> DistributionStrategy:
        """Return the distribution strategy for this module."""
        if self.module_id in REMOTE_MODULE_IDS:
            return DistributionStrategy.REMOTE
        return DistributionStrategy.BUNDLED


def module_id_to_package_name(module_id: str) -> str:
    """Convert ``"geo.countries"`` to ``"resolvekit-geo-countries"``."""
    return "resolvekit-" + module_id.replace(".", "-")


@lru_cache(maxsize=1)
def catalog_entries() -> tuple[ModuleCatalogEntry, ...]:
    """Return all concrete module catalog entries in stable order."""
    geo_entries: list[ModuleCatalogEntry] = [
        ModuleCatalogEntry(
            module_id="geo.countries",
            domain="geo",
            include_entity_types=("geo.country",),
            include_in_geo_base=True,
            include_in_geo=True,
            include_calibrator=True,
        )
    ]
    for level in range(1, GEO_MAX_ADMIN_DEPTH + 1):
        geo_entries.append(
            ModuleCatalogEntry(
                module_id=f"geo.admin{level}",
                domain="geo",
                include_entity_types=(f"geo.admin{level}",),
                include_in_geo_base=True,
                include_in_geo=True,
                default_module_dependencies=(
                    ("geo.countries",) if level == 1 else (f"geo.admin{level - 1}",)
                ),
            )
        )
    geo_entries.extend(
        [
            ModuleCatalogEntry(
                module_id="geo.cities",
                domain="geo",
                include_entity_types=("geo.city",),
                include_in_geo_base=True,
                include_in_geo=True,
                default_module_dependencies=(f"geo.admin{GEO_MAX_ADMIN_DEPTH}",),
            ),
            ModuleCatalogEntry(
                module_id="geo.regions",
                domain="geo",
                include_entity_types=("geo.region", "geo.subregion"),
                include_in_geo=True,
            ),
            ModuleCatalogEntry(
                module_id="geo.continental_unions",
                domain="geo",
                # geo.organization covers intergovernmental bodies (NATO, OECD, etc.)
                # that are not DC coverage units; bundled alongside continental unions.
                include_entity_types=("geo.continental_union", "geo.organization"),
                include_in_geo=True,
            ),
            ModuleCatalogEntry(
                module_id="geo.continents",
                domain="geo",
                # Hardcoded constants (scripts/build/build_continents.py).
                # Eight entities: the seven geographic continents + Americas (Q828).
                include_entity_types=("geo.continent",),
                include_in_geo=True,
            ),
        ]
    )

    org_entries = [
        ModuleCatalogEntry(
            module_id="org.providers",
            domain="org",
            include_entity_types=("org.development_finance_provider",),
            include_in_org=True,
        ),
        ModuleCatalogEntry(
            module_id="org.lenders",
            domain="org",
            include_entity_types=("org.lending_entity",),
            include_in_org=True,
        ),
        ModuleCatalogEntry(
            module_id="org.political_parties",
            domain="org",
            include_entity_types=("org.political_party",),
            include_in_org=True,
        ),
        ModuleCatalogEntry(
            module_id="org.companies",
            domain="org",
            include_entity_types=("org.company", "org.corporation", "org.subsidiary"),
            include_in_org=True,
        ),
        ModuleCatalogEntry(
            module_id="org.governments",
            domain="org",
            include_entity_types=("org.government_organization",),
            include_in_org=True,
        ),
        ModuleCatalogEntry(
            module_id="org.igos",
            domain="org",
            include_entity_types=("org.igo",),
            include_in_org=True,
        ),
        # Sourced from Data Commons `Source` nodes (national statistics offices,
        # research institutes, etc.). The exclude list drops source noise and the
        # handful of publishers already represented elsewhere in the graph, so the
        # module stays purely additive (no cross-pack duplicates):
        #   c/s/default                          → "Custom Data Commons" placeholder
        #   dc/s/StatisticsSweden                → already an OECD-DAC org.government_organization
        #   c/s/1 + dc/s/WorldHealthOrganization → WHO (two Source rows; WHO is a geo entity)
        #   .../Oecd, .../BankFor...Bis          → OECD/BIS already exist as geo entities
        ModuleCatalogEntry(
            module_id="org.data_sources",
            domain="org",
            include_entity_types=("org.data_source",),
            include_in_org=True,
            exclude_entity_ids=(
                "c/s/default",
                "dc/s/StatisticsSweden",
                "c/s/1",
                "dc/s/WorldHealthOrganizationWho",
                "dc/s/OrganisationForEconomicCo-operationAndDevelopmentOecd",
                "dc/s/BankForInternationalSettlementsBis",
            ),
        ),
    ]
    return (*geo_entries, *org_entries)


@lru_cache(maxsize=1)
def _catalog_by_module_id() -> dict[str, ModuleCatalogEntry]:
    return {entry.module_id: entry for entry in catalog_entries()}


@lru_cache(maxsize=1)
def _catalog_by_entity_type() -> dict[str, str]:
    return {
        entity_type: entry.module_id
        for entry in catalog_entries()
        for entity_type in entry.include_entity_types
    }


def module_entry(module_id: str) -> ModuleCatalogEntry:
    """Return one catalog entry by module ID."""
    return _catalog_by_module_id()[module_id]


def module_id_for_entity_type(entity_type: str) -> str | None:
    """Return the owning module ID for a canonical entity type."""
    return _catalog_by_entity_type().get(entity_type.strip())


@lru_cache(maxsize=1)
def geo_base_entries() -> tuple[ModuleCatalogEntry, ...]:
    return tuple(entry for entry in catalog_entries() if entry.include_in_geo_base)


@lru_cache(maxsize=1)
def geo_entries() -> tuple[ModuleCatalogEntry, ...]:
    return tuple(entry for entry in catalog_entries() if entry.include_in_geo)


@lru_cache(maxsize=1)
def org_entries() -> tuple[ModuleCatalogEntry, ...]:
    return tuple(entry for entry in catalog_entries() if entry.include_in_org)


def module_recipe(entry: ModuleCatalogEntry) -> ModuleRecipe:
    """Convert a catalog entry to a concrete build recipe."""
    return ModuleRecipe(
        module_id=entry.module_id,
        domain=entry.domain,
        entity_filter=EntityFilter(
            include_entity_types=list(entry.include_entity_types),
            exclude_entity_ids=list(entry.exclude_entity_ids),
            include_relation_targets=False,
        ),
        module_dependencies=[],
        source_datasets=["datacommons"],
        include_calibrator=entry.include_calibrator,
    )


def build_plan_from_entries(
    entries: tuple[ModuleCatalogEntry, ...],
    *,
    options: BuildOptions | None = None,
) -> BuildPlan:
    """Return a build plan from catalog entries."""
    return BuildPlan(
        recipes=[module_recipe(entry) for entry in entries],
        options=options or BuildOptions(),
    )
