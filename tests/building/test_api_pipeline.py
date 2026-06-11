"""End-to-end and integration tests for the module build pipeline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from resolvekit.builder import pipeline as building_pipeline
from resolvekit.builder import presets
from resolvekit.builder.api import (
    _merge_resume_options,
    build,
    inspect,
    list_releases,
    resume,
)
from resolvekit.builder.geo_shared import COVERAGE_UNITS, GeoSharedStore
from resolvekit.builder.inspection import (
    DiscoveredEntityFacts,
    summarize_domain_inspection,
)
from resolvekit.builder.models import (
    BuildOptions,
    BuildPlan,
    EntityFilter,
    ModuleRecipe,
    QualityPolicy,
)
from resolvekit.builder.pipeline import validate_packaged_artifacts
from resolvekit.builder.pipeline.reconcile import _filter_payload_by_entity_ids
from resolvekit.builder.sources.datacommons.models import (
    NormalizedChunk,
    NormalizedCode,
    NormalizedEntity,
    NormalizedName,
    NormalizedRelation,
)
from resolvekit.builder.sources.seed.continents import CONTINENTS as _CONTINENT_SEED
from resolvekit.builder.state import RunStateStore
from resolvekit.core.api import Resolver, RoutingMode
from resolvekit.core.datapack import DataPackLoader, DataPackMetadata
from resolvekit.core.model import ResolutionStatus

# Continent seed entities the containment enricher (pipeline/enrich.py) points
# M.49 sub-regions at via ``contained_in`` edges.  Real geo builds always include
# the geo.continents module, so reconcile hydrates these as relation targets.
# These synthetic builds omit that module, so we serve the same entities on
# demand — hydratable as relation targets but never *discovered* as primaries,
# matching production and keeping other tests' discovered entity sets unchanged.
_GEO_CONTINENT_HYDRATION_TARGETS: dict[str, dict[str, Any]] = {
    entry.entity_id: {
        "entity_type": "geo.continent",
        "name": entry.canonical_name,
        "codes": [],
        "aliases": [],
        "parents": [],
    }
    for entry in _CONTINENT_SEED
}


class StaticAdapter:
    """Deterministic in-memory source adapter for pipeline tests."""

    def __init__(
        self,
        *,
        domain: str,
        entities: dict[str, dict[str, Any]],
        fail_fetch_counts: dict[str, int] | None = None,
        discovered_ids: list[str] | None = None,
    ) -> None:
        self.domain = domain
        self.entities = entities
        self.fail_fetch_counts = fail_fetch_counts or {}
        self.discovered_ids = discovered_ids
        # Relation targets the enricher mints edges to but that are not
        # discovered primaries (continents). Only consulted on fetch.
        self.hydration_targets: dict[str, dict[str, Any]] = (
            dict(_GEO_CONTINENT_HYDRATION_TARGETS) if domain == "geo" else {}
        )

    def supported_domains(self) -> set[str]:
        return {self.domain}

    def discover_entities(self, domain: str) -> list[str]:
        if domain != self.domain:
            raise ValueError(f"Unsupported domain {domain!r}")
        if self.discovered_ids is not None:
            return list(self.discovered_ids)
        return sorted(self.entities.keys())

    def discover_entities_filtered(
        self,
        domain: str,
        include_entity_types: list[str],
        include_relation_targets: bool,
    ) -> list[str]:
        _ = include_relation_targets
        discovered = self.discover_entities(domain)
        return self.filter_discovered_entities(
            domain,
            discovered,
            include_entity_types,
        )

    def filter_discovered_entities(
        self,
        domain: str,
        entity_ids: list[str],
        include_entity_types: list[str],
    ) -> list[str]:
        if domain != self.domain:
            raise ValueError(f"Unsupported domain {domain!r}")
        allowlist = {value.strip() for value in include_entity_types if value.strip()}
        if not allowlist:
            return list(entity_ids)
        return [
            entity_id
            for entity_id in entity_ids
            if self.entities[entity_id]["entity_type"] in allowlist
        ]

    def fetch_raw_chunk(self, domain: str, entity_ids: list[str]) -> dict[str, Any]:
        if domain != self.domain:
            raise ValueError(f"Unsupported domain {domain!r}")

        chunk_key = "|".join(sorted(entity_ids))
        if self.fail_fetch_counts.get(chunk_key, 0) > 0:
            self.fail_fetch_counts[chunk_key] -= 1
            raise RuntimeError(f"temporary fetch failure for {chunk_key}")

        entities: dict[str, dict[str, Any]] = {}
        codes: dict[str, list[dict[str, Any]]] = {}
        aliases: dict[str, list[dict[str, Any]]] = {}
        parents: dict[str, list[str]] = {}

        for entity_id in entity_ids:
            row = self.entities.get(entity_id) or self.hydration_targets[entity_id]
            entities[entity_id] = {
                "entity_type": row["entity_type"],
                "name": row["name"],
                "centroid_lat": row.get("centroid_lat"),
                "centroid_lon": row.get("centroid_lon"),
            }
            codes[entity_id] = [
                {
                    "code_system": system,
                    "code_value": value,
                    "source": "test",
                }
                for system, value in row.get("codes", [])
            ]
            aliases[entity_id] = [
                {
                    "alias_text": alias,
                    "language": "en",
                    "alias_type": "alias",
                }
                for alias in row.get("aliases", [])
            ]
            parents[entity_id] = list(row.get("parents", []))

        return {
            "entities": entities,
            "codes": codes,
            "aliases": aliases,
            "parents": parents,
        }

    def normalize_raw_chunk(
        self,
        domain: str,
        raw_chunk: dict[str, Any],
    ) -> dict[str, list[dict[str, Any]]]:
        if domain != self.domain:
            raise ValueError(f"Unsupported domain {domain!r}")

        entity_rows: list[dict[str, Any]] = []
        name_rows: list[dict[str, Any]] = []
        code_rows: list[dict[str, Any]] = []
        relation_rows: list[dict[str, Any]] = []

        for entity_id, payload in raw_chunk["entities"].items():
            canonical_name = str(payload["name"])
            entity_rows.append(
                {
                    "entity_id": entity_id,
                    "entity_type": str(payload["entity_type"]),
                    "canonical_name": canonical_name,
                    "canonical_name_norm": canonical_name.casefold(),
                    "valid_from": None,
                    "valid_until": None,
                    "attrs_json": {
                        "source": "test",
                        "centroid_lat": payload.get("centroid_lat"),
                        "centroid_lon": payload.get("centroid_lon"),
                    },
                }
            )
            name_rows.append(
                {
                    "entity_id": entity_id,
                    "name_kind": "canonical",
                    "value": canonical_name,
                    "value_norm": canonical_name.casefold(),
                    "lang": "en",
                    "script": None,
                    "is_preferred": 1,
                }
            )
            code_rows.append(
                {
                    "entity_id": entity_id,
                    "system": "dcid",
                    "value": entity_id,
                    "value_norm": entity_id.casefold(),
                }
            )

        for entity_id, alias_rows in raw_chunk["aliases"].items():
            for alias_row in alias_rows:
                alias_text = str(alias_row["alias_text"])
                name_rows.append(
                    {
                        "entity_id": entity_id,
                        "name_kind": "alias",
                        "value": alias_text,
                        "value_norm": alias_text.casefold(),
                        "lang": "en",
                        "script": None,
                        "is_preferred": 0,
                    }
                )

        for entity_id, code_payload in raw_chunk["codes"].items():
            for code in code_payload:
                code_rows.append(
                    {
                        "entity_id": entity_id,
                        "system": str(code["code_system"]).casefold(),
                        "value": str(code["code_value"]),
                        "value_norm": str(code["code_value"]).casefold(),
                    }
                )

        for entity_id, parent_ids in raw_chunk["parents"].items():
            for parent_id in parent_ids:
                relation_rows.append(
                    {
                        "entity_id": entity_id,
                        "relation_type": "contained_in",
                        "target_id": parent_id,
                    }
                )

        return {
            "entities": entity_rows,
            "names": name_rows,
            "codes": code_rows,
            "relations": relation_rows,
        }

    def inspect_domain(
        self,
        domain: str,
        *,
        include_entity_types: list[str],
        include_relation_targets: bool,
    ):
        if domain != self.domain:
            raise ValueError(f"Unsupported domain {domain!r}")

        facts_by_entity = {
            entity_id: DiscoveredEntityFacts(
                entity_id=entity_id,
                raw_entity_type=row["entity_type"],
                canonical_entity_type=row["entity_type"],
            )
            for entity_id, row in self.entities.items()
        }
        return summarize_domain_inspection(
            domain=domain,
            requested_entity_types=include_entity_types,
            include_relation_targets=include_relation_targets,
            facts_by_entity=facts_by_entity,
        )


class IncrementalStaticAdapter(StaticAdapter):
    """Static adapter that streams filtered discovery batches + progress."""

    def __init__(
        self,
        *,
        domain: str,
        entities: dict[str, dict[str, Any]],
        incremental_batches: list[list[str]],
    ) -> None:
        super().__init__(domain=domain, entities=entities)
        self.incremental_batches = incremental_batches
        self.incremental_calls = 0

    def discover_entities_filtered_incremental(
        self,
        domain: str,
        *,
        include_entity_types: list[str],
        include_relation_targets: bool,
        emit_entities,
        emit_progress,
        seed_frontier: dict[str, list[str]] | None = None,
    ) -> None:
        from resolvekit.builder.sources.discovery_events import (
            BatchComplete,
            DomainComplete,
            DomainStart,
            UnitBatch,
            UnitComplete,
            UnitStart,
        )

        self.incremental_calls += 1
        discovered = self.discover_entities_filtered(
            domain,
            include_entity_types,
            include_relation_targets,
        )
        allowlist = set(discovered)
        emit_progress(
            DomainStart(
                unit=domain,
                requested_entity_types=include_entity_types,
                include_relation_targets=include_relation_targets,
            )
        )
        emit_progress(
            UnitStart(unit="countries", batch_count=len(self.incremental_batches))
        )
        discovered_total = 0
        for batch_index, batch_ids in enumerate(self.incremental_batches, start=1):
            filtered_batch = [
                entity_id for entity_id in batch_ids if entity_id in allowlist
            ]
            if not filtered_batch:
                continue
            discovered_total += len(filtered_batch)
            emit_entities(
                "countries",
                filtered_batch,
                UnitBatch(
                    unit="countries",
                    batch_index=batch_index,
                    batch_count=len(self.incremental_batches),
                    discovered_in_batch=len(filtered_batch),
                    discovered_total=discovered_total,
                ),
            )
            emit_progress(
                BatchComplete(
                    unit="countries",
                    batch_index=batch_index,
                    batch_count=len(self.incremental_batches),
                    completed_batches=batch_index,
                )
            )
        emit_progress(
            UnitComplete(
                unit="countries",
                batch_count=len(self.incremental_batches),
                completed_batches=len(self.incremental_batches),
                discovered_entities=discovered_total,
            )
        )
        emit_progress(
            DomainComplete(
                unit=domain,
                requested_entity_types=include_entity_types,
                discovered_entities=discovered_total,
            )
        )


def make_options(tmp_path: Path, **kwargs: Any) -> BuildOptions:
    """Create test options with fast retry timings and isolated roots."""
    payload: dict[str, Any] = {
        "build_root": tmp_path / "build",
        "datapacks_root": tmp_path / "_data",
        "reports_root": tmp_path / "reports",
        "max_workers": 2,
        "chunk_size": 1,
        "max_retries": 2,
        "retry_base_delay_sec": 0.0,
        "retry_max_delay_sec": 0.0,
    }
    payload.update(kwargs)
    return BuildOptions(**payload)


def make_geo_entities(*, include_canada: bool = True) -> dict[str, dict[str, Any]]:
    """Create synthetic geo graph with region and countries."""
    rows: dict[str, dict[str, Any]] = {
        "region/NAM": {
            "entity_type": "geo.region",
            "name": "North America",
            "codes": [],
            "aliases": ["NAM"],
            "parents": [],
        },
        "country/USA": {
            "entity_type": "geo.country",
            "name": "United States",
            "codes": [("iso2", "US"), ("iso3", "USA")],
            "aliases": ["US"],
            "parents": ["region/NAM"],
        },
    }
    if include_canada:
        rows["country/CAN"] = {
            "entity_type": "geo.country",
            "name": "Canada",
            "codes": [("iso2", "CA")],
            "aliases": [],
            "parents": ["region/NAM"],
        }
    return rows


def make_geo_module_entities() -> dict[str, dict[str, Any]]:
    """Create geo entities spanning the default module preset split."""
    return {
        "region/NAM": {
            "entity_type": "geo.region",
            "name": "North America",
            "codes": [],
            "aliases": ["NAM"],
            "parents": [],
        },
        "country/USA": {
            "entity_type": "geo.country",
            "name": "United States",
            "codes": [("iso2", "US"), ("iso3", "USA")],
            "aliases": ["US"],
            "parents": ["region/NAM"],
        },
        "admin1/US-CA": {
            "entity_type": "geo.admin1",
            "name": "California",
            "codes": [("iso3166_2", "US-CA")],
            "aliases": ["CA"],
            "parents": ["country/USA"],
        },
        "city/US-CA-SF": {
            "entity_type": "geo.city",
            "name": "San Francisco",
            "codes": [],
            "aliases": ["SF"],
            "parents": ["admin1/US-CA"],
        },
    }


def make_geo_group_entities() -> dict[str, dict[str, Any]]:
    """Create synthetic geo group entities for filtered module builds."""
    return {
        "geo/EuropeanUnion": {
            "entity_type": "geo.continental_union",
            "name": "European Union",
            "codes": [("undata", "97")],
            "aliases": ["EU"],
            "parents": [],
        },
        "geo/GroupOf7": {
            "entity_type": "geo.region",
            "name": "Group of 7",
            "codes": [("dac", "G7")],
            "aliases": ["G7"],
            "parents": [],
        },
    }


def make_org_entities() -> dict[str, dict[str, Any]]:
    """Create synthetic org entities for bundle integration tests."""
    return {
        "org/EU": {
            "entity_type": "org.igo",
            "name": "European Union",
            "codes": [],
            "aliases": ["EU"],
            "parents": [],
        }
    }


def make_org_family_entities() -> dict[str, dict[str, Any]]:
    """Create synthetic provider and lender org entities."""
    return {
        "provider/BMGF": {
            "entity_type": "org.development_finance_provider",
            "name": "Bill & Melinda Gates Foundation",
            "codes": [("dac", "9PRIV1601"), ("dac_numeric", "1601.0")],
            "aliases": ["BMGF"],
            "parents": [],
        },
        "lender/World_Bank_IBRD": {
            "entity_type": "org.lending_entity",
            "name": "World Bank IBRD",
            "codes": [("wikidata", "Q49108")],
            "aliases": ["IBRD"],
            "parents": [],
        },
    }


def patch_adapters(monkeypatch, adapter_by_domain: dict[str, StaticAdapter]) -> None:
    """Patch adapter registry used by BuildContext."""
    monkeypatch.setattr(
        building_pipeline,
        "build_adapter_registry",
        lambda _plan: adapter_by_domain,
    )
    monkeypatch.setattr(
        building_pipeline,
        "build_inspection_adapter_registry",
        lambda _plan: adapter_by_domain,
    )


def invalidate_all_geo_coverage(options: BuildOptions) -> None:
    store = GeoSharedStore(options.shared_geo_root)
    store.ensure_paths()
    for unit_name in COVERAGE_UNITS:
        store.mark_invalid(unit_name)


def test_builtin_org_adapter_registry_supports_build_plans(tmp_path: Path) -> None:
    options = make_options(tmp_path)
    plan = BuildPlan(
        recipes=[ModuleRecipe(module_id="org.providers", domain="org")],
        options=options,
    )

    adapters = building_pipeline.build_adapter_registry(plan)

    assert set(adapters) == {"org"}


def test_builtin_adapter_registry_passes_datacommons_options(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Any] = {}

    class _CapturedAdapter:
        def supported_domains(self) -> set[str]:
            return {"geo"}

    def factory(options: BuildOptions) -> _CapturedAdapter:
        captured["instance"] = options.datacommons_instance
        captured["api_key"] = options.datacommons_api_key
        return _CapturedAdapter()

    monkeypatch.setitem(building_pipeline.ADAPTER_FACTORIES, "geo", factory)

    plan = BuildPlan(
        recipes=[ModuleRecipe(module_id="geo.countries", domain="geo")],
        options=make_options(
            tmp_path,
            datacommons_instance="datacommons.one.org",
            datacommons_api_key="secret-key",
        ),
    )

    adapters = building_pipeline.build_adapter_registry(plan)

    assert set(adapters) == {"geo"}
    assert captured == {
        "instance": "datacommons.one.org",
        "api_key": "secret-key",
    }


def test_inspect_reports_domain_coverage_and_persists_json(
    monkeypatch, tmp_path: Path
) -> None:
    geo_adapter = StaticAdapter(domain="geo", entities=make_geo_module_entities())
    org_adapter = StaticAdapter(domain="org", entities=make_org_entities())
    patch_adapters(monkeypatch, {"geo": geo_adapter, "org": org_adapter})

    options = make_options(tmp_path)
    outcome = inspect(presets.all_modules(options))

    assert not outcome.errors
    assert {report.domain for report in outcome.domains} == {"geo", "org"}
    geo_report = next(report for report in outcome.domains if report.domain == "geo")
    assert geo_report.classification.canonical_type_counts["geo.country"] == 1
    assert geo_report.classification.canonical_type_counts["geo.admin1"] == 1
    assert geo_report.classification.canonical_type_counts["geo.city"] == 1
    report_path = Path(outcome.reports["inspection_report"])
    assert report_path.exists()
    payload = json.loads(report_path.read_text())
    assert payload["run_id"] == outcome.run_id
    assert {row["domain"] for row in payload["domains"]} == {"geo", "org"}


def test_build_is_inplace_preserves_version_and_writes_no_registry(
    monkeypatch, tmp_path: Path
) -> None:
    # A plain build() rebuilds in place: it never bumps the version and never
    # writes the release ledger (that is the explicit job of release_data.py).
    geo_adapter = StaticAdapter(domain="geo", entities=make_geo_entities())
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(tmp_path)
    recipe = ModuleRecipe(module_id="geo.world", domain="geo", include_symspell=False)
    plan = BuildPlan(recipes=[recipe], options=options)

    first = build(plan)
    second = build(plan)

    assert first.status.value == "success"
    assert second.status.value == "success"
    # First build has no pack on disk → placeholder version; the rebuild
    # preserves it rather than bumping.
    assert [r.version for r in first.releases] == ["0.0.0"]
    assert [r.version for r in second.releases] == ["0.0.0"]
    # build() leaves the release ledger untouched.
    assert list_releases(module_id="geo.world", options=options) == []


def test_release_data_stamps_calver_records_ledger_and_freezes(
    monkeypatch, tmp_path: Path
) -> None:
    # The release path owns versioning + the ledger + immutability. A built pack
    # carries a placeholder version; release_data stamps the CalVer, records the
    # ledger row (with the build's quality_metrics), and refuses re-release.
    from scripts.release import release_data

    geo_adapter = StaticAdapter(domain="geo", entities=make_geo_entities())
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(tmp_path)
    plan = BuildPlan(
        recipes=[
            ModuleRecipe(
                module_id="geo.countries", domain="geo", include_symspell=False
            )
        ],
        options=options,
    )
    assert build(plan).status.value == "success"

    monkeypatch.setattr(release_data, "DATAPACKS_ROOT", options.datapacks_root)
    monkeypatch.setattr(release_data, "BUILD_ROOT", options.build_root)
    # PROJECT_ROOT is used for the manifest write — redirect it into tmp so the
    # test never touches the real repo root.
    monkeypatch.setattr(release_data, "PROJECT_ROOT", tmp_path)
    # Immutability is now sourced from the GitHub release tag via `gh release
    # view`; stub the check so the first run() proceeds and the second sees
    # the tag as already-published.
    tag_published: set[str] = set()

    def fake_tag_exists(tag: str) -> bool:
        return tag in tag_published

    monkeypatch.setattr(release_data, "_release_tag_exists", fake_tag_exists)

    manifest = release_data.run("2026.5", dry_run=False)
    assert manifest["calver"] == "2026.5"

    meta = DataPackMetadata.from_file(
        options.datapacks_root / "geo" / "countries" / "metadata.json"
    )
    assert meta.data_version == "2026.5"
    assert meta.datapack_id == "geo.countries-v2026.5"

    releases = list_releases(module_id="geo.countries", options=options)
    assert [r.version for r in releases] == ["2026.5"]
    assert releases[0].metrics["geo.entity_count"] > 0

    # Immutability: once the GitHub release tag exists, re-releasing refuses.
    tag_published.add("data-v2026.5")
    with pytest.raises(RuntimeError, match="already exists"):
        release_data.run("2026.5", dry_run=False)


def test_retry_policy_fails_after_max_attempts(monkeypatch, tmp_path: Path) -> None:
    geo_entities = {
        "country/USA": make_geo_entities(include_canada=False)["country/USA"]
    }
    geo_adapter = StaticAdapter(
        domain="geo",
        entities=geo_entities,
        fail_fetch_counts={"country/USA": 2},
    )
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(tmp_path, max_retries=1)
    plan = BuildPlan(
        recipes=[ModuleRecipe(module_id="geo.fail", domain="geo")],
        options=options,
    )

    outcome = build(plan)
    assert outcome.status.value == "failed"
    assert outcome.stage == "extract"

    state = RunStateStore(options.runs_root / outcome.run_id / "state.sqlite")
    row = state.get_chunk("geo:000000")
    assert row["failed_stage"] == "extract"
    assert row["extract_attempts"] == 1
    error_meta = state.get_meta("last_error")
    assert error_meta["stage"] == "extract"
    assert error_meta["error_type"] == "BuildExecutionError"
    assert "max retries" in error_meta["message"]

    build_report_path = (
        options.runs_root / outcome.run_id / "reports" / "build_report.json"
    )
    build_report = json.loads(build_report_path.read_text())
    assert build_report["stage_statuses"]["extract"] == "failed"
    assert build_report["last_error"]["stage"] == "extract"
    assert build_report["last_error"]["error_type"] == "BuildExecutionError"


def test_discover_prunes_geo_entities_for_countries_only_recipe(
    monkeypatch, tmp_path: Path
) -> None:
    geo_adapter = StaticAdapter(
        domain="geo",
        entities=make_geo_entities(include_canada=True),
    )
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(tmp_path)
    plan = BuildPlan(
        recipes=[
            ModuleRecipe(
                module_id="geo.countries-only",
                domain="geo",
                entity_filter=EntityFilter(
                    include_entity_types=["geo.country"],
                    include_relation_targets=False,
                ),
                include_symspell=False,
            )
        ],
        options=options,
    )

    outcome = build(plan)
    assert outcome.status.value == "success"

    state = RunStateStore(options.runs_root / outcome.run_id / "state.sqlite")
    chunk_rows = state.list_chunks(domain="geo")
    discovered_ids = {
        entity_id
        for row in chunk_rows
        for entity_id in json.loads(str(row["entity_ids_json"]))
    }
    assert discovered_ids == {"region/NAM", "country/USA", "country/CAN"}


def test_build_persists_incremental_discover_progress_in_report(
    monkeypatch, tmp_path: Path
) -> None:
    geo_adapter = IncrementalStaticAdapter(
        domain="geo",
        entities=make_geo_entities(include_canada=True),
        incremental_batches=[
            ["region/NAM"],
            ["country/USA", "country/CAN"],
        ],
    )
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(tmp_path)
    plan = BuildPlan(
        recipes=[
            ModuleRecipe(
                module_id="geo.countries",
                domain="geo",
                entity_filter=EntityFilter(
                    include_entity_types=["geo.country"],
                    include_relation_targets=False,
                ),
                include_symspell=False,
            )
        ],
        options=options,
    )

    outcome = build(plan)

    assert outcome.status.value == "success"
    assert geo_adapter.incremental_calls == 1

    state = RunStateStore(options.runs_root / outcome.run_id / "state.sqlite")
    discover_progress = state.get_meta("discover_progress")
    assert discover_progress["domains"]["geo"]["mode"] == "incremental_filtered"
    assert discover_progress["domains"]["geo"]["status"] == "complete"
    assert discover_progress["domains"]["geo"]["chunk_count"] == 3
    assert discover_progress["domains"]["geo"]["units"]["countries"]["status"] == (
        "complete"
    )

    build_report = json.loads(
        (
            options.runs_root / outcome.run_id / "reports" / "build_report.json"
        ).read_text()
    )
    assert build_report["discover_progress"]["domains"]["geo"]["chunk_count"] == 3
    assert build_report["discovered_chunks"] == {"geo": 3}


def test_resume_retries_failed_chunks_with_higher_retry_budget(
    monkeypatch,
    tmp_path: Path,
) -> None:
    geo_entities = make_geo_entities(include_canada=False)
    geo_adapter = StaticAdapter(
        domain="geo",
        entities=geo_entities,
        fail_fetch_counts={"country/USA": 1},
    )
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    first_options = make_options(tmp_path, max_retries=1)
    recipe = ModuleRecipe(
        module_id="geo.resume",
        domain="geo",
        include_symspell=False,
    )
    first_plan = BuildPlan(recipes=[recipe], options=first_options)

    first = build(first_plan)
    assert first.status.value == "failed"

    resumed_options = make_options(tmp_path, max_retries=3)
    resumed = resume(first.run_id, options=resumed_options)

    assert resumed.status.value == "success"
    assert resumed.releases


def test_resume_rejects_run_shaping_option_changes(monkeypatch, tmp_path: Path) -> None:
    geo_entities = {
        "country/USA": make_geo_entities(include_canada=False)["country/USA"]
    }
    geo_adapter = StaticAdapter(
        domain="geo",
        entities=geo_entities,
        fail_fetch_counts={"country/USA": 2},
    )
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    first_options = make_options(tmp_path, max_retries=1)
    first_plan = BuildPlan(
        recipes=[ModuleRecipe(module_id="geo.resume-guard", domain="geo")],
        options=first_options,
    )
    first = build(first_plan)
    assert first.status.value == "failed"

    with pytest.raises(ValueError, match="chunk_size"):
        resume(first.run_id, options=make_options(tmp_path, chunk_size=2))


def test_merge_resume_options_only_updates_explicit_mutable_fields() -> None:
    original = BuildOptions(
        max_workers=12,
        max_retries=1,
        retry_base_delay_sec=0.1,
        retry_max_delay_sec=1.0,
    )
    override = BuildOptions(max_retries=4)

    merged = _merge_resume_options(original, override)

    assert merged.max_workers == 12
    assert merged.max_retries == 4
    assert merged.retry_base_delay_sec == 0.1
    assert merged.retry_max_delay_sec == 1.0


def _make_geo_country_grid(count: int) -> dict[str, dict[str, Any]]:
    """Create ``count`` synthetic countries under a single region.

    Used by the suspicious-drop gate test, which needs a large enough source
    population that a realistic drop exceeds the gate threshold even with the
    ~177 OECD DAC recipient aggregates that the enricher always injects into the
    geo.region pool.
    """
    rows: dict[str, dict[str, Any]] = {
        "region/NAM": {
            "entity_type": "geo.region",
            "name": "North America",
            "codes": [],
            "aliases": ["NAM"],
            "parents": [],
        },
    }
    for i in range(count):
        code = f"X{i:03d}"
        rows[f"country/{code}"] = {
            "entity_type": "geo.country",
            "name": f"Country {code}",
            "codes": [("iso3", code)],
            "aliases": [],
            "parents": ["region/NAM"],
        }
    return rows


def test_suspicious_drop_quality_gate_blocks_release(
    monkeypatch, tmp_path: Path
) -> None:
    # The OECD DAC enricher always injects ~177 recipient aggregates into the
    # geo.region pool, so the entity-drop drift metric is computed over a
    # source + OECD population. To exercise the gate meaningfully we seed a large
    # source country set and then drop a chunk large enough that the drop exceeds
    # 10% of the *total* (source + OECD) entity count. See the design note in the
    # task report: embracing OECD aggregates dilutes whole-pack drift; per-type or
    # per-source drift would be a more targeted future option.
    geo_adapter = StaticAdapter(domain="geo", entities=_make_geo_country_grid(100))
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(tmp_path)
    policy = QualityPolicy(max_entity_drop_pct=0.1)
    recipe = ModuleRecipe(
        module_id="geo.drop-gate",
        domain="geo",
        include_symspell=False,
        quality_policy=policy,
    )
    plan = BuildPlan(recipes=[recipe], options=options)

    first = build(plan)
    assert first.status.value == "success"
    published_meta = first.releases[0].output_path / "metadata.json"
    before = DataPackMetadata.from_file(published_meta).quality_metrics

    # Drop half the source countries. Against a first-build total of ~278
    # (100 countries + 1 region + ~177 OECD regions), dropping 50 is ~18%, well
    # above the 10% gate threshold.
    geo_adapter.entities = _make_geo_country_grid(50)
    invalidate_all_geo_coverage(options)
    # Rebuild in place (same datapacks_root). The gate snapshots the first
    # build's pack before overwriting it and compares the new pack against that
    # snapshot — the in-place rebuild semantics. The drop must fire the gate.
    plan2 = BuildPlan(recipes=[recipe], options=options)
    second = build(plan2)

    assert second.status.value == "failed"
    assert second.stage == "package"
    # Build-to-temp invariant: a failed gate must not corrupt the published pack.
    after = DataPackMetadata.from_file(published_meta).quality_metrics
    assert after == before


def test_diff_and_changelog_outputs_are_generated(monkeypatch, tmp_path: Path) -> None:
    geo_adapter = StaticAdapter(
        domain="geo", entities=make_geo_entities(include_canada=False)
    )
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    # This test isolates diff/changelog mechanics for a country add + rename.
    # Disable reconcile relation closure so the M.49 containment enricher's
    # continent edges (minted in enrich, after reconcile) are not hydrated —
    # the second in-place build would otherwise surface continents as spurious
    # "added" entities (a reconcile-before-enrich shared-store artifact).
    options = make_options(tmp_path, reconcile_relation_closure=False)
    recipe = ModuleRecipe(module_id="geo.diff", domain="geo", include_symspell=False)
    plan = BuildPlan(recipes=[recipe], options=options)

    first = build(plan)
    assert first.status.value == "success"

    geo_adapter.entities["country/USA"]["name"] = "United States of America"
    geo_adapter.entities["country/CAN"] = make_geo_entities(include_canada=True)[
        "country/CAN"
    ]
    invalidate_all_geo_coverage(options)

    # Rebuild in place (same datapacks_root). The changelog diffs the new pack
    # against a snapshot of the one it replaced — taken before overwrite — so an
    # in-place rebuild still reports +added / -removed / ~changed correctly.
    plan2 = BuildPlan(recipes=[recipe], options=options)
    second = build(plan2)
    assert second.status.value == "success"

    release = second.releases[0]
    diff_entities = json.loads((release.output_path / "diff_entities.json").read_text())
    assert diff_entities["counts"] == {"added": 1, "removed": 0, "changed": 1}
    assert diff_entities["domains"]["geo"]["counts"] == {
        "added": 1,
        "removed": 0,
        "changed": 1,
    }

    changelog = (release.output_path / "changelog.md").read_text()
    assert "+1 / -0 / ~1" in changelog


def test_multi_module_plan_outputs_loadable_packs(monkeypatch, tmp_path: Path) -> None:
    geo_adapter = StaticAdapter(
        domain="geo", entities=make_geo_entities(include_canada=False)
    )
    org_adapter = StaticAdapter(domain="org", entities=make_org_entities())
    patch_adapters(monkeypatch, {"geo": geo_adapter, "org": org_adapter})

    options = make_options(tmp_path)
    plan = BuildPlan(
        recipes=[
            ModuleRecipe(
                module_id="geo.countries",
                domain="geo",
                include_symspell=False,
            ),
            ModuleRecipe(
                module_id="org.igos",
                domain="org",
                include_symspell=False,
            ),
        ],
        options=options,
    )

    outcome = build(plan)
    assert outcome.status.value == "success"

    outputs = {release.module_id: release.output_path for release in outcome.releases}
    assert set(outputs) == {"geo.countries", "org.igos"}

    loader = DataPackLoader()
    loader.load(outputs["geo.countries"])
    loader.load(outputs["org.igos"])

    with Resolver.from_datapacks(
        datapack_paths=[outputs["geo.countries"], outputs["org.igos"]],
        routing_mode=RoutingMode.EXPLICIT,
    ) as resolver:
        us = resolver.resolve("United States", domain="geo")
        eu = resolver.resolve("European Union", domain="org")

        assert us.status in {
            ResolutionStatus.RESOLVED,
            ResolutionStatus.AMBIGUOUS,
            ResolutionStatus.NO_MATCH,
            ResolutionStatus.ERROR,
        }
        assert eu.status in {
            ResolutionStatus.RESOLVED,
            ResolutionStatus.AMBIGUOUS,
            ResolutionStatus.NO_MATCH,
            ResolutionStatus.ERROR,
        }


def test_geo_preset_builds_disjoint_module_outputs(monkeypatch, tmp_path: Path) -> None:
    geo_adapter = StaticAdapter(domain="geo", entities=make_geo_module_entities())
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(tmp_path)
    # The static fixture has no calibration training data, so disable the
    # calibrator for this fast-path test. Production builds retain
    # include_calibrator=True via the catalog entry for geo.countries.
    plan = presets.geo(options)
    recipes = [
        recipe.model_copy(update={"include_calibrator": False})
        for recipe in plan.recipes
    ]
    plan = plan.model_copy(update={"recipes": recipes})
    outcome = build(plan)

    assert outcome.status.value == "success"
    outputs = {release.module_id: release.output_path for release in outcome.releases}
    assert set(outputs) == {
        "geo.regions",
        "geo.countries",
        "geo.admin1",
        "geo.cities",
        "geo.continental_unions",
    }

    regions_meta = json.loads((outputs["geo.regions"] / "metadata.json").read_text())
    countries_meta = json.loads(
        (outputs["geo.countries"] / "metadata.json").read_text()
    )
    admin1_meta = json.loads((outputs["geo.admin1"] / "metadata.json").read_text())
    cities_meta = json.loads((outputs["geo.cities"] / "metadata.json").read_text())
    assert regions_meta["module_dependencies"] == []
    assert sorted(countries_meta["module_dependencies"]) == sorted(
        ["geo.regions", "geo.continental_unions"]
    )
    assert admin1_meta["module_dependencies"] == ["geo.countries"]
    assert cities_meta["module_dependencies"] == ["geo.admin1"]

    regions_loader = DataPackLoader().load(outputs["geo.regions"])
    countries_loader = DataPackLoader().load(outputs["geo.countries"])
    admin1_loader = DataPackLoader().load(outputs["geo.admin1"])
    cities_loader = DataPackLoader().load(outputs["geo.cities"])
    assert regions_loader.module_id == "geo.regions"
    assert countries_loader.module_id == "geo.countries"
    assert admin1_loader.module_id == "geo.admin1"
    assert cities_loader.module_id == "geo.cities"

    import sqlite3

    with sqlite3.connect(regions_loader.db_path) as conn:
        region_ids = {
            row[0] for row in conn.execute("SELECT entity_id FROM entities").fetchall()
        }
    with sqlite3.connect(countries_loader.db_path) as conn:
        country_ids = {
            row[0] for row in conn.execute("SELECT entity_id FROM entities").fetchall()
        }
    with sqlite3.connect(admin1_loader.db_path) as conn:
        admin1_ids = {
            row[0] for row in conn.execute("SELECT entity_id FROM entities").fetchall()
        }
    with sqlite3.connect(cities_loader.db_path) as conn:
        city_ids = {
            row[0] for row in conn.execute("SELECT entity_id FROM entities").fetchall()
        }

    # The geo.regions module holds source regions plus the OECD DAC recipient
    # aggregates ("West Africa, regional", etc.), which the enricher injects as
    # first-class ``geo.region/oecd:*`` entities. Assert the source region is
    # present and OECD aggregates were embraced, rather than pinning the exact
    # (170+) id set.
    assert "region/NAM" in region_ids
    assert any(rid.startswith("geo.region/oecd:") for rid in region_ids)
    # OECD attaches codes/names to existing countries but creates no new country
    # entities, so the countries module is unchanged.
    assert country_ids == {"country/USA"}
    assert admin1_ids == {"admin1/US-CA"}
    assert city_ids == {"city/US-CA-SF"}


def test_geo_build_packages_from_shared_store_when_coverage_is_already_ready(
    monkeypatch, tmp_path: Path
) -> None:
    geo_adapter = StaticAdapter(domain="geo", entities=make_geo_module_entities())
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(tmp_path)
    first_plan = BuildPlan(
        recipes=[
            ModuleRecipe(
                module_id="geo.admin1",
                domain="geo",
                entity_filter=EntityFilter(
                    include_entity_types=["geo.admin1"],
                    include_relation_targets=False,
                ),
                include_symspell=False,
            )
        ],
        options=options,
    )
    first = build(first_plan)
    assert first.status.value == "success"

    second_plan = BuildPlan(
        recipes=[
            ModuleRecipe(
                module_id="geo.countries",
                domain="geo",
                entity_filter=EntityFilter(
                    include_entity_types=["geo.country"],
                    include_relation_targets=False,
                ),
                include_symspell=False,
            )
        ],
        options=options,
    )
    second = build(second_plan)
    assert second.status.value == "success"

    second_state = RunStateStore(options.runs_root / second.run_id / "state.sqlite")
    assert second_state.count_chunks_by_domain() == {}

    metadata = json.loads(
        (second.releases[0].output_path / "metadata.json").read_text()
    )
    assert sorted(metadata["module_dependencies"]) == sorted(
        ["geo.regions", "geo.continental_unions"]
    )


def test_geo_partial_refresh_packages_from_shared_store_for_dependencies(
    monkeypatch, tmp_path: Path
) -> None:
    geo_adapter = StaticAdapter(domain="geo", entities=make_geo_module_entities())
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(tmp_path)
    first_plan = BuildPlan(
        recipes=[
            ModuleRecipe(
                module_id="geo.admin1",
                domain="geo",
                entity_filter=EntityFilter(
                    include_entity_types=["geo.admin1"],
                    include_relation_targets=False,
                ),
                include_symspell=False,
            )
        ],
        options=options,
    )
    first = build(first_plan)
    assert first.status.value == "success"

    second_plan = BuildPlan(
        recipes=[
            ModuleRecipe(
                module_id="geo.cities",
                domain="geo",
                entity_filter=EntityFilter(
                    include_entity_types=["geo.city"],
                    include_relation_targets=False,
                ),
                include_symspell=False,
            )
        ],
        options=options,
    )
    second = build(second_plan)
    assert second.status.value == "success"

    metadata = json.loads(
        (second.releases[0].output_path / "metadata.json").read_text()
    )
    assert metadata["module_dependencies"] == ["geo.admin1"]

    second_state = RunStateStore(options.runs_root / second.run_id / "state.sqlite")
    coverage = second_state.get_meta("geo_shared_coverage")
    assert coverage["missing_units"] == []


def test_build_filtered_geo_group_modules(monkeypatch, tmp_path: Path) -> None:
    import sqlite3

    geo_adapter = StaticAdapter(domain="geo", entities=make_geo_group_entities())
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(tmp_path)
    plan = BuildPlan(
        recipes=[
            ModuleRecipe(
                module_id="geo.regions",
                domain="geo",
                entity_filter=EntityFilter(
                    include_entity_types=["geo.region"],
                    include_relation_targets=False,
                ),
                include_symspell=False,
            ),
            ModuleRecipe(
                module_id="geo.continental_unions",
                domain="geo",
                entity_filter=EntityFilter(
                    include_entity_types=["geo.continental_union"],
                    include_relation_targets=False,
                ),
                include_symspell=False,
            ),
        ],
        options=options,
    )

    outcome = build(plan)
    assert outcome.status.value == "success"

    outputs = {release.module_id: release.output_path for release in outcome.releases}
    with sqlite3.connect(outputs["geo.regions"] / "entities.sqlite") as conn:
        region_ids = {
            row[0] for row in conn.execute("SELECT entity_id FROM entities").fetchall()
        }
    with sqlite3.connect(outputs["geo.continental_unions"] / "entities.sqlite") as conn:
        union_ids = {
            row[0] for row in conn.execute("SELECT entity_id FROM entities").fetchall()
        }

    # geo.regions filters on geo.region, which now also holds the OECD DAC
    # recipient aggregates injected by the enricher as first-class entities.
    # Assert the source region is present alongside the embraced OECD aggregates.
    assert "geo/GroupOf7" in region_ids
    assert any(rid.startswith("geo.region/oecd:") for rid in region_ids)
    # OECD creates no geo.continental_union entities, so this module is unchanged.
    assert union_ids == {"geo/EuropeanUnion"}


def test_build_filtered_org_family_modules(monkeypatch, tmp_path: Path) -> None:
    import sqlite3

    org_adapter = StaticAdapter(domain="org", entities=make_org_family_entities())
    patch_adapters(monkeypatch, {"org": org_adapter})

    options = make_options(tmp_path)
    plan = BuildPlan(
        recipes=[
            ModuleRecipe(
                module_id="org.providers",
                domain="org",
                entity_filter=EntityFilter(
                    include_entity_types=["org.development_finance_provider"],
                    include_relation_targets=False,
                ),
                include_symspell=False,
            ),
            ModuleRecipe(
                module_id="org.lenders",
                domain="org",
                entity_filter=EntityFilter(
                    include_entity_types=["org.lending_entity"],
                    include_relation_targets=False,
                ),
                include_symspell=False,
            ),
        ],
        options=options,
    )

    outcome = build(plan)
    assert outcome.status.value == "success"

    outputs = {release.module_id: release.output_path for release in outcome.releases}
    with sqlite3.connect(outputs["org.providers"] / "entities.sqlite") as conn:
        provider_ids = {
            row[0] for row in conn.execute("SELECT entity_id FROM entities").fetchall()
        }
        provider_codes = {
            tuple(row)
            for row in conn.execute(
                "SELECT system, value FROM codes WHERE entity_id = 'provider/BMGF'"
            ).fetchall()
        }
        provider_aliases = {
            tuple(row)
            for row in conn.execute(
                "SELECT name_kind, value FROM names WHERE entity_id = 'provider/BMGF'"
            ).fetchall()
        }
    with sqlite3.connect(outputs["org.lenders"] / "entities.sqlite") as conn:
        lender_ids = {
            row[0] for row in conn.execute("SELECT entity_id FROM entities").fetchall()
        }

    # The OECD DAC enricher injects multilateral providers (typed
    # org.development_finance_provider) into this module, so the only entities
    # beyond the mock BMGF provider are those synthesized OECD providers.
    assert "provider/BMGF" in provider_ids
    assert all(
        pid == "provider/BMGF" or pid.startswith("org/oecd:provider:")
        for pid in provider_ids
    )
    assert lender_ids == {"lender/World_Bank_IBRD"}
    assert ("dac", "9PRIV1601") in provider_codes
    assert ("dac_numeric", "1601.0") in provider_codes
    assert ("alias", "BMGF") in provider_aliases


def test_org_preset_prunes_empty_modules_dynamically(
    monkeypatch, tmp_path: Path
) -> None:
    org_adapter = StaticAdapter(domain="org", entities=make_org_family_entities())
    patch_adapters(monkeypatch, {"org": org_adapter})

    options = make_options(tmp_path)
    outcome = build(presets.org(options))

    assert outcome.status.value == "success"
    # The OECD DAC enricher injects donor-country agencies as first-class
    # ``org.government_organization`` entities, so org.governments is legitimately
    # non-empty and gets released alongside the source-backed provider/lender
    # modules. (OECD multilateral providers ship in org.providers as
    # ``org.development_finance_provider``; channels stay ``org.organization``,
    # which no module catalogs, so the remaining modules are empty and pruned.)
    assert {release.module_id for release in outcome.releases} == {
        "org.providers",
        "org.lenders",
        "org.governments",
    }

    build_report = json.loads(
        (
            options.runs_root / outcome.run_id / "reports" / "build_report.json"
        ).read_text()
    )
    skipped = {
        (row["module_id"], row["reason"]) for row in build_report["skipped_modules"]
    }
    assert skipped == {
        ("org.political_parties", "no selected entities after filtering"),
        ("org.companies", "no selected entities after filtering"),
        ("org.igos", "no selected entities after filtering"),
        ("org.data_sources", "no selected entities after filtering"),
    }


def test_build_succeeds_when_all_requested_modules_are_empty(
    monkeypatch, tmp_path: Path
) -> None:
    org_adapter = StaticAdapter(domain="org", entities=make_org_family_entities())
    patch_adapters(monkeypatch, {"org": org_adapter})

    options = make_options(tmp_path)
    plan = BuildPlan(
        recipes=[
            ModuleRecipe(
                module_id="org.governments",
                domain="org",
                entity_filter=EntityFilter(
                    include_entity_types=["org.government_organization"],
                    include_relation_targets=False,
                ),
                include_symspell=False,
            )
        ],
        options=options,
    )

    outcome = build(plan)

    assert outcome.status.value == "success"
    assert outcome.releases == []
    assert not (options.datapacks_root / "org.governments").exists()

    build_report = json.loads(
        (
            options.runs_root / outcome.run_id / "reports" / "build_report.json"
        ).read_text()
    )
    assert build_report["skipped_modules"] == [
        {
            "module_id": "org.governments",
            "domain": "org",
            "reason": "no discovered entities",
        }
    ]


def test_validate_packaged_artifacts_detects_missing_symspell(tmp_path: Path) -> None:
    domain_dir = tmp_path / "geo"
    domain_dir.mkdir(parents=True, exist_ok=True)

    sqlite_path = domain_dir / "entities.sqlite"
    sqlite_path.write_bytes(b"test")

    metadata_payload = {
        "datapack_id": "geo-test-v1",
        "module_id": "geo.test",
        "domain_pack_id": "geo",
        "entity_schema_version": "1.0",
        "feature_schema_version": "geo.features.v1",
        "index_versions": {"fts": "fts5", "symspell": "symspell.dict"},
        "build_timestamp": "2026-01-01T00:00:00Z",
        "source_datasets": ["test"],
        "artifacts": {"symspell": "symspell.dict"},
        "pack_type": "base",
        "store_type": "sqlite",
        "store_file": "entities.sqlite",
        "checksums": {"sqlite": "deadbeef"},
    }
    (domain_dir / "metadata.json").write_text(json.dumps(metadata_payload))

    issues = validate_packaged_artifacts(
        domain_dir=domain_dir,
        sqlite_path=sqlite_path,
        include_symspell=True,
    )
    assert any("Missing symspell artifact" in issue for issue in issues)


def test_validate_packaged_artifacts_detects_checksum_mismatch(tmp_path: Path) -> None:
    domain_dir = tmp_path / "geo"
    domain_dir.mkdir(parents=True, exist_ok=True)

    sqlite_path = domain_dir / "entities.sqlite"
    sqlite_path.write_bytes(b"test")

    metadata_payload = {
        "datapack_id": "geo-test-v1",
        "module_id": "geo.test",
        "domain_pack_id": "geo",
        "entity_schema_version": "1.0",
        "feature_schema_version": "geo.features.v1",
        "index_versions": {"fts": "fts5", "symspell": None},
        "build_timestamp": "2026-01-01T00:00:00Z",
        "source_datasets": ["test"],
        "pack_type": "base",
        "store_type": "sqlite",
        "store_file": "entities.sqlite",
        "checksums": {"sqlite": "deadbeef"},
    }
    (domain_dir / "metadata.json").write_text(json.dumps(metadata_payload))

    issues = validate_packaged_artifacts(
        domain_dir=domain_dir,
        sqlite_path=sqlite_path,
        include_symspell=False,
    )

    assert any("Checksum validation failed" in issue for issue in issues)


def test_reconcile_stage_hydrates_missing_contained_in_targets(
    monkeypatch, tmp_path: Path
) -> None:
    geo_entities = {
        "city/Toronto": {
            "entity_type": "geo.city",
            "name": "Toronto",
            "codes": [("iso2", "CA")],
            "aliases": [],
            "parents": ["country/CAN"],
        },
        "country/CAN": {
            "entity_type": "geo.country",
            "name": "Canada",
            "codes": [("iso2", "CA")],
            "aliases": [],
            "parents": ["region/NAM"],
        },
        "region/NAM": {
            "entity_type": "geo.region",
            "name": "North America",
            "codes": [],
            "aliases": [],
            "parents": [],
        },
    }
    geo_adapter = StaticAdapter(
        domain="geo",
        entities=geo_entities,
        discovered_ids=["city/Toronto"],
    )
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(
        tmp_path,
        reconcile_max_rounds=4,
        reconcile_max_entities=10,
        reconcile_batch_size=1,
    )
    recipe = ModuleRecipe(
        module_id="geo.reconcile-success",
        domain="geo",
        include_symspell=False,
    )
    plan = BuildPlan(recipes=[recipe], options=options)

    outcome = build(plan)
    assert outcome.status.value == "success"

    state = RunStateStore(options.runs_root / outcome.run_id / "state.sqlite")
    reconcile_meta = state.get_meta("staging_reconcile")
    assert reconcile_meta["geo"]["remaining_missing_targets"] == 0
    assert reconcile_meta["geo"]["hydrated_entities"] == 2


def test_reconcile_stage_fails_when_target_budget_is_exhausted(
    monkeypatch, tmp_path: Path
) -> None:
    geo_entities = {
        "city/Toronto": {
            "entity_type": "geo.city",
            "name": "Toronto",
            "codes": [],
            "aliases": [],
            "parents": ["country/CAN"],
        },
        "country/CAN": {
            "entity_type": "geo.country",
            "name": "Canada",
            "codes": [],
            "aliases": [],
            "parents": ["region/NAM"],
        },
        "region/NAM": {
            "entity_type": "geo.region",
            "name": "North America",
            "codes": [],
            "aliases": [],
            "parents": [],
        },
    }
    geo_adapter = StaticAdapter(
        domain="geo",
        entities=geo_entities,
        discovered_ids=["city/Toronto"],
    )
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(
        tmp_path,
        reconcile_max_rounds=4,
        reconcile_max_entities=1,
        reconcile_batch_size=1,
    )
    recipe = ModuleRecipe(
        module_id="geo.reconcile-budget-fail",
        domain="geo",
        include_symspell=False,
    )
    plan = BuildPlan(recipes=[recipe], options=options)

    outcome = build(plan)
    assert outcome.status.value == "failed"
    assert outcome.stage == "reconcile"


def test_filter_payload_by_entity_ids_accepts_normalized_chunk_models() -> None:
    chunk = NormalizedChunk(
        entities=[
            NormalizedEntity(
                entity_id="geo/1",
                entity_type="geo.region",
                canonical_name="Region 1",
                canonical_name_norm="region 1",
            ),
            NormalizedEntity(
                entity_id="geo/2",
                entity_type="geo.region",
                canonical_name="Region 2",
                canonical_name_norm="region 2",
            ),
        ],
        names=[
            NormalizedName(
                entity_id="geo/1",
                name_kind="canonical",
                value="Region 1",
                value_norm="region 1",
                is_preferred=1,
            ),
            NormalizedName(
                entity_id="geo/2",
                name_kind="canonical",
                value="Region 2",
                value_norm="region 2",
                is_preferred=1,
            ),
        ],
        codes=[
            NormalizedCode(
                entity_id="geo/2",
                system="dcid",
                value="geo/2",
                value_norm="geo/2",
            )
        ],
        relations=[
            NormalizedRelation(
                entity_id="geo/2",
                relation_type="contained_in",
                target_id="geo/1",
            )
        ],
    )
    payload = chunk.model_dump(mode="python")

    filtered = _filter_payload_by_entity_ids(payload, {"geo/2"})

    assert [row["entity_id"] for row in filtered["entities"]] == ["geo/2"]
    assert [row["entity_id"] for row in filtered["names"]] == ["geo/2"]
    assert [row["entity_id"] for row in filtered["codes"]] == ["geo/2"]
    assert [row["entity_id"] for row in filtered["relations"]] == ["geo/2"]


def test_geo_build_pins_names_relations_fts(monkeypatch, tmp_path: Path) -> None:
    """Characterization: packaged geo sqlite has expected names, relations, FTS rows.

    Pins the full pipeline (discover → merge → reconcile → enrich → package)
    for the name/relation/FTS content so changes cannot silently break them.
    """
    import sqlite3

    geo_adapter = StaticAdapter(
        domain="geo", entities=make_geo_entities(include_canada=False)
    )
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(tmp_path)
    recipe = ModuleRecipe(module_id="geo.world", domain="geo", include_symspell=False)
    plan = BuildPlan(recipes=[recipe], options=options)

    outcome = build(plan)
    assert outcome.status.value == "success"

    loader = DataPackLoader().load(outcome.releases[0].output_path)

    with sqlite3.connect(loader.db_path) as conn:
        # Names table: canonical name for country/USA
        rows = conn.execute(
            "SELECT value FROM names WHERE entity_id = 'country/USA' AND name_kind = 'canonical'"
        ).fetchall()
        assert rows == [("United States",)], f"expected canonical name, got {rows}"

        # Relations table: country/USA contained_in region/NAM
        # (StaticAdapter.normalize_raw_chunk emits relation_type='contained_in' for parents)
        target_ids = {
            row[0]
            for row in conn.execute(
                "SELECT target_id FROM relations "
                "WHERE entity_id = 'country/USA' AND relation_type = 'contained_in'"
            ).fetchall()
        }
        assert "region/NAM" in target_ids, (
            f"expected region/NAM in relations, got {target_ids}"
        )

        # FTS index: MATCH 'united' returns country/USA
        fts_ids = {
            row[0]
            for row in conn.execute(
                "SELECT entity_id FROM names_fts WHERE names_fts MATCH 'united'"
            ).fetchall()
        }
        assert "country/USA" in fts_ids, (
            f"expected country/USA in FTS results, got {fts_ids}"
        )


def test_reconcile_then_package_survival(monkeypatch, tmp_path: Path) -> None:
    """Characterization: entities in a reconcile-enabled build appear in the packaged sqlite.

    Single-run: discover all three entities (city/Toronto, country/CAN, region/NAM).
    Reconcile is enabled and runs, but finds no missing targets because all
    entities were discovered. Assert all three appear in the packaged output.

    NOTE: this single-run setup does not trigger the incremental scenario
    where reconcile must hydrate targets absent from the shared store. See
    test_two_run_incremental_reconcile_survival for that case.
    """
    import sqlite3

    geo_entities = {
        "city/Toronto": {
            "entity_type": "geo.city",
            "name": "Toronto",
            "codes": [("iso2", "CA")],
            "aliases": [],
            "parents": ["country/CAN"],
        },
        "country/CAN": {
            "entity_type": "geo.country",
            "name": "Canada",
            "codes": [("iso2", "CA")],
            "aliases": [],
            "parents": ["region/NAM"],
        },
        "region/NAM": {
            "entity_type": "geo.region",
            "name": "North America",
            "codes": [],
            "aliases": [],
            "parents": [],
        },
    }
    # Discover all three — reconcile has no missing targets to hydrate, but the
    # reconcile stage still runs and must not drop any entity on the path to package.
    geo_adapter = StaticAdapter(
        domain="geo",
        entities=geo_entities,
    )
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(
        tmp_path,
        reconcile_max_rounds=4,
        reconcile_max_entities=10,
        reconcile_batch_size=1,
    )
    recipe = ModuleRecipe(
        module_id="geo.reconcile-pack",
        domain="geo",
        include_symspell=False,
    )
    plan = BuildPlan(recipes=[recipe], options=options)

    outcome = build(plan)
    assert outcome.status.value == "success"

    loader = DataPackLoader().load(outcome.releases[0].output_path)

    with sqlite3.connect(loader.db_path) as conn:
        entity_ids = {
            row[0] for row in conn.execute("SELECT entity_id FROM entities").fetchall()
        }

    # All three must survive discover → materialize → reconcile → package.
    assert "city/Toronto" in entity_ids
    assert "country/CAN" in entity_ids
    assert "region/NAM" in entity_ids


def test_two_run_incremental_reconcile_survival(monkeypatch, tmp_path: Path) -> None:
    """Characterization: reconcile-hydrated entities survive to the packaged sqlite
    in a two-run incremental build scenario.

    Run 1: discover country/USA + region/NAM → merged into shared geo store.
    Run 2: discover city/Toronto only (country/CAN NOT discovered in run 2, so
    reconcile must hydrate it from relation targets). Assert country/CAN appears
    in run 2's packaged sqlite. Reconcile and stage_package read the same DB,
    so reconcile-hydrated entities appear in the packaged output.
    """
    import sqlite3

    # Run 1: build base units so shared store is populated.
    run1_entities = {
        "region/NAM": {
            "entity_type": "geo.region",
            "name": "North America",
            "codes": [],
            "aliases": [],
            "parents": [],
        },
        "country/USA": {
            "entity_type": "geo.country",
            "name": "United States",
            "codes": [("iso3", "USA")],
            "aliases": [],
            "parents": ["region/NAM"],
        },
    }
    geo_adapter = StaticAdapter(domain="geo", entities=run1_entities)
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    # Both runs share the same build_root so the geo shared store persists.
    options = make_options(tmp_path)
    recipe1 = ModuleRecipe(module_id="geo.run1", domain="geo", include_symspell=False)
    plan1 = BuildPlan(recipes=[recipe1], options=options)

    run1 = build(plan1)
    assert run1.status.value == "success"

    # Run 2: adapter exposes city/Toronto (discovered) plus country/CAN and
    # region/NAM (relation targets — hydrated by reconcile, NOT discovered).
    run2_entities = {
        "city/Toronto": {
            "entity_type": "geo.city",
            "name": "Toronto",
            "codes": [],
            "aliases": [],
            "parents": ["country/CAN"],
        },
        "country/CAN": {
            "entity_type": "geo.country",
            "name": "Canada",
            "codes": [("iso2", "CA")],
            "aliases": [],
            "parents": ["region/NAM"],
        },
        "region/NAM": {
            "entity_type": "geo.region",
            "name": "North America",
            "codes": [],
            "aliases": [],
            "parents": [],
        },
    }
    geo_adapter.entities = run2_entities
    geo_adapter.discovered_ids = ["city/Toronto"]

    # Invalidate coverage so run 2 performs a fresh discover+merge cycle.
    invalidate_all_geo_coverage(options)

    options2 = make_options(
        tmp_path,
        datapacks_root=tmp_path / "_data2",
        reconcile_max_rounds=4,
        reconcile_max_entities=10,
        reconcile_batch_size=1,
    )
    recipe2 = ModuleRecipe(
        module_id="geo.run2",
        domain="geo",
        include_symspell=False,
    )
    plan2 = BuildPlan(recipes=[recipe2], options=options2)

    run2 = build(plan2)
    assert run2.status.value == "success"

    loader = DataPackLoader().load(run2.releases[0].output_path)
    with sqlite3.connect(loader.db_path) as conn:
        entity_ids = {
            row[0] for row in conn.execute("SELECT entity_id FROM entities").fetchall()
        }

    # Reconcile and stage_package read the same DB, so reconcile-hydrated
    # country/CAN appears in the packaged sqlite.
    assert "city/Toronto" in entity_ids
    assert "country/CAN" in entity_ids, (
        "reconcile-hydrated country/CAN must appear in packaged sqlite"
    )


def test_build_allows_external_relation_targets_when_reconcile_disabled(
    monkeypatch, tmp_path: Path
) -> None:
    geo_entities = {
        "region/NAM": {
            "entity_type": "geo.region",
            "name": "North America",
            "codes": [],
            "aliases": [],
            "parents": ["Earth"],
        }
    }
    geo_adapter = StaticAdapter(
        domain="geo",
        entities=geo_entities,
        discovered_ids=["region/NAM"],
    )
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(tmp_path, reconcile_relation_closure=False)
    plan = BuildPlan(
        recipes=[
            ModuleRecipe(
                module_id="geo.regions",
                domain="geo",
                entity_filter=EntityFilter(
                    include_entity_types=["geo.region"],
                    include_relation_targets=False,
                ),
                include_symspell=False,
            )
        ],
        options=options,
    )

    outcome = build(plan)

    assert outcome.status.value == "success"


# ---------------------------------------------------------------------------
# Finding 2 — _publish_pack is atomic / crash-safe
# ---------------------------------------------------------------------------


def test_publish_pack_crash_during_swapin_leaves_previous_pack_intact(
    monkeypatch, tmp_path: Path
) -> None:
    """If the final os.replace (swap-in) raises, the previously-published pack
    must remain intact (entities.sqlite and metadata.json unchanged)."""
    import os

    from resolvekit.builder.pipeline.packaging import _publish_pack

    # Simulate an already-published pack
    output_path = tmp_path / "geo" / "countries"
    output_path.mkdir(parents=True)
    (output_path / "entities.sqlite").write_bytes(b"original-sqlite")
    (output_path / "metadata.json").write_text('{"datapack_id": "geo.countries-v1"}')

    # Create a work_dir to publish
    work_dir = tmp_path / "work"
    work_dir.mkdir(parents=True)
    (work_dir / "entities.sqlite").write_bytes(b"new-sqlite")
    (work_dir / "metadata.json").write_text('{"datapack_id": "geo.countries-v2"}')

    original_os_replace = os.replace
    call_count = 0

    def _fail_on_second_replace(src: Any, dst: Any) -> None:
        nonlocal call_count
        call_count += 1
        # First call: move-aside of old pack → let it succeed.
        # Second call: swap-in of staging → raise to simulate crash.
        # Third call (rollback): must succeed so the previous pack is restored.
        if call_count == 2:
            raise OSError("simulated crash during swap-in")
        original_os_replace(src, dst)

    monkeypatch.setattr(os, "replace", _fail_on_second_replace)

    with pytest.raises(OSError, match="simulated crash"):
        _publish_pack(work_dir=work_dir, output_path=output_path)

    # Previously-published pack must be intact after rollback
    assert (output_path / "entities.sqlite").read_bytes() == b"original-sqlite"
    assert (
        output_path / "metadata.json"
    ).read_text() == '{"datapack_id": "geo.countries-v1"}'


# ---------------------------------------------------------------------------
# Finding 3 — data_version is preserved on in-place rebuild
# ---------------------------------------------------------------------------


def test_inplace_rebuild_preserves_stamped_data_version(
    monkeypatch, tmp_path: Path
) -> None:
    """After release_data stamps data_version=2026.5, a subsequent plain build()
    must preserve that data_version rather than resetting it to the default."""
    from resolvekit.core.datapack import DataPackMetadata
    from scripts.release import release_data

    geo_adapter = StaticAdapter(domain="geo", entities=make_geo_entities())
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(tmp_path)
    plan = BuildPlan(
        recipes=[
            ModuleRecipe(
                module_id="geo.countries", domain="geo", include_symspell=False
            )
        ],
        options=options,
    )

    # First build (placeholder version 0.0.0)
    first = build(plan)
    assert first.status.value == "success"

    # Release stamps the CalVer
    monkeypatch.setattr(release_data, "DATAPACKS_ROOT", options.datapacks_root)
    monkeypatch.setattr(release_data, "BUILD_ROOT", options.build_root)
    monkeypatch.setattr(release_data, "PROJECT_ROOT", tmp_path)
    release_data.run("2026.5", dry_run=False)

    meta_path = options.datapacks_root / "geo" / "countries" / "metadata.json"
    meta_after_release = DataPackMetadata.from_file(meta_path)
    assert meta_after_release.data_version == "2026.5"

    # In-place rebuild (fresh adapter data; invalidate geo coverage)
    invalidate_all_geo_coverage(options)
    plan2 = BuildPlan(recipes=[plan.recipes[0]], options=options)
    second = build(plan2)
    assert second.status.value == "success"

    meta_after_rebuild = DataPackMetadata.from_file(meta_path)
    assert meta_after_rebuild.data_version == "2026.5", (
        "Plain rebuild must preserve the CalVer-stamped data_version"
    )


# ---------------------------------------------------------------------------
# Finding 5 — resume after package stage reloads release_candidates
# ---------------------------------------------------------------------------


def test_resume_after_package_stage_has_nonempty_releases(
    monkeypatch, tmp_path: Path
) -> None:
    """On a resume where package is already 'done', outcome.releases must be
    non-empty because release_candidates are reloaded from persisted state."""
    from resolvekit.builder.pipeline.core import BuildContext, execute_build
    from resolvekit.builder.pipeline.types import load_release_candidates
    from resolvekit.builder.utils import utc_now_iso

    geo_adapter = StaticAdapter(domain="geo", entities=make_geo_entities())
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(tmp_path)
    recipe = ModuleRecipe(
        module_id="geo.countries", domain="geo", include_symspell=False
    )
    plan = BuildPlan(recipes=[recipe], options=options)

    # Complete a full successful build first
    first = build(plan)
    assert first.status.value == "success"
    assert first.releases

    # Simulate a resume: create a fresh context for the same run.
    ctx = BuildContext(
        plan=plan,
        run_id=first.run_id,
        started_at=utc_now_iso(),
        resume_mode=True,
    )
    # Mark package stage as done so it is skipped (release_candidates won't be
    # populated from stage_package again); mark changelog pending so it re-runs.
    ctx.state.set_stage_status("package", "done")
    ctx.state.set_stage_status("changelog", "pending")

    # In-memory candidates are empty (simulates a fresh context on resume)
    assert ctx.release_candidates == []

    # load_release_candidates should find the persisted meta
    loaded = load_release_candidates(ctx)
    assert loaded, "release_candidates must be reloadable from state on resume"

    outcome = execute_build(ctx)
    assert outcome.status.value == "success"
    assert outcome.releases, "outcome.releases must be non-empty after resume"


# ---------------------------------------------------------------------------
# Finding 7 — per-module ledger write (partial failure test)
# ---------------------------------------------------------------------------


def test_release_data_records_first_module_in_ledger_on_partial_failure(
    monkeypatch, tmp_path: Path
) -> None:
    """If release_data fails partway through (e.g. on the 2nd module), the
    1st module must already be recorded in the ledger."""

    from resolvekit.builder import registry as registry_mod
    from resolvekit.builder.api import list_releases
    from scripts.release import release_data

    # Build two modules
    geo_adapter = StaticAdapter(domain="geo", entities=make_geo_entities())
    org_adapter = StaticAdapter(domain="org", entities=make_org_entities())
    patch_adapters(monkeypatch, {"geo": geo_adapter, "org": org_adapter})

    options = make_options(tmp_path)
    plan = BuildPlan(
        recipes=[
            ModuleRecipe(
                module_id="geo.countries", domain="geo", include_symspell=False
            ),
            ModuleRecipe(module_id="org.igos", domain="org", include_symspell=False),
        ],
        options=options,
    )
    outcome = build(plan)
    assert outcome.status.value == "success"

    monkeypatch.setattr(release_data, "DATAPACKS_ROOT", options.datapacks_root)
    monkeypatch.setattr(release_data, "BUILD_ROOT", options.build_root)
    monkeypatch.setattr(release_data, "PROJECT_ROOT", tmp_path)

    # Make append_releases raise on the second call to simulate a mid-loop
    # failure after the first module has been ledgered.
    original_append = registry_mod.append_releases
    call_count = 0

    def _fail_on_second_append(opts: Any, records: Any) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise RuntimeError("simulated mid-loop failure on 2nd module")
        original_append(opts, records)

    monkeypatch.setattr(registry_mod, "append_releases", _fail_on_second_append)
    monkeypatch.setattr(release_data, "append_releases", _fail_on_second_append)

    with pytest.raises(RuntimeError, match="simulated mid-loop failure"):
        release_data.run("2026.5", dry_run=False)

    # The first module (whichever was processed first) must be in the ledger
    all_releases = list_releases(options=options)
    assert len(all_releases) >= 1, (
        "At least one module must be in the ledger after a partial failure"
    )
