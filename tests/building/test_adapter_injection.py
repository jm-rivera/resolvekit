"""Tests for adapter_builder injection into build() and resume()."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from resolvekit.builder.api import build, resume
from resolvekit.builder.models import BuildOptions, BuildPlan, ModuleRecipe


class _StubAdapter:
    """Minimal static adapter sufficient to drive a geo build."""

    def __init__(self, domain: str, entities: dict[str, dict[str, Any]]) -> None:
        self.domain = domain
        self.entities = entities

    def supported_domains(self) -> set[str]:
        return {self.domain}

    def discover_entities(self, domain: str) -> list[str]:
        return sorted(self.entities)

    def discover_entities_filtered(
        self,
        domain: str,
        include_entity_types: list[str],
        include_relation_targets: bool,
    ) -> list[str]:
        _ = include_relation_targets
        ids = self.discover_entities(domain)
        if not include_entity_types:
            return ids
        allowed = {t.strip() for t in include_entity_types if t.strip()}
        return [eid for eid in ids if self.entities[eid]["entity_type"] in allowed]

    def filter_discovered_entities(
        self,
        domain: str,
        entity_ids: list[str],
        include_entity_types: list[str],
    ) -> list[str]:
        allowed = {t.strip() for t in include_entity_types if t.strip()}
        if not allowed:
            return list(entity_ids)
        return [
            eid for eid in entity_ids if self.entities[eid]["entity_type"] in allowed
        ]

    def fetch_raw_chunk(self, domain: str, entity_ids: list[str]) -> dict[str, Any]:
        entities: dict[str, dict[str, Any]] = {}
        codes: dict[str, list[dict[str, Any]]] = {}
        aliases: dict[str, list[dict[str, Any]]] = {}
        parents: dict[str, list[str]] = {}
        for eid in entity_ids:
            row = self.entities[eid]
            entities[eid] = {
                "entity_type": row["entity_type"],
                "name": row["name"],
                "centroid_lat": row.get("centroid_lat"),
                "centroid_lon": row.get("centroid_lon"),
            }
            codes[eid] = []
            aliases[eid] = []
            parents[eid] = list(row.get("parents", []))
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
        entity_rows: list[dict[str, Any]] = []
        name_rows: list[dict[str, Any]] = []
        code_rows: list[dict[str, Any]] = []
        relation_rows: list[dict[str, Any]] = []

        for eid, payload in raw_chunk["entities"].items():
            canonical_name = str(payload["name"])
            entity_rows.append(
                {
                    "entity_id": eid,
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
                    "entity_id": eid,
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
                    "entity_id": eid,
                    "system": "dcid",
                    "value": eid,
                    "value_norm": eid.casefold(),
                }
            )

        for eid, parent_ids in raw_chunk["parents"].items():
            for pid in parent_ids:
                relation_rows.append(
                    {
                        "entity_id": eid,
                        "relation_type": "contained_in",
                        "target_id": pid,
                    }
                )

        return {
            "entities": entity_rows,
            "names": name_rows,
            "codes": code_rows,
            "relations": relation_rows,
        }


def _make_plan(tmp_path: Path) -> BuildPlan:
    options = BuildOptions(
        build_root=tmp_path / "build",
        datapacks_root=tmp_path / "datapacks",
        reports_root=tmp_path / "reports",
        max_workers=1,
        chunk_size=1,
        max_retries=1,
        retry_base_delay_sec=0.0,
        retry_max_delay_sec=0.0,
    )
    recipe = ModuleRecipe(
        module_id="geo.world",
        domain="geo",
        include_symspell=False,
    )
    return BuildPlan(recipes=[recipe], options=options)


def _make_stub_adapter() -> _StubAdapter:
    entities: dict[str, dict[str, Any]] = {
        "region/NAM": {
            "entity_type": "geo.region",
            "name": "North America",
            "parents": [],
        },
        "country/USA": {
            "entity_type": "geo.country",
            "name": "United States",
            "parents": ["region/NAM"],
        },
    }
    return _StubAdapter(domain="geo", entities=entities)


def test_build_with_injected_adapter_builder_succeeds_without_monkeypatch(
    tmp_path: Path,
) -> None:
    """build() with adapter_builder= routes to the injected factory, no module-global patch needed."""
    stub = _make_stub_adapter()

    outcome = build(
        _make_plan(tmp_path),
        adapter_builder=lambda _plan: {"geo": stub},
    )

    assert outcome.status.value == "success", outcome.errors


class _FailOnceThenSucceedAdapter(_StubAdapter):
    """Raises RuntimeError on the first fetch call, then succeeds on subsequent calls."""

    def __init__(self, domain: str, entities: dict[str, dict[str, Any]]) -> None:
        super().__init__(domain=domain, entities=entities)
        self._fetch_calls = 0

    def fetch_raw_chunk(self, domain: str, entity_ids: list[str]) -> dict[str, Any]:
        if self._fetch_calls == 0:
            self._fetch_calls += 1
            raise RuntimeError("simulated transient failure")
        self._fetch_calls += 1
        return super().fetch_raw_chunk(domain, entity_ids)


def test_resume_with_injected_adapter_builder_succeeds_without_monkeypatch(
    tmp_path: Path,
) -> None:
    """resume() with adapter_builder= routes to the injected factory, no module-global patch needed."""
    options = BuildOptions(
        build_root=tmp_path / "build",
        datapacks_root=tmp_path / "datapacks",
        reports_root=tmp_path / "reports",
        max_workers=1,
        chunk_size=1,
        max_retries=1,
        retry_base_delay_sec=0.0,
        retry_max_delay_sec=0.0,
    )
    entities: dict[str, dict[str, Any]] = {
        "country/USA": {
            "entity_type": "geo.country",
            "name": "United States",
            "parents": [],
        }
    }
    # Adapter raises on the first fetch, leaving the initial build failed — resumable.
    fail_once_stub = _FailOnceThenSucceedAdapter(domain="geo", entities=entities)

    recipe = ModuleRecipe(
        module_id="geo.world",
        domain="geo",
        include_symspell=False,
    )
    first_plan = BuildPlan(recipes=[recipe], options=options)
    first = build(first_plan, adapter_builder=lambda _plan: {"geo": fail_once_stub})
    assert first.status.value == "failed", f"expected failed, got {first.status.value}"

    # resume() with a higher retry budget and our own adapter_builder — no monkeypatch.
    resume_options = options.model_copy(update={"max_retries": 3})
    resumed = resume(
        first.run_id,
        options=resume_options,
        adapter_builder=lambda _plan: {"geo": fail_once_stub},
    )

    assert resumed.status.value == "success", resumed.errors
