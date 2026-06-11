"""Tests for Resolver facade."""

from pathlib import Path

import pytest

from resolvekit.core.api import Resolver
from resolvekit.core.datapack import NORMALIZER_VERSION, LoadedDataPack
from resolvekit.core.engine import CandidateSource, PipelineRunner
from resolvekit.core.engine.decision import ThresholdDecisionPolicy
from resolvekit.core.errors import (
    AmbiguousResolutionError,
    ResolutionError,
)
from resolvekit.core.explain import NullTraceSink
from resolvekit.core.model import (
    CandidateEvidence,
    EntityRecord,
    GenerationContext,
    MatchTier,
    ReasonCode,
    RefinementHint,
    RelationRecord,
    ResolutionStatus,
)
from resolvekit.core.util import TextNormalizer
from tests.conftest import MockEntityStore

# Default decision policy matching the threshold-and-gap criteria used in legacy code.
_DEFAULT_POLICY = ThresholdDecisionPolicy(
    confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
)


class MockCodeSource(CandidateSource):
    """Mock source that returns evidence when normalized text is 'us'."""

    @property
    def name(self) -> str:
        return "mock_exact_code"

    def supports(self, domain_pack_id: str) -> bool:
        return True

    def generate(self, ctx: GenerationContext):
        if ctx.text_norm == "us":
            return [
                CandidateEvidence(
                    entity_id="country/USA",
                    source_name=self.name,
                    raw_score=1.0,
                    rank=1,
                    matched_field="code.iso2",
                    matched_value="US",
                )
            ]
        return []


class MockAmbiguousSource(CandidateSource):
    """Mock source that returns two close candidates for ambiguity tests."""

    @property
    def name(self) -> str:
        return "mock_fts"

    def supports(self, domain_pack_id: str) -> bool:
        return True

    def generate(self, ctx: GenerationContext):
        if ctx.text_norm != "paris":
            return []
        return [
            CandidateEvidence(
                entity_id="city/Paris_FR",
                source_name=self.name,
                raw_score=0.80,
                rank=1,
                matched_field="fts",
                matched_value="Paris",
            ),
            CandidateEvidence(
                entity_id="city/Paris_TX",
                source_name=self.name,
                raw_score=0.75,
                rank=2,
                matched_field="fts",
                matched_value="Paris",
            ),
        ]


class MockLowConfidenceFTSSource(CandidateSource):
    """Mock source that returns a near-miss candidate below threshold."""

    @property
    def name(self) -> str:
        return "mock_fts"

    def supports(self, domain_pack_id: str) -> bool:
        return True

    def generate(self, ctx: GenerationContext):
        if ctx.text_norm != "springfeld":
            return []
        return [
            CandidateEvidence(
                entity_id="city/Springfield_US",
                source_name=self.name,
                raw_score=0.65,
                rank=1,
                matched_field="fts",
                matched_value="springfield",
            )
        ]


def test_resolver_normalizes_and_resolves():
    store = MockEntityStore(codes={("iso2", "us"): ["country/USA"]})

    runner = PipelineRunner(
        trace_sink=NullTraceSink(),
        store=store,
        sources=[MockCodeSource()],
        decision_policy=_DEFAULT_POLICY,
    )

    resolver = Resolver(runner=runner, normalizer=TextNormalizer())
    result = resolver.resolve("US")

    assert result.status == ResolutionStatus.RESOLVED
    assert result.pack_id is None
    assert result.match_tier == MatchTier.EXACT_CODE


def test_resolved_result_includes_pack_and_match_tier():
    store = MockEntityStore(
        entities={
            "country/USA": EntityRecord(
                entity_id="country/USA",
                entity_type="geo.country",
                canonical_name="United States",
                canonical_name_norm="united states",
            )
        },
        codes={("iso2", "us"): ["country/USA"]},
    )

    runner = PipelineRunner(
        trace_sink=NullTraceSink(),
        store=store,
        sources=[MockCodeSource()],
        pack_id="geo",
        decision_policy=_DEFAULT_POLICY,
    )

    resolver = Resolver(runner=runner, normalizer=TextNormalizer())
    result = resolver.resolve("US")

    assert result.status == ResolutionStatus.RESOLVED
    assert result.pack_id == "geo"
    assert result.match_tier == MatchTier.EXACT_CODE
    assert result.refinement_hints == []


def test_blank_query_returns_explicit_no_match():
    store = MockEntityStore(codes={("iso2", "us"): ["country/USA"]})

    runner = PipelineRunner(
        trace_sink=NullTraceSink(),
        store=store,
        sources=[MockCodeSource()],
        decision_policy=_DEFAULT_POLICY,
    )

    resolver = Resolver(runner=runner, normalizer=TextNormalizer())
    result = resolver.resolve("   ")

    assert result.status == ResolutionStatus.NO_MATCH
    assert result.reasons == [ReasonCode.INVALID_QUERY]


def test_blank_query_with_explanation_returns_scorecard():
    store = MockEntityStore(codes={("iso2", "us"): ["country/USA"]})

    runner = PipelineRunner(
        trace_sink=NullTraceSink(),
        store=store,
        sources=[MockCodeSource()],
        decision_policy=_DEFAULT_POLICY,
    )

    resolver = Resolver(runner=runner, normalizer=TextNormalizer())
    explained = resolver.resolve_explained("   ")
    result, scorecard = explained.result, explained.scorecard

    assert result.status == ResolutionStatus.NO_MATCH
    assert result.reasons == [ReasonCode.INVALID_QUERY]
    assert scorecard.status == ResolutionStatus.NO_MATCH
    assert scorecard.normalized_text == ""


def test_ambiguous_results_include_display_metadata():
    entities = {
        "city/Paris_FR": EntityRecord(
            entity_id="city/Paris_FR",
            entity_type="geo.city",
            canonical_name="Paris",
            canonical_name_norm="paris",
            relations=[
                RelationRecord(
                    relation_type="contained_in",
                    target_id="country/FRA",
                )
            ],
        ),
        "city/Paris_TX": EntityRecord(
            entity_id="city/Paris_TX",
            entity_type="geo.city",
            canonical_name="Paris, Texas",
            canonical_name_norm="paris texas",
            relations=[
                RelationRecord(
                    relation_type="contained_in",
                    target_id="country/USA",
                )
            ],
        ),
    }
    store = MockEntityStore(entities=entities)
    runner = PipelineRunner(
        trace_sink=NullTraceSink(),
        store=store,
        sources=[MockAmbiguousSource()],
        pack_id="geo",
        decision_policy=_DEFAULT_POLICY,
        type_prefixes=frozenset({"geo"}),
        country_relation_prefixes=frozenset({"country/"}),
    )

    resolver = Resolver(runner=runner, normalizer=TextNormalizer())
    result = resolver.resolve("Paris")

    assert result.status == ResolutionStatus.AMBIGUOUS
    assert result.pack_id == "geo"
    assert result.match_tier == MatchTier.FTS
    assert result.candidates[0].canonical_name == "Paris"
    assert result.candidates[0].entity_type == "geo.city"
    assert result.candidates[0].pack_id == "geo"
    assert result.candidates[1].canonical_name == "Paris, Texas"
    assert RefinementHint.PARENT_IDS in result.refinement_hints
    assert RefinementHint.COUNTRY in result.refinement_hints


def test_no_match_keeps_recovery_candidates_and_hints():
    entities = {
        "city/Springfield_US": EntityRecord(
            entity_id="city/Springfield_US",
            entity_type="geo.city",
            canonical_name="Springfield",
            canonical_name_norm="springfield",
            relations=[
                RelationRecord(
                    relation_type="contained_in",
                    target_id="country/USA",
                )
            ],
        )
    }
    store = MockEntityStore(entities=entities)
    runner = PipelineRunner(
        trace_sink=NullTraceSink(),
        store=store,
        sources=[MockLowConfidenceFTSSource()],
        pack_id="geo",
        decision_policy=_DEFAULT_POLICY,
        type_prefixes=frozenset({"geo"}),
        country_relation_prefixes=frozenset({"country/"}),
    )

    resolver = Resolver(runner=runner, normalizer=TextNormalizer())
    result = resolver.resolve("Springfeld")

    assert result.status == ResolutionStatus.NO_MATCH
    assert result.pack_id == "geo"
    assert result.match_tier == MatchTier.FTS
    assert result.reasons == [ReasonCode.BELOW_CONFIDENCE_THRESHOLD]
    assert [candidate.entity_id for candidate in result.candidates] == [
        "city/Springfield_US"
    ]
    assert RefinementHint.PARENT_IDS in result.refinement_hints
    assert RefinementHint.COUNTRY in result.refinement_hints


class TestResolverFromDatapacks:
    def test_resolve_simple(self, geo_test_datapack):
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )

        result = resolver.resolve("US")

        assert result.status == ResolutionStatus.RESOLVED
        assert result.entity_id == "country/USA"

    def test_resolve_with_context(self, geo_test_datapack):
        from datetime import date

        from resolvekit.core.model import ResolutionContext

        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )

        result = resolver.resolve(
            "United States",
            context=ResolutionContext(as_of=date(2024, 1, 1)),
        )

        assert result.status == ResolutionStatus.RESOLVED

    @pytest.mark.parametrize(
        "query",
        [
            "US",  # exact code
            "Untied States",  # typo
            "qzwxz-no-match-here",  # no match
        ],
    )
    def test_resolve_explained_full_verbosity_does_not_crash(
        self, geo_test_datapack, query
    ):
        """resolve_explained(verbosity=FULL) must not crash
        with PipelineTiming ValidationError when concurrent trace events
        produce slightly out-of-order timestamps."""
        from resolvekit.core.explain import Verbosity

        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )

        explained = resolver.resolve_explained(query, verbosity=Verbosity.FULL)

        # All phase timings (and the total) must be non-negative.
        timing = explained.scorecard.timing
        if timing is not None:
            for value in (
                timing.generation_ms,
                timing.constraints_ms,
                timing.features_ms,
                timing.scoring_ms,
                timing.decision_ms,
                timing.total_ms,
            ):
                assert value is None or value >= 0.0

    def test_code_systems_returns_store_systems(self, geo_test_datapack):
        """code_systems() must reflect real code systems in the loaded stores."""
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )

        systems = resolver.code_systems()

        assert "iso2" in systems

    def test_resolver_uses_custom_normalizer(self, geo_test_datapack):
        calls = []

        class TracingNormalizer(TextNormalizer):
            def normalize(self, text: str):
                calls.append(text)
                return super().normalize(text)

        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack],
            domains=["geo"],
            normalizer=TracingNormalizer(),
        )

        resolver.resolve("United States")

        assert "United States" in calls

    def test_default_normalization_is_casefold(self, geo_test_datapack):
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )

        # Access internal normalized form
        normalized = resolver._normalize("UNITED STATES")

        assert normalized.normalized == "united states"

    def test_raises_on_no_valid_packs(self, tmp_path):
        import json

        # Create invalid datapack (unknown domain)
        (tmp_path / "metadata.json").write_text(
            json.dumps(
                {
                    "datapack_id": "unknown_v1",
                    "module_id": "unknown.entities",
                    "domain_pack_id": "unknown_domain",
                    "entity_schema_version": "1.0",
                    "feature_schema_version": "unknown.features.v1",
                    "normalizer_version": NORMALIZER_VERSION,
                    "build_timestamp": "2024-01-15T10:00:00Z",
                }
            )
        )

        import sqlite3

        db_path = tmp_path / "entities.sqlite"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE entities (entity_id TEXT PRIMARY KEY)")
        conn.close()

        import pytest

        with pytest.raises(ValueError, match="No valid packs found"):
            Resolver.from_datapacks(datapack_paths=[tmp_path])

    def test_raises_on_feature_schema_mismatch(self, geo_test_datapack):
        import json

        import pytest

        from resolvekit.core import IncompatibleFeatureSchemaError

        metadata_path = geo_test_datapack / "metadata.json"
        original = metadata_path.read_text()
        metadata = json.loads(original)
        metadata["feature_schema_version"] = "geo.features.v999"
        metadata_path.write_text(json.dumps(metadata))
        try:
            with pytest.raises(IncompatibleFeatureSchemaError):
                Resolver.from_datapacks(
                    datapack_paths=[geo_test_datapack], domains=["geo"]
                )
        finally:
            # Restore so the session-scoped fixture stays usable for the rest of the suite.
            metadata_path.write_text(original)

    def test_explicit_routing_mode(self, geo_test_datapack):
        from resolvekit.core.api import RoutingMode

        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack],
            domains=["geo"],
            routing_mode=RoutingMode.EXPLICIT,
        )

        # With explicit routing and domains
        result = resolver.resolve("US", domain="geo")

        assert result.status == ResolutionStatus.RESOLVED

    def test_auto_routing_with_domains_raises(self, geo_test_datapack):
        """AUTO mode + domains should error at API boundary."""
        import pytest

        from resolvekit.core.api import RoutingMode

        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack],
            domains=["geo"],
            routing_mode=RoutingMode.AUTO,
        )

        with pytest.raises(ValueError, match="Cannot specify domains with AUTO"):
            resolver.resolve("US", domain="geo")

    def test_auto_routing_with_domains_raises_with_explanation(self, geo_test_datapack):
        """AUTO mode + domains should error in resolve_explained."""
        import pytest

        from resolvekit.core.api import RoutingMode

        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack],
            domains=["geo"],
            routing_mode=RoutingMode.AUTO,
        )

        with pytest.raises(ValueError, match="Cannot specify domains with AUTO"):
            resolver.resolve_explained("US", domain="geo")

    def test_query_length_guardrail_applied_to_raw_text(self, geo_test_datapack):
        """raw_text should be truncated at API boundary."""
        from resolvekit.core.api import RoutingMode
        from resolvekit.core.explain import Verbosity

        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack],
            domains=["geo"],
            routing_mode=RoutingMode.AUTO,
            max_query_length=10,
        )

        # Long query should be truncated
        explained = resolver.resolve_explained(
            "United States of America is a country",
            verbosity=Verbosity.MINIMAL,
        )
        scorecard = explained.scorecard

        # Query text in scorecard should be truncated
        assert len(scorecard.query_text) == 10
        assert scorecard.query_text == "United Sta"

    def test_hybrid_routing_allows_domains(self, geo_test_datapack):
        """HYBRID mode should allow domains."""
        from resolvekit.core.api import RoutingMode

        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack],
            domains=["geo"],
            routing_mode=RoutingMode.HYBRID,
        )

        # Should not raise
        result = resolver.resolve("US", domain="geo")

        assert result.status == ResolutionStatus.RESOLVED

    def test_multiple_datapacks_merge_symspell_dicts(self, tmp_path):
        """When multiple same-domain datapacks are loaded, all symspell dicts are merged.

        GeoPack should receive symspell_dict_paths covering every module so that
        typo correction works for entities from any of the loaded datapacks.
        """
        import json
        import sqlite3

        import pytest

        pytest.importorskip("symspellpy")

        from resolvekit.core.api.loading import (
            _build_domain_stores,
            _create_pack_instances,
            _load_and_separate_datapacks,
        )
        from resolvekit.core.registry import _ensure_builtin_factories

        def _make_datapack(
            base: Path, module_id: str, symspell_terms: list[str]
        ) -> Path:
            """Helper: build a minimal geo datapack with a symspell dict."""
            db_path = base / "entities.sqlite"
            conn = sqlite3.connect(db_path)
            conn.executescript("""
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
            """)
            conn.commit()
            conn.close()

            dict_path = base / "symspell.dict"
            dict_path.write_text("\n".join(f"{t}\t100" for t in symspell_terms) + "\n")

            (base / "metadata.json").write_text(
                json.dumps(
                    {
                        "datapack_id": f"{module_id}_v1",
                        "module_id": module_id,
                        "domain_pack_id": "geo",
                        "entity_schema_version": "1.0",
                        "feature_schema_version": "geo.features.v1",
                        "normalizer_version": NORMALIZER_VERSION,
                        "index_versions": {"fts": "fts5"},
                        "build_timestamp": "2024-01-15T10:00:00Z",
                        "source_datasets": ["test-fixture"],
                        "artifacts": {
                            "sqlite": "entities.sqlite",
                            "symspell": "symspell.dict",
                        },
                    }
                )
            )
            return base

        pack1_dir = tmp_path / "pack1"
        pack1_dir.mkdir()
        pack2_dir = tmp_path / "pack2"
        pack2_dir.mkdir()

        _make_datapack(pack1_dir, "geo.admin1", ["france", "germany"])
        _make_datapack(pack2_dir, "geo.countries", ["nigeria", "kenya"])

        _ensure_builtin_factories()
        base_packs, overlay_packs = _load_and_separate_datapacks(
            [pack1_dir, pack2_dir], pack_filter={"geo"}
        )
        _domain_stores, domain_primary_loaded, _policies, domain_all_base_loaded = (
            _build_domain_stores(base_packs, overlay_packs, pack_filter={"geo"})
        )
        available_packs, _profiles, _normalizers = _create_pack_instances(
            domain_primary_loaded, domain_all_base_loaded
        )

        geo_pack = available_packs.get("geo")
        assert geo_pack is not None

        symspell_source = geo_pack.get_source("geo_symspell")
        assert symspell_source is not None
        # Index is lazy — trigger the build before inspecting _sym_spell.
        symspell_source._ensure_built()
        assert symspell_source._sym_spell is not None, (
            "SymSpell instance must be initialised when symspell dicts are present"
        )

        from symspellpy import Verbosity  # type: ignore[import-untyped]

        sym = symspell_source._sym_spell
        for typo, expected in [("frannce", "france"), ("keenya", "kenya")]:
            suggestions = sym.lookup(typo, Verbosity.CLOSEST, max_edit_distance=2)
            assert any(s.term == expected for s in suggestions), (
                f"Expected '{expected}' to be correctable from merged symspell dict"
            )


class TestResolverIntrospection:
    def test_domains_property(self, geo_test_datapack):
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )
        assert resolver.domains == ["geo"]

    def test_info_returns_resolver_info(self, geo_test_datapack):
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )
        info = resolver.info
        assert "geo" in info.domains
        assert info.routing_mode is not None
        assert info.max_query_length is not None
        assert info.closed is False

    def test_info_after_close(self, geo_test_datapack):
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )
        resolver.close()
        assert resolver.info.closed is True

    def test_info_includes_version_metadata(self, geo_test_datapack):
        """info must surface data_version, data_versions, resolvekit_version."""
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )
        info = resolver.info
        assert info.data_versions is not None
        assert info.resolvekit_version
        # Test fixture doesn't set data_version, so it falls back to datapack_id
        assert info.data_version == "geo_test_v1"
        assert info.data_versions == {
            "geo": {
                "geo.countries": {
                    "datapack_id": "geo_test_v1",
                    "data_version": None,
                    "build_timestamp": "2024-01-15T10:00:00Z",
                }
            }
        }

    def test_repr_open(self, geo_test_datapack):
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )
        r = repr(resolver)
        assert "geo" in r
        assert "open" in r

    def test_repr_closed(self, geo_test_datapack):
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )
        resolver.close()
        assert "closed" in repr(resolver)


class TestResolutionResultRepr:
    def test_resolved_repr(self, geo_test_datapack):
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )
        result = resolver.resolve("US")
        r = repr(result)
        assert "resolved" in r
        assert "country/USA" in r

    def test_no_match_repr(self, geo_test_datapack):
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )
        result = resolver.resolve("   ")
        r = repr(result)
        assert "no_match" in r

    def test_resolved_repr_html(self, geo_test_datapack):
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )
        result = resolver.resolve("US")
        html = result._repr_html_()
        assert "<table" in html
        assert "resolved" in html
        assert "country/USA" in html

    def test_no_match_repr_html(self, geo_test_datapack):
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )
        result = resolver.resolve("   ")
        html = result._repr_html_()
        assert "<table" in html
        assert "no_match" in html


class TestScorecardRepr:
    def test_scorecard_repr(self, geo_test_datapack):
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )
        explained = resolver.resolve_explained("US")
        r = repr(explained.scorecard)
        assert "Scorecard" in r
        assert "resolved" in r

    def test_scorecard_repr_html(self, geo_test_datapack):
        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack], domains=["geo"]
        )
        explained = resolver.resolve_explained("US")
        html = explained.scorecard._repr_html_()
        assert "<table" in html
        assert "resolved" in html


class TestGetEntity:
    def test_get_entity_returns_record(self):
        store = MockEntityStore(
            entities={
                "country/USA": EntityRecord(
                    entity_id="country/USA",
                    entity_type="geo.country",
                    canonical_name="United States",
                    canonical_name_norm="united states",
                )
            },
        )
        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=store,
            sources=[],
            decision_policy=_DEFAULT_POLICY,
        )
        resolver = Resolver(runner=runner)

        entity = resolver.entity("country/USA")

        assert entity is not None
        assert entity.entity_id == "country/USA"
        assert entity.canonical_name == "United States"

    def test_get_entity_not_found(self):
        store = MockEntityStore()
        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=store,
            sources=[],
            decision_policy=_DEFAULT_POLICY,
        )
        resolver = Resolver(runner=runner)

        assert resolver.entity("country/UNKNOWN") is None

    def test_get_entity_closed_raises(self):
        import pytest

        store = MockEntityStore()
        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=store,
            sources=[],
            decision_policy=_DEFAULT_POLICY,
        )
        resolver = Resolver(runner=runner)
        resolver.close()

        with pytest.raises(RuntimeError, match="closed"):
            resolver.entity("country/USA")


class TestCreatePackInstanceCalibratorWiring:
    def _make_loaded(self, tmp_path, module_id: str, artifacts: dict) -> LoadedDataPack:
        """Build a minimal LoadedDataPack with given artifact filenames."""
        from resolvekit.core.datapack import DataPackMetadata

        for filename in artifacts.values():
            (tmp_path / filename).write_text("{}")  # placeholder content

        metadata = DataPackMetadata(
            datapack_id=f"{module_id}-v1",
            module_id=module_id,
            domain_pack_id="geo",
            entity_schema_version="1.0",
            feature_schema_version="geo.features.v1",
            build_timestamp="2024-01-15T10:00:00Z",
            artifacts=artifacts,
        )
        return LoadedDataPack(metadata=metadata, base_path=tmp_path)

    def test_calibrator_wired_single_module(self, tmp_path):
        """Factory receives calibrator_path when metadata declares calibrator artifact."""
        from resolvekit.core.api.loading import _create_pack_instance

        received: dict = {}

        def factory(calibrator_path=None, symspell_dict_path=None):
            received["calibrator_path"] = calibrator_path
            received["symspell_dict_path"] = symspell_dict_path

        cal_dir = tmp_path / "mod1"
        cal_dir.mkdir()
        loaded = self._make_loaded(
            cal_dir,
            "geo.countries",
            {"calibrator": "cal.json"},
        )

        _create_pack_instance(factory, loaded)

        assert received["calibrator_path"] == str(cal_dir / "cal.json")

    def test_calibrator_wired_multi_module_primary_has_it(self, tmp_path):
        """Multi-module case: calibrator on primary loaded pack is wired."""
        from resolvekit.core.api.loading import _create_pack_instance

        received: dict = {}

        def factory(symspell_dict_paths=None, calibrator_path=None):
            received["symspell_dict_paths"] = symspell_dict_paths
            received["calibrator_path"] = calibrator_path

        dir1 = tmp_path / "mod1"
        dir1.mkdir()
        dir2 = tmp_path / "mod2"
        dir2.mkdir()

        loaded1 = self._make_loaded(dir1, "geo.countries", {"calibrator": "cal.json"})
        loaded2 = self._make_loaded(dir2, "geo.admin1", {})

        _create_pack_instance(factory, loaded1, all_loaded=[loaded1, loaded2])

        assert received["calibrator_path"] == str(dir1 / "cal.json")

    def test_calibrator_wired_multi_module_non_primary_has_it(self, tmp_path):
        """Multi-module case: calibrator on a non-primary loaded pack is still wired."""
        from resolvekit.core.api.loading import _create_pack_instance

        received: dict = {}

        def factory(symspell_dict_paths=None, calibrator_path=None):
            received["symspell_dict_paths"] = symspell_dict_paths
            received["calibrator_path"] = calibrator_path

        dir1 = tmp_path / "mod1"
        dir1.mkdir()
        dir2 = tmp_path / "mod2"
        dir2.mkdir()

        # Primary has no calibrator; secondary does
        loaded1 = self._make_loaded(dir1, "geo.admin1", {})
        loaded2 = self._make_loaded(dir2, "geo.countries", {"calibrator": "cal.json"})

        _create_pack_instance(factory, loaded1, all_loaded=[loaded1, loaded2])

        assert received["calibrator_path"] == str(dir2 / "cal.json")

    def test_no_calibrator_backward_compat(self, tmp_path):
        """Factory receives calibrator_path=None (or param absent) when no calibrator declared."""
        from resolvekit.core.api.loading import _create_pack_instance

        call_kwargs: dict = {}

        def factory(**kwargs):
            call_kwargs.update(kwargs)

        cal_dir = tmp_path / "mod1"
        cal_dir.mkdir()
        loaded = self._make_loaded(cal_dir, "geo.countries", {})

        _create_pack_instance(factory, loaded)

        # calibrator_path not present means None was never set
        assert call_kwargs.get("calibrator_path") is None

    def test_calibrator_skipped_when_factory_does_not_accept(self, tmp_path):
        """Factory that does NOT accept calibrator_path does not receive it."""
        from resolvekit.core.api.loading import _create_pack_instance

        received: dict = {}

        def factory(symspell_dict_path=None):
            received["symspell_dict_path"] = symspell_dict_path
            received["called"] = True

        cal_dir = tmp_path / "mod1"
        cal_dir.mkdir()
        loaded = self._make_loaded(
            cal_dir,
            "geo.countries",
            {"calibrator": "cal.json"},
        )

        # Should not raise even though calibrator artifact exists but factory ignores it
        _create_pack_instance(factory, loaded)

        assert received.get("called") is True
        assert "calibrator_path" not in received


def _make_simple_resolver() -> Resolver:
    """Minimal resolver for unit tests (no datapack required)."""
    store = MockEntityStore(codes={("iso2", "us"): ["country/USA"]})
    runner = PipelineRunner(
        trace_sink=NullTraceSink(),
        store=store,
        sources=[MockCodeSource()],
        decision_policy=_DEFAULT_POLICY,
    )
    return Resolver(runner=runner, normalizer=TextNormalizer())


class TestEmptyInputGuard:
    def test_resolve_none_returns_no_match(self):
        resolver = _make_simple_resolver()
        result = resolver.resolve(None)  # type: ignore[arg-type]
        assert result.status == ResolutionStatus.NO_MATCH
        assert result.reasons == [ReasonCode.INVALID_INPUT_TYPE]

    def test_resolve_empty_string_returns_no_match(self):
        resolver = _make_simple_resolver()
        result = resolver.resolve("")
        assert result.status == ResolutionStatus.NO_MATCH
        assert result.reasons == [ReasonCode.INVALID_QUERY]

    def test_resolve_whitespace_returns_no_match(self):
        resolver = _make_simple_resolver()
        result = resolver.resolve("   \t\n")
        assert result.status == ResolutionStatus.NO_MATCH
        assert result.reasons == [ReasonCode.INVALID_QUERY]

    def test_resolve_explained_none_returns_no_match(self):
        resolver = _make_simple_resolver()
        explained = resolver.resolve_explained(None)  # type: ignore[arg-type]
        assert explained.result.status == ResolutionStatus.NO_MATCH
        assert explained.result.reasons == [ReasonCode.INVALID_INPUT_TYPE]

    def test_resolve_explained_empty_returns_no_match(self):
        resolver = _make_simple_resolver()
        explained = resolver.resolve_explained("")
        assert explained.result.status == ResolutionStatus.NO_MATCH
        assert explained.result.reasons == [ReasonCode.INVALID_QUERY]

    @pytest.mark.parametrize(
        "value",
        [float("nan"), b"United States", 840, 3.14, [], {}, object()],
    )
    def test_resolve_non_string_returns_no_match(self, value):
        """bytes / int / float / NaN / arbitrary objects must not crash."""
        resolver = _make_simple_resolver()
        result = resolver.resolve(value)  # type: ignore[arg-type]
        assert result.status == ResolutionStatus.NO_MATCH
        assert result.reasons == [ReasonCode.INVALID_INPUT_TYPE]

    @pytest.mark.parametrize("value", [float("nan"), b"X", 840])
    def test_resolve_id_non_string_returns_none(self, value):
        resolver = _make_simple_resolver()
        assert resolver.resolve_id(value) is None  # type: ignore[arg-type]


class TestResolveIdErrorRaise:
    def test_resolve_id_raises_on_error_status(self):
        from typing import ClassVar

        from resolvekit.core.model import ResolutionResult

        class ErrorRunner:
            available_packs: ClassVar[list] = []

            def resolve(self, query, context, **kwargs):
                return ResolutionResult(status=ResolutionStatus.ERROR)

            def get_entity(self, entity_id):
                return None

            def lookup_code(self, system, value):
                return []

            def close(self):
                pass

        resolver = Resolver(runner=ErrorRunner())  # type: ignore[arg-type]
        with pytest.raises(ResolutionError) as exc_info:
            resolver.resolve_id("anything")
        assert exc_info.value.status == ResolutionStatus.ERROR

    def test_resolve_id_returns_none_for_no_match(self):
        resolver = _make_simple_resolver()
        result = resolver.resolve_id("unknown entity xyz")
        assert result is None

    def test_resolve_id_raises_ambiguous(self):
        store = MockEntityStore()
        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=store,
            sources=[MockAmbiguousSource()],
            decision_policy=_DEFAULT_POLICY,
        )
        resolver = Resolver(runner=runner)
        with pytest.raises(AmbiguousResolutionError):
            resolver.resolve_id("Paris")


class TestUnknownCodeSystemExported:
    def test_unknown_code_system_exported_from_errors_submodule(self):
        from resolvekit.errors import UnknownCodeSystemError

        assert UnknownCodeSystemError is not None


class TestExplicitKwargs:
    def test_auto_rejects_unknown_kwarg(self):
        with pytest.raises(TypeError):
            Resolver.auto(typo_param=True)  # type: ignore[call-arg]

    def test_from_modules_rejects_unknown_kwarg(self):
        with pytest.raises(TypeError):
            Resolver.from_modules(module_ids=[], typo_param=True)  # type: ignore[call-arg]

    def test_from_datapacks_rejects_unknown_kwarg(self):
        with pytest.raises(TypeError):
            Resolver.from_datapacks(datapack_paths=["/tmp/none"], typo_param=True)  # type: ignore[call-arg]


class TestExplainedResolutionRepr:
    def test_repr_contains_status_and_entity(self, geo_test_datapack):
        from resolvekit.core.api import RoutingMode

        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack],
            domains=["geo"],
            routing_mode=RoutingMode.AUTO,
        )
        explained = resolver.resolve_explained("US")
        r = repr(explained)
        assert "ExplainedResolution" in r
        assert "resolved" in r
        assert "country/USA" in r

    def test_repr_no_match(self, geo_test_datapack):
        from resolvekit.core.api import RoutingMode

        resolver = Resolver.from_datapacks(
            datapack_paths=[geo_test_datapack],
            domains=["geo"],
            routing_mode=RoutingMode.AUTO,
        )
        explained = resolver.resolve_explained("xyzzy_no_entity")
        r = repr(explained)
        assert "ExplainedResolution" in r
        assert "no_match" in r or "(no match)" in r


class TestTimeoutParam:
    def test_resolve_rejects_nonpositive_timeout(self):
        resolver = _make_simple_resolver()
        with pytest.raises(ValueError, match="timeout must be positive"):
            resolver.resolve("US", timeout=0)

    def test_resolve_rejects_negative_timeout(self):
        resolver = _make_simple_resolver()
        with pytest.raises(ValueError, match="timeout must be positive"):
            resolver.resolve("US", timeout=-1.0)

    def test_resolve_accepts_positive_timeout(self):
        resolver = _make_simple_resolver()
        result = resolver.resolve("US", timeout=5.0)
        assert result.status == ResolutionStatus.RESOLVED

    def test_resolve_explained_rejects_nonpositive_timeout(self):
        resolver = _make_simple_resolver()
        with pytest.raises(ValueError, match="timeout must be positive"):
            resolver.resolve_explained("US", timeout=0)


class TestConfidenceThresholdOverride:
    def test_confidence_threshold_applies_to_threshold_policy(self):
        """confidence_threshold= overrides the decision policy on a real runner."""
        store = MockEntityStore(codes={("iso2", "us"): ["country/USA"]})
        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=store,
            sources=[MockCodeSource()],
            decision_policy=ThresholdDecisionPolicy(
                confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
            ),
        )
        Resolver(runner=runner, confidence_threshold=0.55)
        # The policy threshold must have been updated.
        policy = runner._decision_policy
        assert policy.confidence_threshold == 0.55

    def test_confidence_threshold_zero_policies_emits_warning(self, caplog):
        """When no ThresholdDecisionPolicy is found, a warning is emitted."""
        import logging

        from resolvekit.core.engine.interfaces import DecisionPolicy, ResolverBackend

        class NoOpPolicy(DecisionPolicy):
            """A policy that is not a ThresholdDecisionPolicy."""

            def decide(self, query, context, candidates, trace):
                from resolvekit.core.model import ResolutionResult, ResolutionStatus

                return ResolutionResult(status=ResolutionStatus.NO_MATCH)

        class StubRunner(ResolverBackend):
            _decision_policy = NoOpPolicy()

            @property
            def available_packs(self):
                return frozenset()

            @property
            def available_entity_types(self):
                return frozenset()

            @property
            def available_code_systems(self):
                return frozenset()

            @property
            def available_group_types(self):
                return frozenset()

            def resolve(self, query, context, *, deadline=None):
                from resolvekit.core.model import ResolutionResult, ResolutionStatus

                return ResolutionResult(status=ResolutionStatus.NO_MATCH)

            def resolve_detailed(self, query, context, *, deadline=None):
                from resolvekit.core.engine import PipelineResult

                return PipelineResult(result=self.resolve(query, context))

            def get_entity(self, entity_id):
                return None

            def store_for_domain(self, domain):
                raise ValueError(f"no store for {domain}")

            def apply_confidence_threshold(self, *, threshold: float) -> bool:
                # NoOpPolicy is not a ThresholdDecisionPolicy; nothing to update.
                return False

            def close(self):
                pass

        runner = StubRunner()
        with caplog.at_level(logging.WARNING, logger="resolvekit.core.api.resolver"):
            Resolver(runner=runner, confidence_threshold=0.85)

        assert any(
            "no effect" in rec.message or "had no effect" in rec.message
            for rec in caplog.records
        ), f"Expected a 'no effect' warning; got: {[r.message for r in caplog.records]}"

    def test_confidence_threshold_none_does_not_warn(self, caplog):
        """Passing confidence_threshold=None must not emit any warning."""
        import logging

        store = MockEntityStore(codes={("iso2", "us"): ["country/USA"]})
        runner = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=store,
            sources=[MockCodeSource()],
            decision_policy=ThresholdDecisionPolicy(
                confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
            ),
        )
        with caplog.at_level(logging.WARNING, logger="resolvekit.core.api.resolver"):
            Resolver(runner=runner, confidence_threshold=None)

        assert not caplog.records, (
            f"Unexpected warning when confidence_threshold=None: {[r.message for r in caplog.records]}"
        )

    def test_confidence_threshold_multipack_applies_to_all_runners(self):
        """confidence_threshold= updates all sub-runners in a multi-pack backend.

        Uses a stub runner whose _runners dict holds two PipelineRunner instances,
        matching the shape that _apply_confidence_threshold_override introspects.
        """
        store_a = MockEntityStore(codes={("iso2", "us"): ["country/USA"]})
        store_b = MockEntityStore(codes={("iso2", "us"): ["country/USA"]})

        policy_a = ThresholdDecisionPolicy(
            confidence_threshold=0.8, min_gap=0.1, gap_inclusive=True
        )
        policy_b = ThresholdDecisionPolicy(
            confidence_threshold=0.75, min_gap=0.05, gap_inclusive=True
        )
        runner_a = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=store_a,
            sources=[MockCodeSource()],
            pack_id="geo",
            decision_policy=policy_a,
        )
        runner_b = PipelineRunner(
            trace_sink=NullTraceSink(),
            store=store_b,
            sources=[MockCodeSource()],
            pack_id="org",
            decision_policy=policy_b,
        )

        # Build a minimal stub runner that exposes _runners as a dict, matching
        # the shape that _apply_confidence_threshold_override introspects on a
        # real MultiPackRunner.
        from resolvekit.core.engine.interfaces import ResolverBackend

        class StubMultiRunner(ResolverBackend):
            def __init__(self, runners_dict):
                self._runners = runners_dict

            @property
            def available_packs(self):
                return frozenset(self._runners)

            @property
            def available_entity_types(self):
                return frozenset()

            @property
            def available_code_systems(self):
                return frozenset()

            @property
            def available_group_types(self):
                return frozenset()

            def resolve(self, query, context, *, deadline=None):
                from resolvekit.core.model import ResolutionResult, ResolutionStatus

                return ResolutionResult(status=ResolutionStatus.NO_MATCH)

            def resolve_detailed(self, query, context, *, deadline=None):
                from resolvekit.core.engine import PipelineResult

                return PipelineResult(result=self.resolve(query, context))

            def get_entity(self, entity_id):
                return None

            def store_for_domain(self, domain):
                raise ValueError(f"no store for {domain}")

            def apply_confidence_threshold(self, *, threshold: float) -> bool:
                results = [
                    r.apply_confidence_threshold(threshold=threshold)
                    for r in self._runners.values()
                ]
                return any(results)

            def close(self):
                pass

        multi = StubMultiRunner({"geo": runner_a, "org": runner_b})
        Resolver(runner=multi, confidence_threshold=0.60)

        assert policy_a.confidence_threshold == 0.60
        assert policy_b.confidence_threshold == 0.60
