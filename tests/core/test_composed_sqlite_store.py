"""Tests for composed SQLite stores (cache miss + hit paths)."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
from pathlib import Path

import pytest

from resolvekit.core.datapack import NORMALIZER_VERSION, DataPackLoader
from resolvekit.core.errors import ModuleConflictError
from resolvekit.core.store.composed_sqlite import (
    PersistentSQLiteEntityStore,
    TemporarySQLiteEntityStore,
    _compose_cache_key,
    compose_base_module_store,
)


def _make_datapack(
    base_path: Path,
    *,
    module_id: str,
    entity_rows: list[tuple[str, str, str]],
    relation_rows: list[tuple[str, str, str]] | None = None,
    domain: str = "geo",
    datapack_id: str | None = None,
) -> Path:
    base_path.mkdir(parents=True, exist_ok=True)
    db_path = base_path / "entities.sqlite"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE entities (
            entity_id TEXT PRIMARY KEY,
            entity_type TEXT NOT NULL,
            canonical_name TEXT NOT NULL,
            canonical_name_norm TEXT NOT NULL,
            valid_from TEXT,
            valid_until TEXT
        );
        CREATE TABLE names (
            entity_id TEXT NOT NULL,
            name_kind TEXT NOT NULL,
            value TEXT NOT NULL,
            value_norm TEXT NOT NULL,
            lang TEXT,
            is_preferred INTEGER DEFAULT 0
        );
        CREATE TABLE codes (
            entity_id TEXT NOT NULL,
            system TEXT NOT NULL,
            value TEXT NOT NULL,
            value_norm TEXT NOT NULL,
            PRIMARY KEY (entity_id, system)
        );
        CREATE TABLE relations (
            entity_id TEXT NOT NULL,
            relation_type TEXT NOT NULL,
            target_id TEXT NOT NULL
        );
        CREATE VIRTUAL TABLE names_fts USING fts5(entity_id, value_norm);
        """
    )

    for entity_id, entity_type, canonical_name in entity_rows:
        normalized = canonical_name.casefold()
        conn.execute(
            "INSERT INTO entities VALUES (?, ?, ?, ?, NULL, NULL)",
            (entity_id, entity_type, canonical_name, normalized),
        )
        conn.execute(
            "INSERT INTO names VALUES (?, 'canonical', ?, ?, 'en', 1)",
            (entity_id, canonical_name, normalized),
        )
        conn.execute(
            "INSERT INTO names_fts(entity_id, value_norm) VALUES (?, ?)",
            (entity_id, normalized),
        )

    for entity_id, relation_type, target_id in relation_rows or []:
        conn.execute(
            "INSERT INTO relations VALUES (?, ?, ?)",
            (entity_id, relation_type, target_id),
        )

    conn.commit()
    conn.close()

    pack_id = datapack_id or f"{module_id}-v1"
    metadata = {
        "datapack_id": pack_id,
        "module_id": module_id,
        "domain_pack_id": domain,
        "module_dependencies": [],
        "entity_schema_version": "1.0",
        "feature_schema_version": f"{domain}.features.v1",
        "normalizer_version": NORMALIZER_VERSION,
        "index_versions": {"fts": "fts5"},
        "build_timestamp": "2024-01-01T00:00:00Z",
        "source_datasets": ["test"],
    }
    (base_path / "metadata.json").write_text(json.dumps(metadata))
    return base_path


def test_compose_base_module_store_merges_entities_relations_and_cleans_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache-miss build merges entities/relations; cache hit is persistent."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("RESOLVEKIT_CACHE_DIR", str(cache_dir))

    loader = DataPackLoader()
    regions = loader.load(
        _make_datapack(
            tmp_path / "geo_regions",
            module_id="geo.regions",
            entity_rows=[("region/NAM", "geo.region", "North America")],
        )
    )
    countries = loader.load(
        _make_datapack(
            tmp_path / "geo_countries",
            module_id="geo.countries",
            entity_rows=[("country/USA", "geo.country", "United States")],
            relation_rows=[("country/USA", "contained_in", "region/NAM")],
        )
    )

    # Cache miss: result is a PersistentSQLiteEntityStore
    # backed by the cache file (not TemporarySQLiteEntityStore).
    store = compose_base_module_store(domain="geo", loaded_packs=[regions, countries])
    db_path = store._db_path

    assert store.lookup_name_exact("north america") == ["region/NAM"]
    assert store.lookup_name_exact("united states") == ["country/USA"]
    assert store.get_relations("country/USA", "contained_in") == ["region/NAM"]
    assert db_path.exists()

    # Close: PersistentSQLiteEntityStore does NOT delete the file.
    store.close()
    assert db_path.exists(), "Cache file must persist after close()"


def test_compose_base_module_store_rejects_overlapping_entities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("RESOLVEKIT_CACHE_DIR", str(cache_dir))

    loader = DataPackLoader()
    left = loader.load(
        _make_datapack(
            tmp_path / "geo_one",
            module_id="geo.one",
            entity_rows=[("country/USA", "geo.country", "United States")],
        )
    )
    right = loader.load(
        _make_datapack(
            tmp_path / "geo_two",
            module_id="geo.two",
            entity_rows=[("country/USA", "geo.country", "United States of America")],
        )
    )

    with pytest.raises(ModuleConflictError):
        compose_base_module_store(domain="geo", loaded_packs=[left, right])


def test_cache_hit_returns_identical_entity_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second compose_base_module_store call is a cache hit with same entities."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("RESOLVEKIT_CACHE_DIR", str(cache_dir))

    loader = DataPackLoader()
    regions = loader.load(
        _make_datapack(
            tmp_path / "geo_regions",
            module_id="geo.regions",
            entity_rows=[("region/NAM", "geo.region", "North America")],
        )
    )
    countries = loader.load(
        _make_datapack(
            tmp_path / "geo_countries",
            module_id="geo.countries",
            entity_rows=[("country/USA", "geo.country", "United States")],
        )
    )

    store1 = compose_base_module_store(domain="geo", loaded_packs=[regions, countries])
    entities1 = store1.all_entity_ids()
    fts1 = store1.lookup_name_exact("north america")
    store1.close()

    # Same inputs with existing cache should be a cache hit.
    store2 = compose_base_module_store(domain="geo", loaded_packs=[regions, countries])
    assert isinstance(store2, PersistentSQLiteEntityStore), (
        "Cache hit must return PersistentSQLiteEntityStore"
    )
    entities2 = store2.all_entity_ids()
    fts2 = store2.lookup_name_exact("north america")
    store2.close()

    assert entities1 == entities2
    assert fts1 == fts2 == ["region/NAM"]


def test_cache_hit_fts_works(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache-hit store has a working FTS index."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("RESOLVEKIT_CACHE_DIR", str(cache_dir))

    loader = DataPackLoader()
    pack = loader.load(
        _make_datapack(
            tmp_path / "geo_a",
            module_id="geo.a",
            entity_rows=[("r/A", "geo.region", "Albuquerque")],
        )
    )
    pack2 = loader.load(
        _make_datapack(
            tmp_path / "geo_b",
            module_id="geo.b",
            entity_rows=[("r/B", "geo.region", "Boston")],
        )
    )

    # Populate cache.
    s1 = compose_base_module_store(domain="geo", loaded_packs=[pack, pack2])
    s1.close()

    # Hit.
    s2 = compose_base_module_store(domain="geo", loaded_packs=[pack, pack2])
    assert isinstance(s2, PersistentSQLiteEntityStore)
    results = s2.search_fulltext("albuquerque")
    s2.close()
    entity_ids = [r[0] for r in results]
    assert "r/A" in entity_ids


def test_cache_hit_does_not_delete_file_on_close(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closing a cache-hit store must NOT remove the cached DB file."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("RESOLVEKIT_CACHE_DIR", str(cache_dir))

    loader = DataPackLoader()
    pack_a = loader.load(
        _make_datapack(
            tmp_path / "a",
            module_id="geo.a",
            entity_rows=[("e/A", "geo.x", "Alpha")],
        )
    )
    pack_b = loader.load(
        _make_datapack(
            tmp_path / "b",
            module_id="geo.b",
            entity_rows=[("e/B", "geo.x", "Beta")],
        )
    )

    # First build populates cache.
    s1 = compose_base_module_store(domain="geo", loaded_packs=[pack_a, pack_b])
    cache_path = s1._db_path
    s1.close()

    # Confirm the cache file exists after close.
    assert cache_path.exists()

    # Open a second time (cache hit).
    s2 = compose_base_module_store(domain="geo", loaded_packs=[pack_a, pack_b])
    assert s2._db_path == cache_path
    s2.close()

    # File must still exist after closing the cache-hit store.
    assert cache_path.exists(), "Cache file deleted on close — must persist"


def test_cache_key_changes_when_datapack_id_changes(
    tmp_path: Path,
) -> None:
    """Changing datapack_id forces a different cache key (triggers rebuild)."""
    loader = DataPackLoader()
    pack_v1 = loader.load(
        _make_datapack(
            tmp_path / "geo_v1",
            module_id="geo.a",
            datapack_id="geo.a-v1",
            entity_rows=[("e/1", "geo.x", "Old Name")],
        )
    )
    pack_v2 = loader.load(
        _make_datapack(
            tmp_path / "geo_v2",
            module_id="geo.a",
            datapack_id="geo.a-v2",
            entity_rows=[("e/1", "geo.x", "New Name")],
        )
    )

    # Need a second pack because single-pack shortcut bypasses key logic.
    filler = loader.load(
        _make_datapack(
            tmp_path / "geo_fill",
            module_id="geo.fill",
            datapack_id="geo.fill-v1",
            entity_rows=[("e/fill", "geo.x", "Filler")],
        )
    )

    key_v1 = _compose_cache_key("geo", [pack_v1, filler])
    key_v2 = _compose_cache_key("geo", [pack_v2, filler])

    assert key_v1 != key_v2, "datapack_id change must produce a different cache key"


def test_cache_key_stable_across_pack_order(
    tmp_path: Path,
) -> None:
    """Cache key is order-independent (sorted by module_id)."""
    loader = DataPackLoader()
    pack_a = loader.load(
        _make_datapack(
            tmp_path / "a",
            module_id="geo.a",
            datapack_id="geo.a-v1",
            entity_rows=[("e/a", "geo.x", "Alpha")],
        )
    )
    pack_b = loader.load(
        _make_datapack(
            tmp_path / "b",
            module_id="geo.b",
            datapack_id="geo.b-v1",
            entity_rows=[("e/b", "geo.x", "Beta")],
        )
    )

    key_ab = _compose_cache_key("geo", [pack_a, pack_b])
    key_ba = _compose_cache_key("geo", [pack_b, pack_a])
    assert key_ab == key_ba, "Cache key must be stable regardless of input order"


def test_concurrent_builds_do_not_corrupt_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent writes to the same cache slot via os.replace are race-safe."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setenv("RESOLVEKIT_CACHE_DIR", str(cache_dir))

    loader = DataPackLoader()
    pack_a = loader.load(
        _make_datapack(
            tmp_path / "a",
            module_id="geo.a",
            entity_rows=[("e/A", "geo.x", "Alpha")],
        )
    )
    pack_b = loader.load(
        _make_datapack(
            tmp_path / "b",
            module_id="geo.b",
            entity_rows=[("e/B", "geo.x", "Beta")],
        )
    )

    stores: list[SQLiteEntityStore] = []
    errors: list[Exception] = []
    lock = threading.Lock()

    def _build() -> None:
        try:
            s = compose_base_module_store(domain="geo", loaded_packs=[pack_a, pack_b])
            with lock:
                stores.append(s)
        except Exception as exc:
            with lock:
                errors.append(exc)

    threads = [threading.Thread(target=_build) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Concurrent build raised: {errors}"
    assert len(stores) == 4

    for s in stores:
        assert s.all_entity_ids() == {"e/A", "e/B"}
        s.close()

    # Cache file must exist and be readable after all closes.
    from resolvekit.core.store.composed_sqlite import (
        _cache_path_for_key,
        _compose_cache_key,
    )

    cache_path = _cache_path_for_key(_compose_cache_key("geo", [pack_a, pack_b]))
    assert cache_path.exists()


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows ignores POSIX directory permission bits, so a chmod 0o555 "
    "cache dir stays writable and the unwritable-cache path can't be simulated.",
)
def test_compose_falls_back_to_temp_store_when_cache_unwritable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the cache dir is read-only, a TemporarySQLiteEntityStore is used."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True)
    # Make it unwritable.
    os.chmod(cache_dir, 0o555)

    monkeypatch.setenv("RESOLVEKIT_CACHE_DIR", str(cache_dir))

    loader = DataPackLoader()
    pack_a = loader.load(
        _make_datapack(
            tmp_path / "a",
            module_id="geo.a",
            entity_rows=[("e/A", "geo.x", "Alpha")],
        )
    )
    pack_b = loader.load(
        _make_datapack(
            tmp_path / "b",
            module_id="geo.b",
            entity_rows=[("e/B", "geo.x", "Beta")],
        )
    )

    try:
        store = compose_base_module_store(domain="geo", loaded_packs=[pack_a, pack_b])
        assert isinstance(store, TemporarySQLiteEntityStore), (
            "Should fall back to TemporarySQLiteEntityStore when cache is unwritable"
        )
        assert store.all_entity_ids() == {"e/A", "e/B"}
        db_path = store._db_path
        store.close()
        # After close, temp store cleans up.
        assert not db_path.exists()
    finally:
        os.chmod(cache_dir, 0o755)


from resolvekit.core.store.sqlite import SQLiteEntityStore  # noqa: E402
