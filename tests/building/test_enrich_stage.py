"""Tests for the ``enrich`` pipeline stage."""

from __future__ import annotations

import contextlib
import json
import sqlite3
from pathlib import Path

from resolvekit.builder.api import build
from resolvekit.builder.formal_names import COUNTRY_ENTITY_TYPE
from resolvekit.builder.models import (
    BuildPlan,
    EntityFilter,
    ModuleRecipe,
)
from resolvekit.builder.pipeline.types import STAGES
from resolvekit.builder.state import RunStateStore
from tests.building.test_api_pipeline import (
    StaticAdapter,
    make_geo_entities,
    make_options,
    make_org_family_entities,
    patch_adapters,
)


def test_enrich_stage_is_registered_between_reconcile_and_validate() -> None:
    assert "enrich" in STAGES
    assert STAGES.index("enrich") == STAGES.index("reconcile") + 1
    assert STAGES.index("enrich") + 1 == STAGES.index("validate")


def test_enrich_adds_country_formal_aliases_to_packaged_sqlite(
    monkeypatch, tmp_path: Path
) -> None:
    geo_adapter = StaticAdapter(
        domain="geo", entities=make_geo_entities(include_canada=False)
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

    state = RunStateStore(options.runs_root / outcome.run_id / "state.sqlite")
    enrich_meta = state.get_meta("staging_enrich")
    assert enrich_meta is not None
    geo_report = enrich_meta["geo"]
    assert geo_report["names_changed"] > 0
    assert COUNTRY_ENTITY_TYPE in geo_report["results"]
    enricher_results = geo_report["results"][COUNTRY_ENTITY_TYPE]
    assert "build_formal_name_contribution" in enricher_results
    assert enricher_results["build_formal_name_contribution"]["names"] > 0

    sqlite_path = outcome.releases[0].output_path / "entities.sqlite"
    with sqlite3.connect(sqlite_path) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT value FROM names WHERE entity_id = 'country/USA'"
            )
        }
    assert "United States of America" in names


def test_enrich_is_idempotent_across_repeated_builds(
    monkeypatch, tmp_path: Path
) -> None:
    geo_adapter = StaticAdapter(
        domain="geo", entities=make_geo_entities(include_canada=False)
    )
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(tmp_path)
    plan = BuildPlan(
        recipes=[
            ModuleRecipe(
                module_id="geo.countries-idempotent",
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

    first = build(plan)
    assert first.status.value == "success"

    sqlite_path = first.releases[0].output_path / "entities.sqlite"
    # closing() because a sqlite3 connection context manager commits but does
    # not close — leaving the handle open would block the second build from
    # rewriting entities.sqlite on Windows.
    with contextlib.closing(sqlite3.connect(sqlite_path)) as conn:
        first_names = sorted(
            tuple(row)
            for row in conn.execute(
                "SELECT entity_id, value FROM names ORDER BY entity_id, value"
            )
        )

    second = build(plan)
    assert second.status.value == "success"

    state = RunStateStore(options.runs_root / second.run_id / "state.sqlite")
    enrich_meta = state.get_meta("staging_enrich")
    # Second build inserts zero new rows because INSERT OR IGNORE collides
    # with the pre-existing aliases written by the first build.
    assert enrich_meta["geo"]["names_changed"] == 0
    enricher_results = enrich_meta["geo"]["results"][COUNTRY_ENTITY_TYPE]
    for inserted in enricher_results.values():
        assert inserted["names"] == 0

    sqlite_path = second.releases[0].output_path / "entities.sqlite"
    with contextlib.closing(sqlite3.connect(sqlite_path)) as conn:
        second_names = sorted(
            tuple(row)
            for row in conn.execute(
                "SELECT entity_id, value FROM names ORDER BY entity_id, value"
            )
        )

    assert first_names == second_names


def test_enrich_skips_domains_without_matching_entity_types(
    monkeypatch, tmp_path: Path
) -> None:
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
        ],
        options=options,
    )

    outcome = build(plan)
    assert outcome.status.value == "success"

    state = RunStateStore(options.runs_root / outcome.run_id / "state.sqlite")
    enrich_meta = state.get_meta("staging_enrich")
    assert enrich_meta is not None
    assert enrich_meta["org"]["names_changed"] == 0
    assert enrich_meta["org"]["results"] == {}


def test_enrich_country_st_aliases_emits_abbreviated_variants(
    monkeypatch, tmp_path: Path
) -> None:
    """Saint X countries gain ``St. X`` and ``St X`` aliases."""
    entities = make_geo_entities(include_canada=False)
    entities["country/LCA"] = {
        "entity_type": "geo.country",
        "name": "Saint Lucia",
        "codes": [("iso2", "LC"), ("iso3", "LCA")],
        "aliases": [],
        "parents": ["region/NAM"],
    }
    geo_adapter = StaticAdapter(domain="geo", entities=entities)
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(tmp_path)
    plan = BuildPlan(
        recipes=[
            ModuleRecipe(
                module_id="geo.countries-st",
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

    sqlite_path = outcome.releases[0].output_path / "entities.sqlite"
    with sqlite3.connect(sqlite_path) as conn:
        names = {
            row[0]
            for row in conn.execute(
                "SELECT value FROM names WHERE entity_id = 'country/LCA'"
            )
        }
    assert "Saint Lucia" in names
    assert "St. Lucia" in names
    assert "St Lucia" in names


def test_enrich_region_filter_removes_known_placeholder_patterns(
    monkeypatch, tmp_path: Path
) -> None:
    """Junk ``geo.region`` rows ([former], G009*, breakdown labels) are stripped."""
    entities: dict[str, dict] = {
        "region/EU": {
            "entity_type": "geo.region",
            "name": "European Union",
            "codes": [],
            "aliases": [],
            "parents": [],
        },
        "undata-geo/G00001020": {
            "entity_type": "geo.region",
            "name": "Federal Republic of Germany",
            "codes": [],
            "aliases": [],
            "parents": [],
        },
        "undata-geo/G00001950": {
            "entity_type": "geo.region",
            "name": "Micronesia [former]",
            "codes": [],
            "aliases": [],
            "parents": [],
        },
        "undata-geo/G00900010": {
            "entity_type": "geo.region",
            "name": "Not applicable",
            "codes": [],
            "aliases": [],
            "parents": [],
        },
        "undata-geo/C07400000": {
            "entity_type": "geo.region",
            "name": "Cocos (Keeling) Islands: All cities or breakdown by cities not available",
            "codes": [],
            "aliases": [],
            "parents": [],
        },
    }
    geo_adapter = StaticAdapter(domain="geo", entities=entities)
    patch_adapters(monkeypatch, {"geo": geo_adapter})

    options = make_options(tmp_path)
    plan = BuildPlan(
        recipes=[
            ModuleRecipe(
                module_id="geo.regions-filter",
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

    sqlite_path = outcome.releases[0].output_path / "entities.sqlite"
    with sqlite3.connect(sqlite_path) as conn:
        ids = {row[0] for row in conn.execute("SELECT entity_id FROM entities")}
    # Genuine regions are kept; the three pattern matches are removed.
    assert "region/EU" in ids
    assert "undata-geo/G00001020" in ids  # FRG has no [former]; out of scope
    assert "undata-geo/G00001950" not in ids  # [former]
    assert "undata-geo/G00900010" not in ids  # G009* placeholder
    assert "undata-geo/C07400000" not in ids  # : All cities or breakdown


def test_enrich_report_round_trips_through_build_report_json(
    monkeypatch, tmp_path: Path
) -> None:
    geo_adapter = StaticAdapter(
        domain="geo", entities=make_geo_entities(include_canada=False)
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

    build_report_path = (
        options.runs_root / outcome.run_id / "reports" / "build_report.json"
    )
    build_report = json.loads(build_report_path.read_text())
    assert build_report["stage_statuses"]["enrich"] == "done"
