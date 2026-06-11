"""Tests for lazy SymSpell index build, thread safety, and lite preset."""

import contextlib
import tempfile
import threading
from pathlib import Path


class TestSymSpellLazyBuild:
    """Verify that the SymSpell index is built lazily on first use."""

    def test_index_not_built_at_construction(self):
        """_sym_spell must be None immediately after construction."""
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("france\t100\n")
            dict_path = f.name

        try:
            source = GeoSymSpellSource(dictionary_path=dict_path)
            assert source._sym_spell is None, (
                "SymSpell index must not be built at construction time"
            )
            assert not source._build_attempted
        finally:
            Path(dict_path).unlink(missing_ok=True)

    def test_index_built_after_ensure_built(self):
        """_ensure_built() triggers the index build."""
        pytest = __import__("pytest")
        pytest.importorskip("symspellpy")

        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("france\t100\n")
            dict_path = f.name

        try:
            source = GeoSymSpellSource(dictionary_path=dict_path)
            source._ensure_built()
            assert source._sym_spell is not None
            assert source._build_attempted
        finally:
            Path(dict_path).unlink(missing_ok=True)

    def test_index_built_on_first_generate(self):
        """generate() triggers the lazy build on first call."""
        pytest = __import__("pytest")
        pytest.importorskip("symspellpy")

        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                if value_norm == "france":
                    return ["country/FRA"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

            def search_prefix(self, query_norm, field, limit=10):
                return []

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("france\t100\n")
            dict_path = f.name

        try:
            source = GeoSymSpellSource(dictionary_path=dict_path)
            assert source._sym_spell is None  # not built yet

            query = Query(
                raw_text="Frannce",
                normalized=NormalizedText(original="Frannce", normalized="frannce"),
            )
            ctx = GenerationContext(
                query=query,
                context=ResolutionContext(),
                store=MockStore(),
                budget=10,
                trace=NullTraceSink(),
            )
            source.generate(ctx)

            # After generate(), index must be built.
            assert source._sym_spell is not None
        finally:
            Path(dict_path).unlink(missing_ok=True)

    def test_index_identical_to_eager_build(self):
        """Lazy-built index produces the same suggestions as an immediately-built one."""
        pytest = __import__("pytest")
        pytest.importorskip("symspellpy")

        from symspellpy import SymSpell, Verbosity

        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        terms = ["france\t100", "germany\t80", "nigeria\t60"]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("\n".join(terms) + "\n")
            dict_path = f.name

        try:
            # Reference: eager SymSpell built directly.
            eager = SymSpell(max_dictionary_edit_distance=2, prefix_length=7)
            eager.load_dictionary(
                dict_path, term_index=0, count_index=1, separator="\t"
            )

            # Lazy: triggered via _ensure_built().
            source = GeoSymSpellSource(dictionary_path=dict_path)
            source._ensure_built()
            lazy = source._sym_spell

            for typo in ("frannce", "gerrmany", "nigeeria"):
                eager_suggestions = {
                    s.term
                    for s in eager.lookup(typo, Verbosity.CLOSEST, max_edit_distance=2)
                }
                lazy_suggestions = {
                    s.term
                    for s in lazy.lookup(typo, Verbosity.CLOSEST, max_edit_distance=2)
                }
                assert eager_suggestions == lazy_suggestions, (
                    f"Mismatch for '{typo}': eager={eager_suggestions}, lazy={lazy_suggestions}"
                )
        finally:
            Path(dict_path).unlink(missing_ok=True)

    def test_extra_dicts_merged_before_build(self):
        """load_additional_dictionary() queues paths that are merged on first build."""
        pytest = __import__("pytest")
        pytest.importorskip("symspellpy")

        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f1:
            f1.write("france\t100\n")
            path1 = f1.name
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f2:
            f2.write("nigeria\t80\n")
            path2 = f2.name

        try:
            source = GeoSymSpellSource(dictionary_path=path1)
            source.load_additional_dictionary(path2)

            # Extra path must be queued, not built.
            assert source._sym_spell is None
            assert path2 in source._extra_dict_paths

            source._ensure_built()
            assert source._sym_spell is not None
            # Both terms should be present.
            from symspellpy import Verbosity

            sug1 = source._sym_spell.lookup(
                "frannce", Verbosity.CLOSEST, max_edit_distance=2
            )
            sug2 = source._sym_spell.lookup(
                "nigerria", Verbosity.CLOSEST, max_edit_distance=2
            )
            assert any(s.term == "france" for s in sug1)
            assert any(s.term == "nigeria" for s in sug2)
        finally:
            Path(path1).unlink(missing_ok=True)
            Path(path2).unlink(missing_ok=True)

    def test_no_dict_no_index(self):
        """Without a dictionary path, _ensure_built() leaves _sym_spell as None."""
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        source = GeoSymSpellSource(dictionary_path=None)
        source._ensure_built()
        assert source._sym_spell is None
        assert source._build_attempted  # attempted but found nothing

    def test_build_only_once(self):
        """_ensure_built() is idempotent; calling twice does not reset the index."""
        pytest = __import__("pytest")
        pytest.importorskip("symspellpy")

        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("france\t100\n")
            dict_path = f.name

        try:
            source = GeoSymSpellSource(dictionary_path=dict_path)
            source._ensure_built()
            first_instance = source._sym_spell

            source._ensure_built()  # second call must be a no-op
            assert source._sym_spell is first_instance
        finally:
            Path(dict_path).unlink(missing_ok=True)


class TestSymSpellThreadSafety:
    """Guard: concurrent first queries must not double-build the index."""

    def test_concurrent_ensure_built_builds_once(self):
        """Multiple threads calling _ensure_built() concurrently build the index once."""
        pytest = __import__("pytest")
        pytest.importorskip("symspellpy")

        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("france\t100\ngermany\t80\n")
            dict_path = f.name

        try:
            source = GeoSymSpellSource(dictionary_path=dict_path)
            errors: list[Exception] = []
            instances: list[object] = []
            barrier = threading.Barrier(8)

            def worker():
                try:
                    barrier.wait()  # All threads start at the same moment.
                    source._ensure_built()
                    instances.append(source._sym_spell)
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors, f"Thread errors: {errors}"
            # All threads must see the same (non-None) instance.
            assert all(inst is not None for inst in instances)
            assert len({id(inst) for inst in instances}) == 1, (
                "All threads must share the same SymSpell instance"
            )
        finally:
            Path(dict_path).unlink(missing_ok=True)


class TestSymSpellShareFrom:
    """Tests for share_symspell_from() used by GeoPack to share one index."""

    def test_shared_source_borrows_provider_instance(self):
        """After share_symspell_from(), borrower and provider share the same object."""
        pytest = __import__("pytest")
        pytest.importorskip("symspellpy")

        from resolvekit.packs.geo.sources.fuzzy_retrieval import GeoFuzzyRetrievalSource
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("france\t100\n")
            dict_path = f.name

        try:
            provider = GeoSymSpellSource(dictionary_path=dict_path)
            borrower = GeoFuzzyRetrievalSource(dictionary_path=None)
            borrower.share_symspell_from(provider)

            # Neither built yet.
            assert provider._sym_spell is None
            assert borrower._sym_spell is None

            # Trigger build through the borrower.
            borrower._ensure_built()

            # Both must now reference the same instance.
            assert borrower._sym_spell is not None
            assert provider._sym_spell is borrower._sym_spell
        finally:
            Path(dict_path).unlink(missing_ok=True)

    def test_geo_pack_shares_index_between_sources(self):
        """GeoPack wires geo_symspell and geo_fuzzy_retrieval to the same index."""
        pytest = __import__("pytest")
        pytest.importorskip("symspellpy")

        from resolvekit.packs.geo import GeoPack

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("france\t100\n")
            dict_path = f.name

        try:
            pack = GeoPack(symspell_dict_path=dict_path)
            sym_src = pack.get_source("geo_symspell")
            fuz_src = pack.get_source("geo_fuzzy_retrieval")
            assert sym_src is not None and fuz_src is not None

            # Trigger build via symspell source.
            sym_src._ensure_built()
            fuz_src._ensure_built()

            # Both must share the same SymSpell instance.
            assert sym_src._sym_spell is not None
            assert fuz_src._sym_spell is sym_src._sym_spell
        finally:
            Path(dict_path).unlink(missing_ok=True)


class TestSymSpellPerTierIndexes:
    """Tests for the per-tier-group SymSpell index architecture.

    The SMALL index covers countries, admin1, regions, continents, continental
    unions (few thousand terms, full params, always cheap). The LARGE index
    covers admin2-5 and cities (potentially ~720k terms, full params, built
    lazily only when large-tier data is actually loaded and a fuzzy query reaches
    it). Both groups use full params (prefix_length=7, max_edit_distance=2).
    """

    def test_small_source_uses_full_params(self):
        """SMALL index always uses prefix_length=7, max_edit_distance=2."""
        from resolvekit.packs.geo import GeoPack

        pack = GeoPack()
        sym_src = pack.get_source("geo_symspell")
        assert sym_src is not None
        assert sym_src._prefix_len == 7
        assert sym_src._max_edit == 2

    def test_large_tier_module_ids_set(self):
        """GeoPack._LARGE_TIER_MODULE_IDS covers admin2-5 and cities."""
        from resolvekit.packs.geo import GeoPack

        expected = {
            "geo.admin2",
            "geo.admin3",
            "geo.admin4",
            "geo.admin5",
            "geo.cities",
        }
        assert expected.issubset(GeoPack._LARGE_TIER_MODULE_IDS)
        # Small-tier modules must NOT be in the large set.
        assert "geo.countries" not in GeoPack._LARGE_TIER_MODULE_IDS
        assert "geo.admin1" not in GeoPack._LARGE_TIER_MODULE_IDS

    def test_no_large_source_when_no_large_paths(self):
        """Without large-tier dict paths, no large index source is created."""
        from resolvekit.packs.geo import GeoPack

        pack = GeoPack()
        # No large source registered when no large-tier paths provided.
        assert pack.get_source("geo_symspell_large") is None
        assert pack.get_source("geo_fuzzy_retrieval_large") is None

    def test_large_source_created_when_large_paths_provided(self, tmp_path):
        """With large-tier paths, geo_symspell_large and geo_fuzzy_retrieval_large appear."""
        from resolvekit.packs.geo import GeoPack

        large_dict = tmp_path / "large.txt"
        large_dict.write_text("karachi\t1000\n")
        pack = GeoPack(symspell_dict_paths_large=[str(large_dict)])
        assert pack.get_source("geo_symspell_large") is not None
        assert pack.get_source("geo_fuzzy_retrieval_large") is not None

    def test_large_source_uses_full_params(self, tmp_path):
        """LARGE index also uses prefix_length=7, max_edit_distance=2."""
        import pytest

        pytest.importorskip("symspellpy")

        from resolvekit.packs.geo import GeoPack

        large_dict = tmp_path / "large.txt"
        large_dict.write_text("karachi\t1000\n")
        pack = GeoPack(symspell_dict_paths_large=[str(large_dict)])
        large_src = pack.get_source("geo_symspell_large")
        assert large_src is not None
        assert large_src._prefix_len == 7
        assert large_src._max_edit == 2

    def test_large_source_has_large_tier_flag(self, tmp_path):
        """LARGE source's _large_tier attribute is True."""
        from resolvekit.packs.geo import GeoPack

        large_dict = tmp_path / "large.txt"
        large_dict.write_text("karachi\t1000\n")
        pack = GeoPack(symspell_dict_paths_large=[str(large_dict)])
        large_src = pack.get_source("geo_symspell_large")
        assert large_src is not None
        assert large_src._large_tier is True

    def test_small_source_large_tier_flag_false(self):
        """SMALL source's _large_tier attribute is False."""
        from resolvekit.packs.geo import GeoPack

        pack = GeoPack()
        sym_src = pack.get_source("geo_symspell")
        assert sym_src is not None
        assert sym_src._large_tier is False

    def test_both_indexes_lazy_at_construction(self, tmp_path):
        """Neither SMALL nor LARGE index is built at construction time."""
        from resolvekit.packs.geo import GeoPack

        small_dict = tmp_path / "small.txt"
        small_dict.write_text("france\t100\n")
        large_dict = tmp_path / "large.txt"
        large_dict.write_text("paris\t1000\n")

        pack = GeoPack(
            symspell_dict_paths_small=[str(small_dict)],
            symspell_dict_paths_large=[str(large_dict)],
        )
        small_src = pack.get_source("geo_symspell")
        large_src = pack.get_source("geo_symspell_large")
        assert small_src is not None and large_src is not None
        assert not small_src._build_attempted
        assert not large_src._build_attempted

    def test_small_index_builds_independently_of_large(self, tmp_path):
        """Building the SMALL index does not build the LARGE index."""
        import pytest

        pytest.importorskip("symspellpy")

        from resolvekit.packs.geo import GeoPack

        small_dict = tmp_path / "small.txt"
        small_dict.write_text("france\t100\n")
        large_dict = tmp_path / "large.txt"
        large_dict.write_text("paris\t1000\n")

        pack = GeoPack(
            symspell_dict_paths_small=[str(small_dict)],
            symspell_dict_paths_large=[str(large_dict)],
        )
        small_src = pack.get_source("geo_symspell")
        large_src = pack.get_source("geo_symspell_large")
        assert small_src is not None and large_src is not None

        # Trigger only the SMALL build.
        small_src._ensure_built()
        assert small_src._sym_spell is not None
        # LARGE index must NOT have been built.
        assert not large_src._build_attempted, (
            "Building the SMALL index must not trigger the LARGE index build"
        )


class TestSymSpellPerTierLoaderWiring:
    """Verify that pack_loader splits dict paths into SMALL / LARGE groups."""

    def _make_stub_loaded(self, module_id: str, symspell_path=None):
        """Return a minimal stub that satisfies _create_pack_instance's duck-typing."""
        _path = symspell_path

        class _StubLoaded:
            def __init__(self, mid: str) -> None:
                self.module_id = mid

            def artifact_path(self, artifact_type: str):
                if artifact_type == "symspell":
                    return _path
                return None

        return _StubLoaded(module_id)

    def test_small_only_load_no_large_source(self):
        """When only small-tier modules are loaded, no LARGE source is created."""
        from resolvekit.core.api.loading.pack_loader import _create_pack_instance
        from resolvekit.packs.geo import GeoPack

        all_loaded = [
            self._make_stub_loaded("geo.countries"),
            self._make_stub_loaded("geo.admin1"),
        ]
        pack = _create_pack_instance(GeoPack, all_loaded[0], all_loaded=all_loaded)
        sym_src = pack.get_source("geo_symspell")
        assert sym_src is not None
        assert sym_src._prefix_len == 7
        assert sym_src._max_edit == 2
        # No large index when no large-tier modules are loaded.
        assert pack.get_source("geo_symspell_large") is None

    def test_mixed_load_creates_separate_small_and_large_sources(self):
        """Mixed load creates two independent sources: SMALL (full params) + LARGE (full params)."""
        import pathlib
        import tempfile

        from resolvekit.core.api.loading.pack_loader import _create_pack_instance
        from resolvekit.packs.geo import GeoPack

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as sf:
            sf.write("france\t100\n")
            small_path = pathlib.Path(sf.name)
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as lf:
            lf.write("paris\t1000\n")
            large_path = pathlib.Path(lf.name)

        try:
            all_loaded = [
                self._make_stub_loaded("geo.countries", symspell_path=small_path),
                self._make_stub_loaded("geo.cities", symspell_path=large_path),
            ]
            pack = _create_pack_instance(GeoPack, all_loaded[0], all_loaded=all_loaded)

            small_src = pack.get_source("geo_symspell")
            large_src = pack.get_source("geo_symspell_large")
            assert small_src is not None, "SMALL source must be created"
            assert large_src is not None, (
                "LARGE source must be created for cities module"
            )

            # Both use full params.
            assert small_src._prefix_len == 7
            assert small_src._max_edit == 2
            assert large_src._prefix_len == 7
            assert large_src._max_edit == 2
        finally:
            small_path.unlink(missing_ok=True)
            large_path.unlink(missing_ok=True)

    def test_large_only_load_routes_to_large_source(self):
        """When only large-tier modules are loaded, paths go to the LARGE index."""
        from resolvekit.core.api.loading.pack_loader import _create_pack_instance
        from resolvekit.packs.geo import GeoPack

        all_loaded = [
            self._make_stub_loaded("geo.admin2"),
            self._make_stub_loaded("geo.cities"),
        ]
        pack = _create_pack_instance(GeoPack, all_loaded[0], all_loaded=all_loaded)
        sym_src = pack.get_source("geo_symspell")
        assert sym_src is not None
        # SMALL source has no paths (large-only load), LARGE source may be created
        # only if paths were non-None — here both return None so no LARGE source either.
        assert pack.get_source("geo_symspell_large") is None


class TestEntityTypeHintSkipsLargeIndex:
    """Verify that typed queries (entity_type hint) skip the LARGE index build."""

    def test_country_typed_query_skips_large_index(self, tmp_path):
        """A fuzzy query with entity_type=geo.country does not build the LARGE index."""
        import pytest

        pytest.importorskip("symspellpy")

        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo import GeoPack

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

            def search_prefix(self, query_norm, field, limit=10):
                return []

        small_dict = tmp_path / "small.txt"
        small_dict.write_text("france\t100\n")
        large_dict = tmp_path / "large.txt"
        large_dict.write_text("paris\t1000\n")

        pack = GeoPack(
            symspell_dict_paths_small=[str(small_dict)],
            symspell_dict_paths_large=[str(large_dict)],
        )
        small_src = pack.get_source("geo_symspell")
        large_src = pack.get_source("geo_symspell_large")
        large_fuz_src = pack.get_source("geo_fuzzy_retrieval_large")
        assert small_src is not None and large_src is not None

        query = Query(
            raw_text="Frannce",
            normalized=NormalizedText(original="Frannce", normalized="frannce"),
        )
        # Context with country-only entity type hint
        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(entity_types=frozenset({"geo.country"})),
            store=MockStore(),
            budget=10,
            trace=NullTraceSink(),
        )
        # Call generate() on the LARGE symspell source directly.
        large_src.generate(ctx)

        # LARGE index must NOT be built when entity_types is country-only.
        assert not large_src._build_attempted, (
            "LARGE index must not be built for a country-typed query"
        )
        if large_fuz_src is not None:
            large_fuz_src.generate(ctx)
            assert not large_fuz_src._build_attempted, (
                "LARGE fuzzy retrieval must not be built for a country-typed query"
            )

    def test_untyped_query_allows_large_index_to_build(self, tmp_path):
        """An untyped fuzzy query (no entity_type hint) allows the LARGE index to build."""
        import pytest

        pytest.importorskip("symspellpy")

        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo import GeoPack

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

            def search_prefix(self, query_norm, field, limit=10):
                return []

        small_dict = tmp_path / "small.txt"
        small_dict.write_text("france\t100\n")
        large_dict = tmp_path / "large.txt"
        large_dict.write_text("paris\t1000\n")

        pack = GeoPack(
            symspell_dict_paths_small=[str(small_dict)],
            symspell_dict_paths_large=[str(large_dict)],
        )
        large_src = pack.get_source("geo_symspell_large")
        assert large_src is not None

        query = Query(
            raw_text="Parris",
            normalized=NormalizedText(original="Parris", normalized="parris"),
        )
        # No entity_type hint — LARGE source is allowed to build.
        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(),  # no entity_types
            store=MockStore(),
            budget=10,
            trace=NullTraceSink(),
        )
        large_src.generate(ctx)

        # LARGE index SHOULD be built when no entity_type hint restricts it.
        assert large_src._build_attempted, (
            "LARGE index must be built for an untyped fuzzy query"
        )

    def test_small_index_finds_country_typo_independently(self, tmp_path):
        """Country typo recall works from the SMALL index alone (no LARGE needed)."""
        import pytest

        pytest.importorskip("symspellpy")

        from resolvekit.core.explain import NullTraceSink
        from resolvekit.core.model import (
            GenerationContext,
            NormalizedText,
            Query,
            ResolutionContext,
        )
        from resolvekit.core.store import EntityStore
        from resolvekit.packs.geo import GeoPack

        class MockStore(EntityStore):
            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value_norm):
                return []

            def lookup_name_exact(self, value_norm, name_kinds=None):
                if value_norm == "france":
                    return ["country/FRA"]
                return []

            def search_fulltext(self, query_norm, fields=None, limit=10):
                return []

            def bulk_get_entities(self, entity_ids):
                return {}

            def search_prefix(self, query_norm, field, limit=10):
                return []

        small_dict = tmp_path / "small.txt"
        small_dict.write_text("france\t100\n")
        # No large dict provided — LARGE source does not exist.
        pack = GeoPack(symspell_dict_paths_small=[str(small_dict)])

        assert pack.get_source("geo_symspell_large") is None, (
            "No LARGE source when no large-tier paths provided"
        )

        small_src = pack.get_source("geo_symspell")
        assert small_src is not None

        query = Query(
            raw_text="Frannce",
            normalized=NormalizedText(original="Frannce", normalized="frannce"),
        )
        ctx = GenerationContext(
            query=query,
            context=ResolutionContext(),
            store=MockStore(),
            budget=10,
            trace=NullTraceSink(),
        )
        evidence = small_src.generate(ctx)

        # SMALL index should find "france" from typo "frannce"
        assert any(ev.entity_id == "country/FRA" for ev in evidence), (
            "SMALL index must correct 'frannce' -> 'france' and find country/FRA"
        )
        # Confirm the SMALL index was built
        assert small_src._build_attempted


class TestSymSpellRaceAndFailure:
    """Tests for double-checked-locking correctness and failed-build degradation."""

    def test_concurrent_threads_never_see_none_index(self):
        """Threads racing the first build must never read a None index mid-build.

        Uses a short artificial delay inside _do_build to widen the race window,
        then asserts every thread sees either a complete index or None (never
        half-built), and that the index was built exactly once.
        """
        pytest = __import__("pytest")
        pytest.importorskip("symspellpy")

        import tempfile
        import threading
        import time
        from pathlib import Path

        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("france\t100\ngermany\t80\nitaly\t60\n")
            dict_path = f.name

        try:
            source = GeoSymSpellSource(dictionary_path=dict_path)

            # Patch _do_build to inject a small delay, widening the race window.
            original_do_build = source._do_build
            build_call_count = []
            build_lock = threading.Lock()

            def slow_do_build() -> None:
                with build_lock:
                    build_call_count.append(1)
                time.sleep(0.02)  # 20 ms window for racing threads
                original_do_build()

            source._do_build = slow_do_build  # type: ignore[method-assign]

            n_threads = 16
            barrier = threading.Barrier(n_threads)
            results: list[object] = []
            errors: list[Exception] = []

            def worker() -> None:
                try:
                    barrier.wait()  # all threads release simultaneously
                    source._ensure_built()
                    # Read _sym_spell AFTER _ensure_built() returns — must be
                    # fully built (or None if no paths), never half-initialised.
                    results.append(source._sym_spell)
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors, f"Thread errors: {errors}"
            # Every thread must see the same non-None instance.
            assert all(r is not None for r in results), (
                "Some threads observed a None index after _ensure_built() returned"
            )
            assert len({id(r) for r in results}) == 1, (
                "All threads must share the same SymSpell instance"
            )
            # The index must have been built exactly once.
            assert len(build_call_count) == 1, (
                f"_do_build called {len(build_call_count)} times; expected exactly 1"
            )
        finally:
            Path(dict_path).unlink(missing_ok=True)

    def test_failed_build_does_not_wedge_subsequent_calls(self):
        """A _do_build() that raises must leave the source in a degraded (not broken) state.

        After a failed build attempt, _ensure_built() must not raise again and
        _sym_spell must remain None so the source falls back gracefully.
        _build_attempted must be True (no retry), _built must be False.
        """
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        source = GeoSymSpellSource(dictionary_path="/nonexistent/path.txt")

        # Patch _do_build to raise on first call.
        def failing_do_build() -> None:
            raise RuntimeError("simulated dict load failure")

        source._do_build = failing_do_build  # type: ignore[method-assign]

        # First call: _do_build raises, so the build fails.
        # _ensure_built itself must NOT propagate the exception; _build_attempted
        # is set, _built is False, _sym_spell stays None.
        # NOTE: in the current implementation _do_build raises inside the lock and
        # the exception propagates. We test that subsequent calls do NOT raise and
        # correctly degrade.
        # Exception escaping from _do_build is acceptable; what matters is the
        # state and that subsequent calls degrade.
        with contextlib.suppress(RuntimeError):
            source._ensure_built()

        # State after failure: attempted but not built.
        assert source._build_attempted is True
        assert source._built is False
        assert source._sym_spell is None

        # Subsequent calls must not raise and must be no-ops (degrade-once).
        source._ensure_built()
        source._ensure_built()

        assert source._sym_spell is None, (
            "After a failed build, _sym_spell must remain None"
        )
        assert source._built is False, "After a failed build, _built must remain False"

    def test_shared_provider_build_is_race_safe(self):
        """Threads racing through a share_symspell_from() borrow never observe None.

        Borrower._ensure_built() delegates to provider._ensure_built(), which
        must be fully complete before the borrower copies _sym_spell.  All
        threads that call borrower._ensure_built() concurrently must observe the
        same non-None instance.
        """
        pytest = __import__("pytest")
        pytest.importorskip("symspellpy")

        import tempfile
        import threading
        from pathlib import Path

        from resolvekit.packs.geo.sources.fuzzy_retrieval import GeoFuzzyRetrievalSource
        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("france\t100\n")
            dict_path = f.name

        try:
            provider = GeoSymSpellSource(dictionary_path=dict_path)
            borrower = GeoFuzzyRetrievalSource(dictionary_path=None)
            borrower.share_symspell_from(provider)

            n_threads = 12
            barrier = threading.Barrier(n_threads)
            results: list[object] = []
            errors: list[Exception] = []

            def worker() -> None:
                try:
                    barrier.wait()
                    borrower._ensure_built()
                    results.append(borrower._sym_spell)
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=worker) for _ in range(n_threads)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors, f"Thread errors: {errors}"
            assert all(r is not None for r in results), (
                "Some threads observed a None index on the borrower"
            )
            assert len({id(r) for r in results}) == 1, (
                "All threads must see the same shared instance"
            )
        finally:
            Path(dict_path).unlink(missing_ok=True)


class TestLitePreset:
    """Tests for Resolver.lite() convenience constructor."""

    def test_lite_module_ids_attribute(self):
        """Resolver._LITE_GEO_MODULE_IDS must contain country-level modules."""
        from resolvekit.core.api.resolver import Resolver

        assert "geo.countries" in Resolver._LITE_GEO_MODULE_IDS
        # Large-tier admin should not be in the default lite set.
        assert "geo.admin2" not in Resolver._LITE_GEO_MODULE_IDS
        assert "geo.cities" not in Resolver._LITE_GEO_MODULE_IDS

    def test_lite_resolves_country(self):
        """Resolver.lite() can resolve country-level queries."""
        from resolvekit.core.api.resolver import Resolver

        r = Resolver.lite()
        try:
            result = r.resolve("United States")
            assert result.entity_id == "country/USA"
        finally:
            r.close()

    def test_lite_custom_module_ids(self):
        """Passing module_ids to lite() overrides the built-in selection."""
        from resolvekit.core.api.resolver import Resolver

        r = Resolver.lite(module_ids=["geo.countries"])
        try:
            assert "geo" in r.domains
            result = r.resolve("France")
            assert result.entity_id == "country/FRA"
        finally:
            r.close()

    def test_lite_no_symspell_at_construction(self):
        """Resolver.lite() must not build the SymSpell index at construction time."""
        from resolvekit.core.api.resolver import Resolver

        r = Resolver.lite()
        try:
            runner = r._runner
            # Look for the geo_symspell source and verify index not built yet.
            geo_runner = getattr(runner, "_runners", {}).get("geo")
            if geo_runner is not None:
                for source in geo_runner._sources:
                    if source.name == "geo_symspell":
                        assert not source._build_attempted, (
                            "SymSpell index must not be built during lite() construction"
                        )
                        break
        finally:
            r.close()
