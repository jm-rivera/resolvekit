"""Focused unit tests for reviewer findings 1, 4, 5, 6, 8.

Finding 1  — resolve_datapacks resolves from disk with an empty ledger
Finding 4  — _snapshot_previous_datapack is idempotent within the same run
Finding 5  — ReleaseCandidate serialize/deserialize round-trip; load_release_candidates
Finding 6  — _ondisk_version returns None for ids lacking "-v"
Finding 8  — distinct snapshot paths for modules sharing a suffix across domains
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from resolvekit.builder.models import (
    BuildOptions,
    ModuleRecipe,
)
from resolvekit.builder.pipeline.types import (
    DomainArtifacts,
    ReleaseCandidate,
    deserialize_release_candidate,
    load_release_candidates,
    serialize_release_candidate,
)

# ---------------------------------------------------------------------------
# Finding 6 — _ondisk_version
# ---------------------------------------------------------------------------


def test_ondisk_version_no_hyphen_v_returns_none(tmp_path: Path) -> None:
    """When datapack_id has no '-v', rpartition must return None (not the whole id)."""
    from resolvekit.builder.pipeline.stages import _ondisk_version

    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    meta = {
        "datapack_id": "geo.countries",  # no "-v" at all
        "module_id": "geo.countries",
        "domain_pack_id": "geo",
        "entity_schema_version": "1.0",
        "feature_schema_version": "geo.features.v1",
        "index_versions": {"fts": "fts5"},
        "build_timestamp": "2026-01-01T00:00:00Z",
        "source_datasets": [],
        "pack_type": "base",
        "store_type": "sqlite",
        "store_file": "entities.sqlite",
        "checksums": {"sqlite": "abc"},
    }
    (pack_dir / "metadata.json").write_text(json.dumps(meta))

    assert _ondisk_version(pack_dir) is None


def test_ondisk_version_trailing_hyphen_v_returns_none(tmp_path: Path) -> None:
    """'some-id-v' has sep but empty version part → must return None."""
    from resolvekit.builder.pipeline.stages import _ondisk_version

    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    meta = {
        "datapack_id": "geo.countries-v",
        "module_id": "geo.countries",
        "domain_pack_id": "geo",
        "entity_schema_version": "1.0",
        "feature_schema_version": "geo.features.v1",
        "index_versions": {"fts": "fts5"},
        "build_timestamp": "2026-01-01T00:00:00Z",
        "source_datasets": [],
        "pack_type": "base",
        "store_type": "sqlite",
        "store_file": "entities.sqlite",
        "checksums": {"sqlite": "abc"},
    }
    (pack_dir / "metadata.json").write_text(json.dumps(meta))

    assert _ondisk_version(pack_dir) is None


def test_ondisk_version_normal_id_returns_version(tmp_path: Path) -> None:
    """Normal datapack_id like 'geo.countries-v2026.5' → version is '2026.5'."""
    from resolvekit.builder.pipeline.stages import _ondisk_version

    pack_dir = tmp_path / "pack"
    pack_dir.mkdir()
    meta = {
        "datapack_id": "geo.countries-v2026.5",
        "module_id": "geo.countries",
        "domain_pack_id": "geo",
        "entity_schema_version": "1.0",
        "feature_schema_version": "geo.features.v1",
        "index_versions": {"fts": "fts5"},
        "build_timestamp": "2026-01-01T00:00:00Z",
        "source_datasets": [],
        "pack_type": "base",
        "store_type": "sqlite",
        "store_file": "entities.sqlite",
        "checksums": {"sqlite": "abc"},
    }
    (pack_dir / "metadata.json").write_text(json.dumps(meta))

    assert _ondisk_version(pack_dir) == "2026.5"


# ---------------------------------------------------------------------------
# Finding 8 — distinct snapshot paths for modules sharing a suffix
# ---------------------------------------------------------------------------


def _fake_context(tmp_path: Path) -> Any:
    """Return a minimal fake BuildContext with run_dir and state."""
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True)
    ctx = MagicMock()
    ctx.run_dir = run_dir
    return ctx


def test_snapshot_path_distinct_for_same_suffix_different_domains(
    tmp_path: Path,
) -> None:
    """geo.countries and org.countries must produce different snapshot paths."""
    from resolvekit.builder.pipeline.stages import _snapshot_previous_datapack

    context = _fake_context(tmp_path)

    # Create two fake output_path directories with entities.sqlite
    geo_output = tmp_path / "geo" / "countries"
    geo_output.mkdir(parents=True)
    (geo_output / "entities.sqlite").write_bytes(b"geo")

    org_output = tmp_path / "org" / "countries"
    org_output.mkdir(parents=True)
    (org_output / "entities.sqlite").write_bytes(b"org")

    geo_snap = _snapshot_previous_datapack(context, "geo.countries", geo_output)
    org_snap = _snapshot_previous_datapack(context, "org.countries", org_output)

    assert geo_snap is not None
    assert org_snap is not None
    assert geo_snap != org_snap, (
        "geo.countries and org.countries must use distinct snapshot directories"
    )


# ---------------------------------------------------------------------------
# Finding 4 — snapshot idempotency within the same run
# ---------------------------------------------------------------------------


def test_snapshot_idempotent_within_same_run(tmp_path: Path) -> None:
    """A second call with the same run_dir reuses the existing snapshot."""
    from resolvekit.builder.pipeline.stages import _snapshot_previous_datapack

    context = _fake_context(tmp_path)

    output = tmp_path / "geo" / "countries"
    output.mkdir(parents=True)
    original_bytes = b"original-data"
    (output / "entities.sqlite").write_bytes(original_bytes)

    snap1 = _snapshot_previous_datapack(context, "geo.countries", output)
    assert snap1 is not None
    first_mtime = snap1.stat().st_mtime

    # Overwrite the on-disk pack (simulating a publish)
    (output / "entities.sqlite").write_bytes(b"new-data-after-first-publish")

    snap2 = _snapshot_previous_datapack(context, "geo.countries", output)
    assert snap2 == snap1, "Second call must return the same path"
    # Snapshot content must be the original, not the overwritten bytes
    assert snap1.read_bytes() == original_bytes, (
        "Snapshot content must be from the first capture, not the re-snapshot"
    )
    # Modification time must not change (file was not re-copied)
    assert snap2.stat().st_mtime == first_mtime


def test_snapshot_returns_none_for_zero_byte_placeholder(tmp_path: Path) -> None:
    """A 0-byte remote placeholder is not a baseline: treat it as no prior pack."""
    from resolvekit.builder.pipeline.stages import _snapshot_previous_datapack

    context = _fake_context(tmp_path)

    output = tmp_path / "geo" / "admin1"
    output.mkdir(parents=True)
    # Remote modules ship a git-tracked 0-byte entities.sqlite until the real
    # pack is published as a release asset.
    (output / "entities.sqlite").write_bytes(b"")

    assert _snapshot_previous_datapack(context, "geo.admin1", output) is None


# ---------------------------------------------------------------------------
# Finding 5 — ReleaseCandidate serialize/deserialize round-trip
# ---------------------------------------------------------------------------


def _make_candidate(tmp_path: Path) -> ReleaseCandidate:
    recipe = ModuleRecipe(
        module_id="geo.countries",
        domain="geo",
        include_symspell=False,
    )
    output_path = tmp_path / "geo" / "countries"
    output_path.mkdir(parents=True)
    prev = tmp_path / "prev" / "entities.sqlite"
    prev.parent.mkdir(parents=True)
    prev.write_bytes(b"x")
    return ReleaseCandidate(
        recipe=recipe,
        version="2026.5",
        output_path=output_path,
        domain_artifacts={
            "geo": DomainArtifacts(
                domain="geo",
                datapack_dir=output_path,
                sqlite_path=output_path / "entities.sqlite",
                metrics={"entity_count": 3},
                qa_checks={"passed": True},
            )
        },
        previous_db_path=prev,
    )


def test_release_candidate_roundtrip(tmp_path: Path) -> None:
    candidate = _make_candidate(tmp_path)
    serialized = serialize_release_candidate(candidate)
    restored = deserialize_release_candidate(serialized)

    assert restored.recipe.module_id == candidate.recipe.module_id
    assert restored.version == candidate.version
    assert restored.output_path == candidate.output_path
    assert restored.previous_db_path == candidate.previous_db_path
    assert "geo" in restored.domain_artifacts
    assert restored.domain_artifacts["geo"].metrics == {"entity_count": 3}


def test_release_candidate_roundtrip_no_previous_db(tmp_path: Path) -> None:
    recipe = ModuleRecipe(module_id="geo.regions", domain="geo", include_symspell=False)
    output_path = tmp_path / "geo" / "regions"
    output_path.mkdir(parents=True)
    candidate = ReleaseCandidate(
        recipe=recipe,
        version="0.0.0",
        output_path=output_path,
        domain_artifacts={},
        previous_db_path=None,
    )
    restored = deserialize_release_candidate(serialize_release_candidate(candidate))
    assert restored.previous_db_path is None


class _FakeState:
    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    def get_meta(self, key: str, default: Any = None) -> Any:
        return self._store.get(key, default)

    def set_meta(self, key: str, value: Any) -> None:
        self._store[key] = value


def _fake_context_with_state(tmp_path: Path) -> Any:
    ctx = MagicMock()
    ctx.run_dir = tmp_path / "run"
    ctx.run_dir.mkdir(parents=True)
    ctx.release_candidates = []
    ctx.state = _FakeState()
    return ctx


def test_load_release_candidates_from_persisted_state(tmp_path: Path) -> None:
    """load_release_candidates reads from state when in-memory list is empty."""
    candidate = _make_candidate(tmp_path)
    ctx = _fake_context_with_state(tmp_path)

    # Persist to state (simulating what stage_package does)
    ctx.state.set_meta(
        "release_candidates",
        [serialize_release_candidate(candidate)],
    )

    # In-memory is empty (resume scenario)
    assert ctx.release_candidates == []

    loaded = load_release_candidates(ctx)

    assert len(loaded) == 1
    assert loaded[0].recipe.module_id == "geo.countries"
    # Also check it was written back onto context
    assert ctx.release_candidates == loaded


def test_load_release_candidates_prefers_in_memory(tmp_path: Path) -> None:
    """load_release_candidates returns in-memory candidates without reading state."""
    candidate = _make_candidate(tmp_path)
    ctx = _fake_context_with_state(tmp_path)
    ctx.release_candidates = [candidate]

    # Put something different in state to verify it's NOT read
    ctx.state.set_meta("release_candidates", [])

    loaded = load_release_candidates(ctx)
    assert loaded == [candidate]


# ---------------------------------------------------------------------------
# Finding 1 — resolve_datapacks from disk with an empty ledger
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _external_shipped_ids — 0-byte placeholder guard
# ---------------------------------------------------------------------------


def test_external_shipped_ids_tolerates_zero_byte_sqlite(tmp_path: Path) -> None:
    """A 0-byte entities.sqlite must not raise; the pack is treated as not-shipped."""
    from resolvekit.builder.pipeline.stages import _external_shipped_ids

    pack_dir = tmp_path / "geo" / "countries"
    pack_dir.mkdir(parents=True)
    # metadata.json so iter_datapack_dirs picks this directory up as a pack.
    (pack_dir / "metadata.json").write_text(
        json.dumps(
            {"datapack_id": "geo.countries-v0.0.0", "module_id": "geo.countries"}
        )
    )
    # 0-byte placeholder — no SQLite header, no tables.
    (pack_dir / "entities.sqlite").write_bytes(b"")

    result = _external_shipped_ids(datapacks_root=tmp_path, exclude_module_ids=set())

    assert result == set(), (
        "A 0-byte entities.sqlite should yield an empty id set, not raise"
    )


def test_resolve_datapacks_resolves_from_disk_with_empty_ledger(
    tmp_path: Path,
) -> None:
    """Module resolves from the on-disk pack even when the release ledger is empty."""
    from scripts.benchmark.benchmark_common import resolve_datapacks

    # Create a fake on-disk pack
    datapacks_root = tmp_path / "src" / "resolvekit" / "_data"
    pack_dir = datapacks_root / "geo" / "countries"
    pack_dir.mkdir(parents=True)
    (pack_dir / "entities.sqlite").write_bytes(b"fake-sqlite")
    (pack_dir / "metadata.json").write_text(
        json.dumps({"datapack_id": "geo.countries-v0.0.0"})
    )

    build_root = tmp_path / "build"
    build_root.mkdir(parents=True)

    # Patch BuildOptions to use our isolated datapacks_root
    # (the ledger file doesn't exist at all — simulates a plain build())
    from unittest.mock import patch

    def _fake_options(build_root: Path) -> BuildOptions:
        return BuildOptions(build_root=build_root, datapacks_root=datapacks_root)

    with patch(
        "scripts.benchmark.benchmark_common.BuildOptions",
        side_effect=_fake_options,
    ):
        result = resolve_datapacks(
            datapacks=[],
            modules=["geo.countries"],
            build_root=build_root,
        )

    assert len(result) == 1
    assert Path(str(result[0])).resolve() == pack_dir.resolve()
