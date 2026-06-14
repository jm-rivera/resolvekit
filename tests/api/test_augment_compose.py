"""Tests for chained augment() composition.

Verifies that r2 = r1.augment(B) retains entities from both overlays A and B,
that three-deep chaining preserves all three overlays, and that prior resolvers
are unaffected by later augments (immutability).
"""

from __future__ import annotations

import json
from pathlib import Path

from resolvekit.core.api.resolver import Resolver
from resolvekit.core.datapack import NORMALIZER_VERSION
from resolvekit.shared import BaseDataPackBuilder

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def _write_geo_base(path: Path) -> Path:
    """Build a minimal geo base pack (FRA + DEU + BRA) and return the pack dir."""
    pack_dir = path / "geo.base"
    pack_dir.mkdir(parents=True, exist_ok=True)

    builder = BaseDataPackBuilder(output_dir=pack_dir)
    builder.create_database()
    for iso3, name, name_norm in [
        ("FRA", "France", "france"),
        ("DEU", "Germany", "germany"),
        ("BRA", "Brazil", "brazil"),
    ]:
        builder.add_entity(
            entity_id=f"geo/{iso3}",
            entity_type="geo.country",
            canonical_name=name,
            canonical_name_norm=name_norm,
            attrs={},
        )
        builder.add_code(f"geo/{iso3}", "iso3", iso3, iso3.lower())
        builder.add_name(f"geo/{iso3}", "canonical", name, name_norm, lang="en")
    builder.finalize()
    builder.close()

    metadata = {
        "datapack_id": "geo.base-compose-fixture-v1",
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
# Tests
# ---------------------------------------------------------------------------


class TestAugmentComposesTwoOverlays:
    def test_r2_resolves_alias_from_overlay_a(self, tmp_path: Path) -> None:
        """r2 = r1.augment(B): an alias added only in overlay A still resolves on r2."""
        base_dir = _write_geo_base(tmp_path)
        r0 = Resolver.from_datapacks(datapack_paths=[base_dir], domains=["geo"])

        r1 = r0.augment(
            [{"iso3": "FRA", "local": "Frankreich"}],
            link_on=["iso3"],
            add_aliases=["local"],
            cache=False,
        )
        r2 = r1.augment(
            [{"iso3": "DEU", "local": "Allemagne"}],
            link_on=["iso3"],
            add_aliases=["local"],
            cache=False,
        )

        result = r2.resolve("Frankreich")
        assert result.entity_id == "geo/FRA", (
            f"Overlay-A alias 'Frankreich' should resolve to geo/FRA on r2; "
            f"got entity_id={result.entity_id!r} status={result.status}"
        )

    def test_r2_resolves_alias_from_overlay_b(self, tmp_path: Path) -> None:
        """r2 = r1.augment(B): an alias added only in overlay B resolves on r2."""
        base_dir = _write_geo_base(tmp_path)
        r0 = Resolver.from_datapacks(datapack_paths=[base_dir], domains=["geo"])

        r1 = r0.augment(
            [{"iso3": "FRA", "local": "Frankreich"}],
            link_on=["iso3"],
            add_aliases=["local"],
            cache=False,
        )
        r2 = r1.augment(
            [{"iso3": "DEU", "local": "Allemagne"}],
            link_on=["iso3"],
            add_aliases=["local"],
            cache=False,
        )

        result = r2.resolve("Allemagne")
        assert result.entity_id == "geo/DEU", (
            f"Overlay-B alias 'Allemagne' should resolve to geo/DEU on r2; "
            f"got entity_id={result.entity_id!r} status={result.status}"
        )

    def test_base_entity_still_resolves_on_r2(self, tmp_path: Path) -> None:
        """The base entity's canonical name still resolves on r2."""
        base_dir = _write_geo_base(tmp_path)
        r0 = Resolver.from_datapacks(datapack_paths=[base_dir], domains=["geo"])

        r1 = r0.augment(
            [{"iso3": "FRA", "local": "Frankreich"}],
            link_on=["iso3"],
            add_aliases=["local"],
            cache=False,
        )
        r2 = r1.augment(
            [{"iso3": "DEU", "local": "Allemagne"}],
            link_on=["iso3"],
            add_aliases=["local"],
            cache=False,
        )

        assert r2.resolve("France").entity_id == "geo/FRA"
        assert r2.resolve("Germany").entity_id == "geo/DEU"


class TestAugmentComposeThreeDeep:
    def test_three_deep_chaining_preserves_all_aliases(self, tmp_path: Path) -> None:
        """Three-deep chaining (.augment().augment().augment()) preserves all three overlays."""
        base_dir = _write_geo_base(tmp_path)
        r0 = Resolver.from_datapacks(datapack_paths=[base_dir], domains=["geo"])

        r1 = r0.augment(
            [{"iso3": "FRA", "local": "Frankreich"}],
            link_on=["iso3"],
            add_aliases=["local"],
            cache=False,
        )
        r2 = r1.augment(
            [{"iso3": "DEU", "local": "Allemagne"}],
            link_on=["iso3"],
            add_aliases=["local"],
            cache=False,
        )
        r3 = r2.augment(
            [{"iso3": "BRA", "local": "Brésil"}],
            link_on=["iso3"],
            add_aliases=["local"],
            cache=False,
        )

        assert r3.resolve("Frankreich").entity_id == "geo/FRA", (
            "Overlay-A alias should still resolve after three-deep augment"
        )
        assert r3.resolve("Allemagne").entity_id == "geo/DEU", (
            "Overlay-B alias should still resolve after three-deep augment"
        )
        assert r3.resolve("Brésil").entity_id == "geo/BRA", (
            "Overlay-C alias should resolve on r3"
        )


class TestAugmentPriorResolverImmutability:
    def test_r1_unchanged_after_r2_built(self, tmp_path: Path) -> None:
        """r1 is unchanged after r2 = r1.augment(B) — B does not leak back into r1."""
        base_dir = _write_geo_base(tmp_path)
        r0 = Resolver.from_datapacks(datapack_paths=[base_dir], domains=["geo"])

        r1 = r0.augment(
            [{"iso3": "FRA", "local": "Frankreich"}],
            link_on=["iso3"],
            add_aliases=["local"],
            cache=False,
        )
        r1.augment(
            [{"iso3": "DEU", "local": "Allemagne"}],
            link_on=["iso3"],
            add_aliases=["local"],
            cache=False,
        )

        # Overlay-B alias must NOT resolve on r1 (augment returns a NEW resolver).
        r1_deu = r1.resolve("Allemagne")
        assert not r1_deu.is_resolved, (
            f"Overlay-B alias 'Allemagne' should not resolve on r1 (B was added to r2); "
            f"got entity_id={r1_deu.entity_id!r} status={r1_deu.status}"
        )

        # r0 also untouched.
        r0_fra = r0.resolve("Frankreich")
        assert not r0_fra.is_resolved, (
            "Overlay-A alias 'Frankreich' should not resolve on r0"
        )

    def test_r1_r2_unchanged_after_r3_built(self, tmp_path: Path) -> None:
        """r1 and r2 are unchanged after r3 = r2.augment(C)."""
        base_dir = _write_geo_base(tmp_path)
        r0 = Resolver.from_datapacks(datapack_paths=[base_dir], domains=["geo"])

        r1 = r0.augment(
            [{"iso3": "FRA", "local": "Frankreich"}],
            link_on=["iso3"],
            add_aliases=["local"],
            cache=False,
        )
        r2 = r1.augment(
            [{"iso3": "DEU", "local": "Allemagne"}],
            link_on=["iso3"],
            add_aliases=["local"],
            cache=False,
        )
        r3 = r2.augment(  # noqa: F841
            [{"iso3": "BRA", "local": "Brésil"}],
            link_on=["iso3"],
            add_aliases=["local"],
            cache=False,
        )

        # r1 still only has overlay-A.
        assert not r1.resolve("Allemagne").is_resolved
        assert not r1.resolve("Brésil").is_resolved
        assert r1.resolve("Frankreich").entity_id == "geo/FRA"

        # r2 has overlays A+B but not C.
        assert r2.resolve("Frankreich").entity_id == "geo/FRA"
        assert r2.resolve("Allemagne").entity_id == "geo/DEU"
        assert not r2.resolve("Brésil").is_resolved


class TestAugmentComposeReturnReport:
    def test_return_report_tallies_unaffected_by_composition(
        self, tmp_path: Path
    ) -> None:
        """return_report=True tallies reflect only the current augment's rows."""
        base_dir = _write_geo_base(tmp_path)
        r0 = Resolver.from_datapacks(datapack_paths=[base_dir], domains=["geo"])

        r1 = r0.augment(
            [{"iso3": "FRA", "local": "Frankreich"}],
            link_on=["iso3"],
            add_aliases=["local"],
            cache=False,
        )
        report = r1.augment(
            [
                {"iso3": "DEU", "local": "Allemagne"},
                {"iso3": "ZZZ", "local": "NoSuchLand"},  # will be skipped
            ],
            link_on=["iso3"],
            add_aliases=["local"],
            on_miss="skip",
            return_report=True,
            cache=False,
        )

        from resolvekit.core.byod.result import AugmentResult

        assert isinstance(report, AugmentResult)
        # Only the two rows from this augment are tallied (not from r1's overlay).
        assert report.linked == 1  # DEU
        assert report.skipped == 1  # ZZZ
        assert report.minted == 0
        assert report.ambiguous == 0

        # And both overlays are present on the returned resolver.
        assert report.resolver.resolve("Frankreich").entity_id == "geo/FRA"
        assert report.resolver.resolve("Allemagne").entity_id == "geo/DEU"
