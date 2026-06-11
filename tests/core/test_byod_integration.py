"""End-to-end integration tests for Resolver.from_records and Resolver.augment.

Verifies: augment adds an alias that resolves through a new resolver;
from_records stands up a custom pack that resolves names and codes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from resolvekit.core.api.resolver import Resolver
from resolvekit.core.byod.result import AugmentResult
from resolvekit.core.datapack import NORMALIZER_VERSION
from resolvekit.shared import BaseDataPackBuilder

# ---------------------------------------------------------------------------
# Shared fixture helpers
# ---------------------------------------------------------------------------


def _write_geo_base(path: Path) -> Path:
    """Build a minimal geo base pack under *path* and return the pack dir.

    Creates entity ``geo/FRA`` with canonical name "France" and code
    ``iso3="FRA"``.  The pack is written using the low-level builder to keep
    the fixture independent of the BYOD verbs under test.
    """
    pack_dir = path / "geo.base"
    pack_dir.mkdir(parents=True, exist_ok=True)

    # Write entities via the shared builder.
    builder = BaseDataPackBuilder(output_dir=pack_dir)
    builder.create_database()
    builder.add_entity(
        entity_id="geo/FRA",
        entity_type="geo.country",
        canonical_name="France",
        canonical_name_norm="france",
        attrs={},
    )
    builder.add_code("geo/FRA", "iso3", "FRA", "fra")
    builder.add_name("geo/FRA", "canonical", "France", "france", lang="en")
    builder.finalize()
    builder.close()

    # Write metadata expected by the pack loader.
    metadata = {
        "datapack_id": "geo.base-byod-fixture-v1",
        "module_id": "geo.base",
        "domain_pack_id": "geo",
        "module_dependencies": [],
        "entity_schema_version": "1.0.0",
        "feature_schema_version": "geo.features.v1",
        "normalizer_version": NORMALIZER_VERSION,
        "build_timestamp": "2024-01-15T10:00:00Z",
        "pack_type": "base",
        "store_type": "sqlite",
        "store_file": "entities.sqlite",
    }
    (pack_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=True) + "\n"
    )
    return pack_dir


# ---------------------------------------------------------------------------
# 1. augment adds an alias → resolves by that alias (closes doc §10)
# ---------------------------------------------------------------------------


class TestAugmentAddsAlias:
    def test_alias_resolves_by_name(self, tmp_path: Path) -> None:
        """Augmenting with add_aliases makes the new alias resolve to the base entity."""
        pack_dir = _write_geo_base(tmp_path)
        r0 = Resolver.from_datapacks(datapack_paths=[pack_dir], domains=["geo"])

        r1 = r0.augment(
            [{"iso3": "FRA", "local": "République"}],
            link_on=["iso3"],
            add_aliases=["local"],
        )

        result = r1.resolve("République")
        assert result.entity_id == "geo/FRA", (
            f"expected geo/FRA, got {result.entity_id!r} (status={result.status})"
        )

    def test_original_name_still_resolves(self, tmp_path: Path) -> None:
        """The base entity's original name still resolves after augment."""
        pack_dir = _write_geo_base(tmp_path)
        r0 = Resolver.from_datapacks(datapack_paths=[pack_dir], domains=["geo"])
        r1 = r0.augment(
            [{"iso3": "FRA", "local": "République"}],
            link_on=["iso3"],
            add_aliases=["local"],
        )
        result = r1.resolve("France")
        assert result.entity_id == "geo/FRA"


# ---------------------------------------------------------------------------
# 2. augment add_codes queryable
# ---------------------------------------------------------------------------


class TestAugmentAddCodes:
    def test_added_code_queryable_via_entity(self, tmp_path: Path) -> None:
        """After augment with add_codes, resolver.entity(internal_id=...) works.

        Note: entity() casefolds the lookup value before the store query, so the
        test uses an already-lowercase code ("x42") that round-trips through
        BaseNormalizer unchanged.  Mixed-case codes (e.g. "X42") are stored as-is
        by BaseNormalizer but entity() would pass "x42" — a known limitation of
        the generic code path for custom domain codes.
        """
        pack_dir = _write_geo_base(tmp_path)
        r0 = Resolver.from_datapacks(datapack_paths=[pack_dir], domains=["geo"])

        r1 = r0.augment(
            [{"iso3": "FRA", "internal_id": "x42"}],
            link_on=["iso3"],
            add_codes=["internal_id"],
        )

        rec = r1.entity(internal_id="x42")
        assert rec is not None, "entity() returned None for added code"
        assert rec.entity_id == "geo/FRA", f"expected geo/FRA, got {rec.entity_id!r}"


# ---------------------------------------------------------------------------
# 3. from_records standalone: resolves name + code
# ---------------------------------------------------------------------------


class TestFromRecordsStandalone:
    def test_resolve_by_name(self, tmp_path: Path) -> None:
        """from_records with domain='custom' resolves the canonical name."""
        r = Resolver.from_records(
            [{"id": "w1", "label": "Widget", "sku": "ABC"}],
            domain="custom",
            name="label",
            id="id",
            codes=["sku"],
        )
        result = r.resolve("Widget")
        assert result.entity_id == "custom/w1", (
            f"expected custom/w1, got {result.entity_id!r} (status={result.status})"
        )

    def test_resolve_by_code(self, tmp_path: Path) -> None:
        """from_records with domain='custom' supports entity() by code.

        entity() casefolds the lookup value, so the code value must survive
        casefolding unchanged (i.e., use lowercase codes for custom packs).
        """
        r = Resolver.from_records(
            [{"id": "w1", "label": "Widget", "sku": "abc"}],
            domain="custom",
            name="label",
            id="id",
            codes=["sku"],
        )
        rec = r.entity(sku="abc")
        assert rec is not None, "entity() returned None for code lookup"
        assert rec.entity_id == "custom/w1", (
            f"expected custom/w1, got {rec.entity_id!r}"
        )

    def test_auto_seq_id(self) -> None:
        """When id= is omitted, entity IDs are sequential integers under namespace."""
        r = Resolver.from_records(
            [{"label": "Alpha"}, {"label": "Beta"}],
            domain="custom",
            name="label",
        )
        assert r.resolve("Alpha").entity_id == "custom/0"
        assert r.resolve("Beta").entity_id == "custom/1"


# ---------------------------------------------------------------------------
# 4. mint-on-miss e2e
# ---------------------------------------------------------------------------


class TestMintOnMiss:
    def test_mint_on_miss_resolves_by_name(self, tmp_path: Path) -> None:
        """augment(on_miss='mint') creates a new entity that resolves by its name."""
        pack_dir = _write_geo_base(tmp_path)
        r0 = Resolver.from_datapacks(datapack_paths=[pack_dir], domains=["geo"])

        # "ZZZ" does not exist in the base — it will be minted.
        r1 = r0.augment(
            [{"iso3": "ZZZ", "local": "Zedonia"}],
            link_on=["iso3"],
            add_aliases=["local"],
            on_miss="mint",
            namespace="extra",
        )

        # The minted entity's alias "Zedonia" should resolve.
        result = r1.resolve("Zedonia")
        assert result.is_resolved, (
            f"expected minted entity to resolve, got status={result.status}"
        )
        assert result.entity_id is not None
        assert result.entity_id.startswith("extra/"), (
            f"minted entity_id should start with 'extra/', got {result.entity_id!r}"
        )


# ---------------------------------------------------------------------------
# 5. return_report=True → AugmentResult; happy path → bare Resolver
# ---------------------------------------------------------------------------


class TestReturnReport:
    def test_happy_path_returns_resolver(self, tmp_path: Path) -> None:
        """augment without return_report returns a bare Resolver."""
        pack_dir = _write_geo_base(tmp_path)
        r0 = Resolver.from_datapacks(datapack_paths=[pack_dir], domains=["geo"])
        result = r0.augment(
            [{"iso3": "FRA", "local": "République"}],
            link_on=["iso3"],
            add_aliases=["local"],
        )
        assert isinstance(result, Resolver), f"expected Resolver, got {type(result)}"

    def test_return_report_true_gives_augment_result(self, tmp_path: Path) -> None:
        """augment(return_report=True) returns an AugmentResult with counts."""
        pack_dir = _write_geo_base(tmp_path)
        r0 = Resolver.from_datapacks(datapack_paths=[pack_dir], domains=["geo"])

        report = r0.augment(
            [{"iso3": "FRA", "local": "République"}],
            link_on=["iso3"],
            add_aliases=["local"],
            return_report=True,
        )
        assert isinstance(report, AugmentResult), (
            f"expected AugmentResult, got {type(report)}"
        )
        assert isinstance(report.resolver, Resolver)
        # One row linked to FRA.
        assert report.linked == 1
        assert report.minted == 0
        assert report.skipped == 0
        assert report.ambiguous == 0

    def test_return_report_with_skip(self, tmp_path: Path) -> None:
        """Skipped rows are counted in AugmentResult.skipped."""
        pack_dir = _write_geo_base(tmp_path)
        r0 = Resolver.from_datapacks(datapack_paths=[pack_dir], domains=["geo"])

        report = r0.augment(
            [
                {"iso3": "FRA", "local": "République"},
                {"iso3": "ZZZ", "local": "Zedonia"},  # no match, skipped
            ],
            link_on=["iso3"],
            add_aliases=["local"],
            on_miss="skip",
            return_report=True,
        )
        assert isinstance(report, AugmentResult)
        assert report.linked == 1
        assert report.skipped == 1


# ---------------------------------------------------------------------------
# 6. Error cases
# ---------------------------------------------------------------------------


class TestErrorCases:
    def test_empty_link_on_raises(self, tmp_path: Path) -> None:
        """augment with empty link_on raises ValueError."""
        pack_dir = _write_geo_base(tmp_path)
        r = Resolver.from_datapacks(datapack_paths=[pack_dir], domains=["geo"])

        with pytest.raises(ValueError, match="link_on cannot be empty"):
            r.augment(
                [{"iso3": "FRA"}],
                link_on=[],
            )

    def test_unknown_link_on_system_raises(self, tmp_path: Path) -> None:
        """augment with an unknown link_on system raises ValueError listing available."""
        pack_dir = _write_geo_base(tmp_path)
        r = Resolver.from_datapacks(datapack_paths=[pack_dir], domains=["geo"])

        with pytest.raises(ValueError, match="nope"):
            r.augment(
                [{"nope": "X"}],
                link_on=["nope"],
            )

    def test_invalid_namespace_raises(self) -> None:
        """from_records with namespace='../evil' raises ValueError (path-traversal guard)."""
        with pytest.raises(ValueError, match=r"\.\./evil"):
            Resolver.from_records(
                [{"id": "w1", "label": "Widget"}],
                domain="custom",
                name="label",
                id="id",
                namespace="../evil",
            )

    def test_invalid_namespace_in_augment_raises(self, tmp_path: Path) -> None:
        """augment with namespace='../evil' raises ValueError."""
        pack_dir = _write_geo_base(tmp_path)
        r = Resolver.from_datapacks(datapack_paths=[pack_dir], domains=["geo"])

        with pytest.raises(ValueError, match=r"\.\./evil"):
            r.augment(
                [{"iso3": "ZZZ", "local": "Zedonia"}],
                link_on=["iso3"],
                on_miss="mint",
                namespace="../evil",
            )

    def test_link_on_name_only_without_aliases_or_codes_raises(
        self, tmp_path: Path
    ) -> None:
        """augment(link_on=['name']) with no add_aliases/add_codes raises ValueError."""
        pack_dir = _write_geo_base(tmp_path)
        r = Resolver.from_datapacks(datapack_paths=[pack_dir], domains=["geo"])

        with pytest.raises(ValueError, match="add_aliases or add_codes"):
            r.augment(
                [{"name": "France"}],
                link_on=["name"],
                # intentionally no add_aliases, no add_codes
            )


# ---------------------------------------------------------------------------
# 7. Multi-row-per-entity e2e (regression guard)
# ---------------------------------------------------------------------------


class TestMultiRowPerEntityIntegration:
    def test_two_rows_same_base_entity_no_crash_aliases_both_resolve(
        self, tmp_path: Path
    ) -> None:
        """Two augment rows for the same base entity — no crash, both aliases
        resolve through the new resolver.
        """
        pack_dir = _write_geo_base(tmp_path)
        r0 = Resolver.from_datapacks(datapack_paths=[pack_dir], domains=["geo"])

        # Two rows both keyed to geo/FRA (iso3=FRA), each adding a different alias.
        report = r0.augment(
            [
                {"iso3": "FRA", "local": "République française"},
                {"iso3": "FRA", "local": "Frankreich"},
            ],
            link_on=["iso3"],
            add_aliases=["local"],
            return_report=True,
        )

        assert isinstance(report, AugmentResult)
        assert report.linked == 2, (
            f"expected 2 linked rows (both iso3=FRA), got {report.linked}"
        )

        r1 = report.resolver
        res1 = r1.resolve("République française")
        assert res1.entity_id == "geo/FRA", (
            f"first alias should resolve to geo/FRA, got {res1.entity_id!r}"
        )
        res2 = r1.resolve("Frankreich")
        assert res2.entity_id == "geo/FRA", (
            f"second alias should resolve to geo/FRA, got {res2.entity_id!r}"
        )


# ---------------------------------------------------------------------------
# 8. augment(columns=...) e2e
# ---------------------------------------------------------------------------


class TestAugmentColumnsRename:
    def test_renamed_name_column_links_row(self, tmp_path: Path) -> None:
        """augment(columns={"name": "country_name"}) links the row.

        The columns= parameter maps logical role names to actual data columns.
        """
        pack_dir = _write_geo_base(tmp_path)
        r0 = Resolver.from_datapacks(datapack_paths=[pack_dir], domains=["geo"])

        report = r0.augment(
            [{"country_name": "France", "iso3": "FRA"}],
            link_on=["iso3"],
            columns={"name": "country_name"},
            return_report=True,
        )

        assert isinstance(report, AugmentResult)
        assert report.linked == 1, (
            f"expected 1 linked row after columns= rename, got {report.linked}"
        )


# ---------------------------------------------------------------------------
# 9. from_records — geo and org domain smoke tests
# ---------------------------------------------------------------------------


class TestFromRecordsGeoDomain:
    def test_resolve_by_name(self) -> None:
        """from_records(domain='geo') mints a standalone geo pack; name resolves."""
        r = Resolver.from_records(
            [{"name": "France", "iso3": "FRA"}],
            domain="geo",
            name="name",
            codes=["iso3"],
        )
        result = r.resolve("France")
        assert result.entity_id is not None, (
            f"expected non-None entity_id, got status={result.status}"
        )

    def test_resolve_by_code(self) -> None:
        """entity(iso3=...) resolves for geo BYOD packs, case-insensitively.

        GeoNormalizer casefolds code values at build time, so iso3 is stored
        as "fra". The query side normalizes through the same GeoNormalizer,
        so both "FRA" and "fra" query forms resolve to the stored code.
        """
        r = Resolver.from_records(
            [{"name": "France", "iso3": "FRA"}],
            domain="geo",
            name="name",
            codes=["iso3"],
        )
        expected = r.resolve("France").entity_id
        assert expected is not None

        rec_upper = r.entity(iso3="FRA")
        assert rec_upper is not None, "geo entity(iso3='FRA') returned None"
        assert rec_upper.entity_id == expected

        rec_lower = r.entity(iso3="fra")
        assert rec_lower is not None, "geo entity(iso3='fra') returned None"
        assert rec_lower.entity_id == expected


class TestFromRecordsOrgDomain:
    def test_resolve_by_name(self) -> None:
        """from_records(domain='org') mints a standalone org pack; name resolves."""
        r = Resolver.from_records(
            [{"name": "World Health Organization", "acronym": "WHO"}],
            domain="org",
            name="name",
            codes=["acronym"],
        )
        result = r.resolve("World Health Organization")
        assert result.entity_id is not None, (
            f"expected non-None entity_id, got status={result.status}"
        )

    def test_resolve_by_code(self) -> None:
        """from_records(domain='org') — entity lookup by code resolves, case-insensitively."""
        r = Resolver.from_records(
            [{"name": "World Health Organization", "acronym": "who"}],
            domain="org",
            name="name",
            codes=["acronym"],
        )
        rec = r.entity(acronym="who")
        assert rec is not None, "entity(acronym=...) returned None for org domain"
        assert rec.entity_id is not None
        # An uppercase query form also matches the stored code.
        assert r.entity(acronym="WHO") is not None
        assert r.entity(acronym="WHO").entity_id == rec.entity_id
