"""Tests for the compiled-index (pickle) cache in SymSpellSource.

All tests use small synthetic tab-separated dict files in tmp_path — never real data.
The cache dir is redirected via monkeypatching so tests are fully isolated.
"""

import os

import pytest

symspellpy = pytest.importorskip("symspellpy")


def _make_dict(path, terms):
    """Write a tab-separated symspell dictionary to *path*."""
    path.write_text("".join(f"{term}\t{count}\n" for term, count in terms))


def _patch_cache_dir(monkeypatch, tmp_path):
    """Redirect get_cache_dir as imported by symspell_base to tmp_path/cache."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(
        "resolvekit.shared.sources.symspell_base.get_cache_dir",
        lambda: cache_dir,
    )
    return cache_dir


def _make_source(dict_path, name="test_ss", use_compiled_cache=True):
    from resolvekit.shared.sources.symspell_base import SymSpellSource

    return SymSpellSource(
        name=name,
        domain="x",
        dictionary_path=str(dict_path),
        use_compiled_cache=use_compiled_cache,
    )


class TestCompiledCacheCreate:
    def test_build_creates_exactly_one_pkl_file(self, tmp_path, monkeypatch):
        """Warming a source with use_compiled_cache=True creates one .pkl file."""
        cache_dir = _patch_cache_dir(monkeypatch, tmp_path)
        d = tmp_path / "dict.txt"
        _make_dict(d, [("france", 100), ("germany", 80)])

        source = _make_source(d)
        source.warm()

        compiled_dir = cache_dir / "compiled"
        pkls = list(compiled_dir.glob("symspell-test_ss-*.pkl"))
        assert len(pkls) == 1, f"Expected 1 .pkl file, found: {pkls}"

    def test_no_pkl_when_cache_disabled(self, tmp_path, monkeypatch):
        """use_compiled_cache=False (default) must not create any artifacts."""
        cache_dir = _patch_cache_dir(monkeypatch, tmp_path)
        d = tmp_path / "dict.txt"
        _make_dict(d, [("france", 100)])

        source = _make_source(d, use_compiled_cache=False)
        source.warm()

        compiled_dir = cache_dir / "compiled"
        assert not compiled_dir.exists() or not list(
            compiled_dir.glob("symspell-test_ss-*.pkl")
        ), "No .pkl files should be created when use_compiled_cache=False"


class TestCompiledCacheLoad:
    def test_second_instance_loads_from_cache_not_text(self, tmp_path, monkeypatch):
        """A fresh instance with identical paths loads from the pickle, not text."""
        _patch_cache_dir(monkeypatch, tmp_path)
        d = tmp_path / "dict.txt"
        _make_dict(d, [("france", 100), ("germany", 80)])

        # Warm first instance to populate the cache.
        source1 = _make_source(d)
        source1.warm()

        # Now patch _load_dictionary_from_path to raise — it must NOT be called.
        monkeypatch.setattr(
            "resolvekit.shared.sources.symspell_base.SymSpellSource._load_dictionary_from_path",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                AssertionError("text load was invoked; should have loaded from cache")
            ),
        )

        source2 = _make_source(d)
        source2.warm()  # Must come from cache

        # Verify it actually works: lookup a corrected term.
        from symspellpy import Verbosity

        suggestions = source2._sym_spell.lookup(
            "frannce", Verbosity.CLOSEST, max_edit_distance=2
        )
        terms = {s.term for s in suggestions}
        assert "france" in terms, f"Expected 'france' in suggestions, got: {terms}"

    def test_cache_hit_same_lookup_results(self, tmp_path, monkeypatch):
        """A cache-loaded index produces the same lookup results as a text-built one."""
        _patch_cache_dir(monkeypatch, tmp_path)
        d = tmp_path / "dict.txt"
        _make_dict(d, [("france", 100), ("nigeria", 60)])

        from symspellpy import Verbosity

        # Text-built reference.
        source_text = _make_source(d, name="ref_ss", use_compiled_cache=False)
        source_text.warm()

        # Cached build (first build).
        source_cached1 = _make_source(d, name="cache_ss")
        source_cached1.warm()

        # Cache-loaded instance (second build with same params).
        source_cached2 = _make_source(d, name="cache_ss")
        source_cached2.warm()

        for typo in ("frannce", "nigerria"):
            ref = {
                s.term
                for s in source_text._sym_spell.lookup(
                    typo, Verbosity.CLOSEST, max_edit_distance=2
                )
            }
            cached = {
                s.term
                for s in source_cached2._sym_spell.lookup(
                    typo, Verbosity.CLOSEST, max_edit_distance=2
                )
            }
            assert ref == cached, (
                f"Lookup mismatch for '{typo}': text={ref}, cached={cached}"
            )


class TestCompiledCacheInvalidation:
    def test_modified_dict_triggers_rebuild_and_evicts_old(self, tmp_path, monkeypatch):
        """Modifying a dict file (size/mtime change) → new key, rebuild, old file removed."""
        cache_dir = _patch_cache_dir(monkeypatch, tmp_path)
        d = tmp_path / "dict.txt"
        _make_dict(d, [("france", 100)])

        # First build — creates cache entry.
        source1 = _make_source(d)
        source1.warm()
        compiled_dir = cache_dir / "compiled"
        pkls_before = list(compiled_dir.glob("symspell-test_ss-*.pkl"))
        assert len(pkls_before) == 1
        first_pkl = pkls_before[0]

        # Modify the dict file (content + mtime change).
        _make_dict(d, [("france", 100), ("germany", 80), ("italy", 60)])
        # Ensure mtime changes even if the filesystem has coarse resolution.
        new_mtime = d.stat().st_mtime + 2
        os.utime(d, (new_mtime, new_mtime))

        # Second build — must detect the change, rebuild, and evict the old pkl.
        source2 = _make_source(d)
        source2.warm()

        pkls_after = list(compiled_dir.glob("symspell-test_ss-*.pkl"))
        assert len(pkls_after) == 1, f"Expected 1 .pkl after rebuild, got: {pkls_after}"
        assert pkls_after[0] != first_pkl, "New cache file should have a different key"
        assert not first_pkl.exists(), "Old cache file must be evicted"


class TestCompiledCacheCorruptFile:
    def test_corrupt_cache_falls_back_to_text_build(self, tmp_path, monkeypatch):
        """A corrupt .pkl file → graceful fallback to text build, query still works."""
        cache_dir = _patch_cache_dir(monkeypatch, tmp_path)
        d = tmp_path / "dict.txt"
        _make_dict(d, [("france", 100)])

        # Warm once to create the cache file, then corrupt it.
        source1 = _make_source(d)
        source1.warm()
        compiled_dir = cache_dir / "compiled"
        pkl = next(compiled_dir.glob("symspell-test_ss-*.pkl"))
        pkl.write_bytes(b"not a valid pickle at all!!!")

        # A new instance must survive the corrupt file and fall back to text build.
        source2 = _make_source(d)
        source2.warm()  # Must not raise

        assert source2._sym_spell is not None, (
            "After corrupt-cache fallback, _sym_spell must be set"
        )
        from symspellpy import Verbosity

        suggestions = source2._sym_spell.lookup(
            "frannce", Verbosity.CLOSEST, max_edit_distance=2
        )
        assert any(s.term == "france" for s in suggestions)


class TestCompiledCacheSaveFailure:
    def test_cache_write_failure_does_not_raise(self, tmp_path, monkeypatch):
        """A failing os.replace (e.g. read-only dir) → build still succeeds, no exception."""
        _patch_cache_dir(monkeypatch, tmp_path)
        d = tmp_path / "dict.txt"
        _make_dict(d, [("france", 100)])

        def _failing_replace(src, dst):
            raise OSError("simulated read-only cache dir")

        monkeypatch.setattr(
            "resolvekit.shared.sources.symspell_base.os.replace", _failing_replace
        )

        source = _make_source(d)
        source.warm()  # Must not raise

        assert source._sym_spell is not None, (
            "Build must succeed even when cache write fails"
        )
        # No pkl file should exist (the temp file might linger but the target won't).
        cache_dir = tmp_path / "cache"
        compiled_dir = cache_dir / "compiled"
        pkls = (
            list(compiled_dir.glob("symspell-test_ss-*.pkl"))
            if compiled_dir.exists()
            else []
        )
        assert len(pkls) == 0, f"No .pkl should exist after a failed save: {pkls}"

    def test_non_oserror_save_failure_keeps_built_index(self, tmp_path, monkeypatch):
        """A non-OSError from save_pickle (e.g. PicklingError) must not escape.

        If it escaped _do_build(), _ensure_built() would mark the build failed
        and discard the successfully built in-memory index for the process.
        """
        import pickle

        _patch_cache_dir(monkeypatch, tmp_path)
        d = tmp_path / "dict.txt"
        _make_dict(d, [("france", 100)])

        def _failing_save(path, compressed=True):
            raise pickle.PicklingError("simulated unpicklable state")

        monkeypatch.setattr(
            symspellpy.SymSpell, "save_pickle", _failing_save, raising=True
        )

        source = _make_source(d)
        source.warm()  # Must not raise

        assert source._built is True, "Build must be marked successful"
        assert source._sym_spell is not None, (
            "In-memory index must survive a cache-save failure"
        )


class TestCompiledCacheTempEviction:
    def test_aged_temp_reaped_fresh_temp_kept(self, tmp_path, monkeypatch):
        """Eviction reaps leaked temp files past the age threshold only.

        A fresh temp file may belong to a concurrent writer mid-save and must
        survive; an hours-old one is a leak from a crashed writer.
        """
        import time as time_mod

        _patch_cache_dir(monkeypatch, tmp_path)
        d = tmp_path / "dict.txt"
        _make_dict(d, [("france", 100)])

        compiled_dir = tmp_path / "cache" / "compiled"
        compiled_dir.mkdir(parents=True)
        old_tmp = compiled_dir / "symspell-test_ss-deadbeef.tmp.999.aaaaaaaa"
        old_tmp.write_bytes(b"leaked")
        os.utime(old_tmp, (time_mod.time() - 7200, time_mod.time() - 7200))
        fresh_tmp = compiled_dir / "symspell-test_ss-deadbeef.tmp.999.bbbbbbbb"
        fresh_tmp.write_bytes(b"in-flight")

        source = _make_source(d)
        source.warm()  # save runs eviction

        assert not old_tmp.exists(), "Aged temp file must be reaped"
        assert fresh_tmp.exists(), "Fresh temp file must survive eviction"


class TestCompiledCacheIdempotent:
    def test_warm_is_idempotent(self, tmp_path, monkeypatch):
        """Calling warm() twice must not trigger a second build."""
        _patch_cache_dir(monkeypatch, tmp_path)
        d = tmp_path / "dict.txt"
        _make_dict(d, [("france", 100)])

        source = _make_source(d)
        source.warm()

        assert source._built is True
        first_instance = source._sym_spell

        # Track any invocation of _load_dictionary_from_path on the second call.
        load_calls: list[int] = []
        orig_load = source._load_dictionary_from_path

        def tracked_load(path):
            load_calls.append(1)
            return orig_load(path)

        source._load_dictionary_from_path = tracked_load  # type: ignore[method-assign]

        source.warm()  # Second call — must be a no-op.

        assert source._built is True
        assert source._sym_spell is first_instance, (
            "Second warm() must not rebuild the index"
        )
        assert len(load_calls) == 0, (
            "Text load must not be invoked on the second warm() call"
        )
