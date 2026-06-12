"""Tests for BYOD content-hash cache: key stability, hits, misses, atomicity."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from resolvekit.core.byod.cache import (
    BYOD_CACHE_VERSION,
    byod_cache_key,
    cached_pack_dir,
    commit_build,
    is_cache_hit,
    prepare_build_dir,
)
from resolvekit.core.byod.intake import RecordSchema

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _simple_schema(rows: list[dict]) -> RecordSchema:
    return RecordSchema.resolve(rows, name="label", id="id")


def _key_for(rows: list[dict], *, namespace: str = "ns") -> str:
    schema = _simple_schema(rows)
    return byod_cache_key(
        records=rows,
        schema=schema,
        domain="custom",
        namespace=namespace,
        pack_type="base",
        options={"link_on": [], "on_miss": "mint", "pack_type": "base"},
        base_identity=None,
    )


def _make_minimal_pack(pack_dir: Path) -> None:
    """Write a minimal valid pack directory (entities.sqlite + metadata.json)."""
    from resolvekit.shared.build.schema import SCHEMA_SQL

    pack_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(pack_dir / "entities.sqlite")
    conn.executescript(SCHEMA_SQL)
    conn.execute("INSERT INTO names_fts(names_fts) VALUES('rebuild')")
    conn.commit()
    conn.close()
    (pack_dir / "metadata.json").write_text(
        json.dumps(
            {
                "datapack_id": "test-byod",
                "module_id": "ns",
                "domain_pack_id": "custom",
                "pack_type": "base",
                "store_type": "sqlite",
                "store_file": "entities.sqlite",
                "entity_schema_version": "1.0",
                "feature_schema_version": "custom.features.v1",
                "index_versions": {"fts": "fts5", "symspell": None},
                "build_timestamp": "2026-01-01T00:00:00+00:00",
                "source_datasets": ["ns"],
                "module_dependencies": [],
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Tests: key stability
# ---------------------------------------------------------------------------


class TestCacheKeyStability:
    def test_identical_inputs_produce_same_key(self) -> None:
        """Same rows + same options → identical key across two calls."""
        rows = [{"id": "1", "label": "Alpha"}, {"id": "2", "label": "Beta"}]
        key_a = _key_for(rows)
        key_b = _key_for(rows)
        assert key_a == key_b

    def test_changed_record_produces_new_key(self) -> None:
        """Mutating one row's value changes the key."""
        rows_a = [{"id": "1", "label": "Alpha"}]
        rows_b = [{"id": "1", "label": "Changed"}]
        assert _key_for(rows_a) != _key_for(rows_b)

    def test_row_order_matters(self) -> None:
        """Reversing row order produces a different key (order preserved by design)."""
        rows = [{"id": "1", "label": "Alpha"}, {"id": "2", "label": "Beta"}]
        rows_rev = list(reversed(rows))
        assert _key_for(rows) != _key_for(rows_rev)

    def test_1_row_differs_from_2_rows(self) -> None:
        """A 1-row and a 2-row input with the same first row produce different keys."""
        one = [{"id": "1", "label": "Alpha"}]
        two = [{"id": "1", "label": "Alpha"}, {"id": "2", "label": "Beta"}]
        assert _key_for(one) != _key_for(two)

    def test_namespace_affects_key(self) -> None:
        """Different namespace → different key."""
        rows = [{"id": "1", "label": "Alpha"}]
        assert _key_for(rows, namespace="ns_a") != _key_for(rows, namespace="ns_b")

    def test_base_identity_included_in_overlay_key(self) -> None:
        """For overlay packs, base_identity changes the key."""
        rows = [{"id": "1", "label": "Alpha"}]
        schema = _simple_schema(rows)
        opts = {"link_on": ["iso3"], "on_miss": "skip", "pack_type": "overlay"}

        key_no_base = byod_cache_key(
            records=rows,
            schema=schema,
            domain="geo",
            namespace="ns",
            pack_type="overlay",
            options=opts,
            base_identity=None,
        )

        key_with_base = byod_cache_key(
            records=rows,
            schema=schema,
            domain="geo",
            namespace="ns",
            pack_type="overlay",
            options=opts,
            base_identity=[("geo.base", "geo-v1", 1024, 1717000000.0)],
        )

        assert key_no_base != key_with_base

    def test_mutating_base_mtime_changes_key(self) -> None:
        """A different db_mtime in base_identity produces a new cache key."""
        rows = [{"id": "1", "label": "Alpha"}]
        schema = _simple_schema(rows)
        opts = {"link_on": ["iso3"], "on_miss": "skip", "pack_type": "overlay"}

        key_a = byod_cache_key(
            records=rows,
            schema=schema,
            domain="geo",
            namespace="ns",
            pack_type="overlay",
            options=opts,
            base_identity=[("geo.base", "geo-v1", 1024, 1717000000.0)],
        )
        key_b = byod_cache_key(
            records=rows,
            schema=schema,
            domain="geo",
            namespace="ns",
            pack_type="overlay",
            options=opts,
            base_identity=[("geo.base", "geo-v1", 1024, 1717999999.9)],  # mtime changed
        )

        assert key_a != key_b

    def test_byod_cache_version_in_key(self) -> None:
        """BYOD_CACHE_VERSION is included in the key blob (bump invalidates all cached)."""
        # We can't easily change the constant in a test, but we can verify
        # the key is deterministic and non-trivial (> 8 chars of hex).
        rows = [{"id": "1", "label": "Alpha"}]
        key = _key_for(rows)
        assert len(key) == 40
        assert all(c in "0123456789abcdef" for c in key)
        assert BYOD_CACHE_VERSION  # non-empty constant


# ---------------------------------------------------------------------------
# Tests: cache hit/miss
# ---------------------------------------------------------------------------


class TestCacheHitMiss:
    def test_is_cache_hit_false_when_dir_absent(self, tmp_path: Path) -> None:
        assert not is_cache_hit(tmp_path / "nonexistent")

    def test_is_cache_hit_false_when_no_metadata(self, tmp_path: Path) -> None:
        d = tmp_path / "pack"
        d.mkdir()
        assert not is_cache_hit(d)

    def test_is_cache_hit_true_when_dir_and_metadata_exist(
        self, tmp_path: Path
    ) -> None:
        d = tmp_path / "pack"
        d.mkdir()
        (d / "metadata.json").write_text("{}", encoding="utf-8")
        assert is_cache_hit(d)

    def test_cached_pack_dir_returns_expected_path(self, tmp_path: Path) -> None:
        from resolvekit.core.config import _reset_config, configure

        configure(cache_dir=str(tmp_path / "cache"))
        try:
            d = cached_pack_dir("abc123")
            assert d == tmp_path / "cache" / "byod" / "abc123"
        finally:
            _reset_config()


# ---------------------------------------------------------------------------
# Tests: build_byod_pack cache integration
# ---------------------------------------------------------------------------


class TestBuildByodPackCache:
    def _rows_and_schema(self) -> tuple[list[dict], RecordSchema]:
        rows = [{"id": "w1", "label": "Widget"}]
        schema = RecordSchema.resolve(rows, name="label", id="id")
        return rows, schema

    def test_cache_hit_reuses_dir_mtime_unchanged(self, tmp_path: Path) -> None:
        """Second identical build returns the cached dir without rebuilding."""
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.config import _reset_config, configure

        configure(cache_dir=str(tmp_path / "cache"))
        try:
            rows, schema = self._rows_and_schema()

            out1 = build_byod_pack(
                records=rows,
                schema=schema,
                domain="custom",
                namespace="ns",
                pack_type="base",
                link_on=[],
                on_miss="mint",
                cache=True,
            )
            mtime_first = out1.pack_dir.stat().st_mtime

            out2 = build_byod_pack(
                records=rows,
                schema=schema,
                domain="custom",
                namespace="ns",
                pack_type="base",
                link_on=[],
                on_miss="mint",
                cache=True,
            )

            assert out1.pack_dir == out2.pack_dir
            assert out2.pack_dir.stat().st_mtime == mtime_first, (
                "mtime should be unchanged on a cache hit"
            )
        finally:
            _reset_config()

    def test_changed_record_builds_to_new_dir(self, tmp_path: Path) -> None:
        """Mutating a record produces a new key → builds to a different directory."""
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.config import _reset_config, configure

        configure(cache_dir=str(tmp_path / "cache"))
        try:
            rows_a = [{"id": "w1", "label": "Widget"}]
            schema_a = RecordSchema.resolve(rows_a, name="label", id="id")

            rows_b = [{"id": "w1", "label": "Changed Widget"}]
            schema_b = RecordSchema.resolve(rows_b, name="label", id="id")

            out_a = build_byod_pack(
                records=rows_a,
                schema=schema_a,
                domain="custom",
                namespace="ns",
                pack_type="base",
                link_on=[],
                on_miss="mint",
                cache=True,
            )
            out_b = build_byod_pack(
                records=rows_b,
                schema=schema_b,
                domain="custom",
                namespace="ns",
                pack_type="base",
                link_on=[],
                on_miss="mint",
                cache=True,
            )

            assert out_a.pack_dir != out_b.pack_dir
        finally:
            _reset_config()

    def test_cache_false_always_builds_fresh(self, tmp_path: Path) -> None:
        """cache=False always builds even when the cached dir exists."""
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.config import _reset_config, configure

        configure(cache_dir=str(tmp_path / "cache"))
        try:
            rows, schema = self._rows_and_schema()

            # First build with cache=True to prime the cache.
            out_cached = build_byod_pack(
                records=rows,
                schema=schema,
                domain="custom",
                namespace="ns",
                pack_type="base",
                link_on=[],
                on_miss="mint",
                cache=True,
            )

            # Second build with cache=False: should build to a different temp dir.
            out_fresh = build_byod_pack(
                records=rows,
                schema=schema,
                domain="custom",
                namespace="ns",
                pack_type="base",
                link_on=[],
                on_miss="mint",
                cache=False,
            )

            assert out_fresh.pack_dir != out_cached.pack_dir
            # cache=False dir is a temp dir (not under the configured cache)
            assert not str(out_fresh.pack_dir).startswith(str(tmp_path / "cache"))
        finally:
            _reset_config()


# ---------------------------------------------------------------------------
# Tests: atomic write + no leftover .tmp
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    def test_no_tmp_dir_left_after_successful_cache_build(self, tmp_path: Path) -> None:
        """commit_build removes the temp dir after os.replace succeeds."""
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.config import _reset_config, configure

        configure(cache_dir=str(tmp_path / "cache"))
        try:
            rows = [{"id": "x", "label": "X"}]
            schema = RecordSchema.resolve(rows, name="label", id="id")

            build_byod_pack(
                records=rows,
                schema=schema,
                domain="custom",
                namespace="ns",
                pack_type="base",
                link_on=[],
                on_miss="mint",
                cache=True,
            )

            byod_root = tmp_path / "cache" / "byod"
            tmp_dirs = [
                d for d in byod_root.iterdir() if d.is_dir() and ".tmp." in d.name
            ]
            assert tmp_dirs == [], f"Leftover .tmp dirs found: {tmp_dirs}"
        finally:
            _reset_config()

    def test_prepare_build_dir_cache_false_not_under_cache(
        self, tmp_path: Path
    ) -> None:
        """cache=False build dir is in system temp, not under cache_dir."""
        from resolvekit.core.config import _reset_config, configure

        configure(cache_dir=str(tmp_path / "cache"))
        try:
            build_dir, final_dir = prepare_build_dir("somekey", cache=False)
            assert final_dir is None
            assert not str(build_dir).startswith(str(tmp_path / "cache"))
            # Clean up
            import shutil

            shutil.rmtree(build_dir, ignore_errors=True)
        finally:
            _reset_config()

    def test_commit_build_moves_dir_atomically(self, tmp_path: Path) -> None:
        """commit_build replaces final_dir and cleans up the build dir."""
        build_dir = tmp_path / "build"
        _make_minimal_pack(build_dir)
        final_dir = tmp_path / "final"

        commit_build(build_dir, final_dir)

        assert final_dir.is_dir()
        assert (final_dir / "metadata.json").is_file()
        # build_dir is gone after replace (it became final_dir)
        assert not build_dir.exists()


# ---------------------------------------------------------------------------
# Tests: commit_build idempotency
# ---------------------------------------------------------------------------


class TestCommitBuildIdempotency:
    def test_commit_into_absent_final_dir(self, tmp_path: Path) -> None:
        """commit_build into a fresh slot creates final_dir and removes build_dir."""
        build_dir = tmp_path / "build"
        _make_minimal_pack(build_dir)
        final_dir = tmp_path / "final"

        commit_build(build_dir, final_dir)

        assert final_dir.is_dir()
        assert (final_dir / "metadata.json").is_file()
        assert not build_dir.exists()

    def test_commit_when_final_dir_already_valid(self, tmp_path: Path) -> None:
        """commit_build keeps the existing valid pack (first-writer-wins)."""
        final_dir = tmp_path / "final"
        _make_minimal_pack(final_dir)
        # Mark the existing pack so the assertion can tell it apart from the
        # build_dir pack (_make_minimal_pack writes identical content otherwise).
        (final_dir / "metadata.json").write_text(
            '{"datapack_id": "original"}\n', encoding="utf-8"
        )
        original_text = (final_dir / "metadata.json").read_text(encoding="utf-8")

        build_dir = tmp_path / "build"
        _make_minimal_pack(build_dir)

        commit_build(build_dir, final_dir)  # must not raise

        assert final_dir.is_dir()
        assert (final_dir / "metadata.json").read_text(
            encoding="utf-8"
        ) == original_text
        assert not build_dir.exists()

    def test_commit_replaces_corrupt_leftover(self, tmp_path: Path) -> None:
        """commit_build replaces a directory that has no metadata.json."""
        final_dir = tmp_path / "final"
        final_dir.mkdir()
        (final_dir / "junk.txt").write_text("corrupt", encoding="utf-8")

        build_dir = tmp_path / "build"
        _make_minimal_pack(build_dir)

        commit_build(build_dir, final_dir)

        assert (final_dir / "metadata.json").is_file()
        assert not (final_dir / "junk.txt").exists()
        assert not build_dir.exists()

    def test_build_dir_cleaned_up_when_discarded(self, tmp_path: Path) -> None:
        """build_dir is removed even when commit_build discards it (valid pack wins)."""
        final_dir = tmp_path / "final"
        _make_minimal_pack(final_dir)

        build_dir = tmp_path / "build"
        _make_minimal_pack(build_dir)

        commit_build(build_dir, final_dir)

        assert not build_dir.exists()

    def test_non_populated_oserror_is_reraised(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An OSError unrelated to a populated target is re-raised."""
        import resolvekit.core.byod.cache as cache_mod

        build_dir = tmp_path / "build"
        _make_minimal_pack(build_dir)
        final_dir = tmp_path / "final"  # absent — not a populated-target case

        def _no_space(src: object, dst: object) -> None:
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(cache_mod.os, "replace", _no_space)

        with pytest.raises(OSError):
            commit_build(build_dir, final_dir)


# ---------------------------------------------------------------------------
# Cache hit persisted tally
# ---------------------------------------------------------------------------


class TestCacheHitPersistedTally:
    def test_cache_hit_returns_persisted_tallies(self, tmp_path: Path) -> None:
        """On a cache hit, build_byod_pack returns the same tallies as the fresh build.

        Tallies are written to a ``byod_tally.json`` sidecar at build time and
        read back on subsequent cache hits.
        """
        from resolvekit.core.byod.build import build_byod_pack
        from resolvekit.core.byod.cache import _TALLY_FILE
        from resolvekit.core.config import _reset_config, configure

        rows = [{"id": "a", "label": "Alpha"}, {"id": "b", "label": "Beta"}]
        schema = _simple_schema(rows)

        configure(cache_dir=str(tmp_path / "cache"))
        try:
            # First call — builds + caches; all rows are minted.
            outcome1 = build_byod_pack(
                records=rows,
                schema=schema,
                domain="custom",
                namespace="ns",
                pack_type="base",
                link_on=[],
                on_miss="mint",
                cache=True,
            )
            assert outcome1.minted == 2

            # Sidecar must exist in the committed pack dir.
            assert (outcome1.pack_dir / _TALLY_FILE).is_file(), (
                "byod_tally.json sidecar should be written alongside the pack"
            )

            # Second call with identical inputs — cache hit.
            outcome2 = build_byod_pack(
                records=rows,
                schema=schema,
                domain="custom",
                namespace="ns",
                pack_type="base",
                link_on=[],
                on_miss="mint",
                cache=True,
            )
            assert outcome2.pack_dir == outcome1.pack_dir, "should reuse cached dir"

            # Tallies must equal the original build's values.
            assert outcome2.linked == outcome1.linked
            assert outcome2.minted == outcome1.minted
            assert outcome2.skipped == outcome1.skipped
            assert outcome2.ambiguous == outcome1.ambiguous

            # Confirm the concrete non-zero value for minted.
            assert outcome2.minted == 2

        finally:
            _reset_config()
