"""Tests for GeoPack."""

from resolvekit.core.model import GenerationContext, ReasonCode
from resolvekit.packs.geo import GeoPack
from resolvekit.packs.geo.sources.exact_code import GeoExactCodeSource
from tests.conftest import MockEntityStore, make_query


class TestGeoExactCodeSource:
    def test_source_properties(self):
        source = GeoExactCodeSource()
        assert source.name == "geo_exact_code"
        assert source.reason_code == ReasonCode.EXACT_CODE_MATCH
        assert source.supports("geo") is True
        assert source.supports("org") is False

    def test_source_generates_evidence_for_code(self, null_trace, empty_context):
        store = MockEntityStore(
            codes={
                ("iso2", "us"): ["country/USA"],
                ("iso3", "usa"): ["country/USA"],
            }
        )
        source = GeoExactCodeSource()
        query = make_query("US")

        ctx = GenerationContext(
            query=query,
            context=empty_context,
            store=store,
            budget=10,
            trace=null_trace,
        )
        evidence = source.generate(ctx)

        assert len(evidence) == 1
        assert evidence[0].entity_id == "country/USA"
        assert evidence[0].source_name == "geo_exact_code"
        assert evidence[0].matched_field == "code.iso2"
        assert evidence[0].raw_score == 1.0

    def test_source_generates_evidence_for_dcid(self, null_trace, empty_context):
        store = MockEntityStore(
            codes={("dcid", "country/usa"): ["country/USA"]}  # normalized key
        )
        source = GeoExactCodeSource()
        query = make_query("country/USA")

        ctx = GenerationContext(
            query=query,
            context=empty_context,
            store=store,
            budget=10,
            trace=null_trace,
        )
        evidence = source.generate(ctx)

        assert len(evidence) == 1
        assert evidence[0].entity_id == "country/USA"
        assert evidence[0].matched_field == "code.dcid"

    def test_source_generates_evidence_for_wikidata_qid(
        self, null_trace, empty_context
    ):
        store = MockEntityStore(codes={("wikidata", "q458"): ["country/EU"]})
        source = GeoExactCodeSource()
        query = make_query("wikidata:Q458", normalized="wikidata:q458")

        ctx = GenerationContext(
            query=query,
            context=empty_context,
            store=store,
            budget=10,
            trace=null_trace,
        )
        evidence = source.generate(ctx)

        assert len(evidence) == 1
        assert evidence[0].entity_id == "country/EU"
        assert evidence[0].matched_field == "code.wikidata"
        assert evidence[0].matched_value == "Q458"

    def test_source_falls_back_to_numeric_wikidata_lookup(
        self, null_trace, empty_context
    ):
        store = MockEntityStore(codes={("wikidata", "458"): ["country/EU"]})
        source = GeoExactCodeSource()
        query = make_query("Q458", normalized="q458")

        ctx = GenerationContext(
            query=query,
            context=empty_context,
            store=store,
            budget=10,
            trace=null_trace,
        )
        evidence = source.generate(ctx)

        assert len(evidence) == 1
        assert evidence[0].entity_id == "country/EU"
        assert evidence[0].matched_field == "code.wikidata"

    def test_source_falls_back_to_any_code_system(self, null_trace, empty_context):
        """Fallback fires when no prioritized system matches but lookup_code_any finds a hit."""
        store = MockEntityStore(
            codes={
                ("fips104", "uk"): ["country/GBR"],
            }
        )
        source = GeoExactCodeSource()
        query = make_query("UK")

        ctx = GenerationContext(
            query=query,
            context=empty_context,
            store=store,
            budget=10,
            trace=null_trace,
        )
        evidence = source.generate(ctx)

        assert len(evidence) == 1
        assert evidence[0].entity_id == "country/GBR"
        assert evidence[0].matched_field == "code.fips104"
        assert evidence[0].raw_score == 1.0

    def test_source_prefers_prioritized_system_over_fallback(
        self, null_trace, empty_context
    ):
        """Known systems take priority — fallback doesn't fire when iso2 matches."""
        store = MockEntityStore(
            codes={
                ("iso2", "us"): ["country/USA"],
                ("fips104", "us"): ["country/USA"],
            }
        )
        source = GeoExactCodeSource()
        query = make_query("US")

        ctx = GenerationContext(
            query=query,
            context=empty_context,
            store=store,
            budget=10,
            trace=null_trace,
        )
        evidence = source.generate(ctx)

        assert len(evidence) == 1
        assert evidence[0].matched_field == "code.iso2"

    def test_source_returns_empty_for_non_code(
        self, empty_store, null_trace, empty_context
    ):
        source = GeoExactCodeSource()
        query = make_query("United States", normalized="united states")

        ctx = GenerationContext(
            query=query,
            context=empty_context,
            store=empty_store,
            budget=10,
            trace=null_trace,
        )
        evidence = source.generate(ctx)

        assert len(evidence) == 0


class TestGeoPack:
    def test_pack_exists(self):
        pack = GeoPack()
        assert pack.pack_id == "geo"
        assert len(pack.sources) >= 1

    def test_symspell_dict_paths_plural_loads_all_dicts(self, tmp_path):
        """GeoPack with symspell_dict_paths loads terms from every dictionary."""
        import pytest

        pytest.importorskip("symspellpy")

        # Two separate dictionaries, each with a unique term
        dict1 = tmp_path / "dict1.txt"
        dict1.write_text("france\t100\n")
        dict2 = tmp_path / "dict2.txt"
        dict2.write_text("germany\t100\n")

        pack = GeoPack(symspell_dict_paths=[str(dict1), str(dict2)])
        symspell_source = pack.get_source("geo_symspell")
        assert symspell_source is not None

        # Trigger lazy build; both dicts merged into a single SymSpell instance.
        symspell_source._ensure_built()
        sym = symspell_source._sym_spell
        assert sym is not None, "SymSpell not initialised after _ensure_built()"

        from symspellpy import Verbosity  # type: ignore[import-untyped]

        suggestions_france = sym.lookup(
            "frannce", Verbosity.CLOSEST, max_edit_distance=2
        )
        suggestions_germany = sym.lookup(
            "gerrmany", Verbosity.CLOSEST, max_edit_distance=2
        )

        assert any(s.term == "france" for s in suggestions_france), (
            "Expected 'france' from dict1 to be correctable"
        )
        assert any(s.term == "germany" for s in suggestions_germany), (
            "Expected 'germany' from dict2 to be correctable"
        )

    def test_symspell_dict_paths_plural_also_loads_fuzzy_retrieval(self, tmp_path):
        """Both GeoSymSpellSource and GeoFuzzyRetrievalSource share the same index."""
        import pytest

        pytest.importorskip("symspellpy")

        dict1 = tmp_path / "d1.txt"
        dict1.write_text("spain\t50\n")
        dict2 = tmp_path / "d2.txt"
        dict2.write_text("portugal\t50\n")

        pack = GeoPack(symspell_dict_paths=[str(dict1), str(dict2)])
        fuzzy_retrieval = pack.get_source("geo_fuzzy_retrieval")
        assert fuzzy_retrieval is not None

        # Trigger lazy build via the symspell source, then fuzzy_retrieval borrows it.
        fuzzy_retrieval._ensure_built()
        sym = fuzzy_retrieval._sym_spell
        assert sym is not None

        from symspellpy import Verbosity  # type: ignore[import-untyped]

        suggestions = sym.lookup("portugall", Verbosity.CLOSEST, max_edit_distance=2)
        assert any(s.term == "portugal" for s in suggestions), (
            "Expected 'portugal' from dict2 to be present in fuzzy retrieval"
        )

    def test_legacy_scalar_symspell_dict_path_still_works(self, tmp_path):
        """Existing callers using symspell_dict_path= (singular) are unaffected."""
        import pytest

        pytest.importorskip("symspellpy")

        dict_path = tmp_path / "legacy.txt"
        dict_path.write_text("italy\t80\n")

        pack = GeoPack(symspell_dict_path=str(dict_path))
        symspell_source = pack.get_source("geo_symspell")
        assert symspell_source is not None
        # Index is lazy — trigger the build before inspecting _sym_spell.
        symspell_source._ensure_built()
        assert symspell_source._sym_spell is not None

        from symspellpy import Verbosity  # type: ignore[import-untyped]

        suggestions = symspell_source._sym_spell.lookup(
            "itally", Verbosity.CLOSEST, max_edit_distance=2
        )
        assert any(s.term == "italy" for s in suggestions)


class TestSymSpellLoadAdditionalDictionary:
    def test_merges_terms_from_second_dict(self, tmp_path):
        """Terms from a second dictionary are findable after merging."""
        import pytest

        pytest.importorskip("symspellpy")

        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        dict1 = tmp_path / "a.txt"
        dict1.write_text("nigeria\t100\n")
        dict2 = tmp_path / "b.txt"
        dict2.write_text("kenya\t100\n")

        source = GeoSymSpellSource(dictionary_path=str(dict1))
        source.load_additional_dictionary(str(dict2))

        # Trigger the lazy build so both dicts are merged.
        source._ensure_built()

        from symspellpy import Verbosity  # type: ignore[import-untyped]

        sym = source._sym_spell
        assert sym is not None

        suggestions = sym.lookup("keenya", Verbosity.CLOSEST, max_edit_distance=2)
        assert any(s.term == "kenya" for s in suggestions), (
            "Expected 'kenya' from the second dictionary to be reachable"
        )

    def test_no_op_for_missing_file(self, tmp_path):
        """load_additional_dictionary() silently ignores non-existent paths."""
        import pytest

        pytest.importorskip("symspellpy")

        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        dict1 = tmp_path / "real.txt"
        dict1.write_text("chad\t100\n")

        source = GeoSymSpellSource(dictionary_path=str(dict1))
        # Should not raise even when the extra path doesn't exist
        source.load_additional_dictionary(str(tmp_path / "does_not_exist.txt"))

        # Trigger lazy build; missing path is silently ignored.
        source._ensure_built()

        # Original dictionary still works
        from symspellpy import Verbosity  # type: ignore[import-untyped]

        suggestions = source._sym_spell.lookup(
            "chadd", Verbosity.CLOSEST, max_edit_distance=2
        )
        assert any(s.term == "chad" for s in suggestions)

    def test_bootstraps_from_additional_when_no_primary(self, tmp_path):
        """load_additional_dictionary() queues path; index built on first use."""
        import pytest

        pytest.importorskip("symspellpy")

        from resolvekit.packs.geo.sources.symspell import GeoSymSpellSource

        extra = tmp_path / "extra.txt"
        extra.write_text("senegal\t100\n")

        source = GeoSymSpellSource(dictionary_path=None)
        # Index not built yet (lazy).
        assert not source._build_attempted

        source.load_additional_dictionary(str(extra))
        # Still not built — path is queued.
        assert not source._build_attempted

        # Trigger the lazy build.
        source._ensure_built()
        assert source._sym_spell is not None

        from symspellpy import Verbosity  # type: ignore[import-untyped]

        suggestions = source._sym_spell.lookup(
            "senegall", Verbosity.CLOSEST, max_edit_distance=2
        )
        assert any(s.term == "senegal" for s in suggestions)
