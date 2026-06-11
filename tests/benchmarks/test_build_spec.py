"""Tests for the DatasetSpec registry.

Verifies the registry invariant (DATASET_SPECS == DATASET_NAMES), the eval flag
on eval and eval_org, and source_limits on country datasets.
"""

from __future__ import annotations

import pytest

from benchmarks.build import DATASET_SPECS, DatasetSpec, build_dataset
from benchmarks.build.spec import DATASET_NAMES


def test_dataset_specs_covers_all_known_names() -> None:
    """DATASET_SPECS has an entry for every name in DATASET_NAMES."""
    for name in DATASET_NAMES:
        assert name in DATASET_SPECS, f"DATASET_SPECS missing entry for {name!r}"


def test_known_names_covers_all_specs() -> None:
    """DATASET_NAMES covers every key in DATASET_SPECS (registry coherence guarantee)."""
    assert set(DATASET_SPECS) == set(DATASET_NAMES), (
        f"DATASET_SPECS keys {sorted(DATASET_SPECS)} do not match "
        f"DATASET_NAMES {sorted(DATASET_NAMES)}"
    )


def test_dataset_specs_all_values_are_datasetspec() -> None:
    """Every value in DATASET_SPECS is a DatasetSpec instance."""
    for name, spec in DATASET_SPECS.items():
        assert isinstance(spec, DatasetSpec), (
            f"DATASET_SPECS[{name!r}] is {type(spec)!r}, expected DatasetSpec"
        )
        assert spec.name == name, (
            f"DatasetSpec.name {spec.name!r} does not match its registry key {name!r}"
        )


def test_org_v1_not_in_registry() -> None:
    """org_v1 is not in the registry."""
    assert "org_v1" not in DATASET_SPECS
    assert "org_v1" not in DATASET_NAMES


def test_eval_geo_has_eval_flag() -> None:
    """eval_geo is marked as an eval dataset."""
    spec = DATASET_SPECS["eval_geo"]
    assert spec.eval is True


def test_eval_org_has_eval_flag() -> None:
    """eval_org is marked as an eval dataset."""
    spec = DATASET_SPECS["eval_org"]
    assert spec.eval is True


def test_geo_countries_en_has_source_limits() -> None:
    """geo_countries_en records its source-level row limits."""
    spec = DATASET_SPECS["geo_countries_en"]
    assert spec.source_limits is not None
    assert "cldr" in spec.source_limits
    assert "geonames" in spec.source_limits
    assert "wikidata" in spec.source_limits
    assert "synthetic" in spec.source_limits


def test_geo_countries_multilingual_has_source_limits() -> None:
    """geo_countries_multilingual records its source-level row limits."""
    spec = DATASET_SPECS["geo_countries_multilingual"]
    assert spec.source_limits is not None
    assert "cldr" in spec.source_limits
    assert "geonames" in spec.source_limits
    assert "wikidata" in spec.source_limits


def test_buildable_datasets_have_build_fn() -> None:
    """Each spec either has a callable build_fn or documents why it has none.

    ``build_fn=None`` is allowed only for specs that are committed as eval sets
    (``notes``) or require an unavailable pack (``requires_pack``). Every other
    dataset must be rebuildable.
    """
    for name, spec in DATASET_SPECS.items():
        if spec.build_fn is None:
            assert spec.requires_pack is not None or spec.notes is not None, (
                f"DATASET_SPECS[{name!r}] has no build_fn and no documented "
                f"reason (set requires_pack or notes)"
            )
            continue
        assert callable(spec.build_fn), (
            f"DATASET_SPECS[{name!r}].build_fn is not callable"
        )


def test_build_dataset_unknown_name_raises_value_error() -> None:
    """build_dataset with an unrecognised name still raises ValueError."""
    with pytest.raises(ValueError, match="Unknown dataset"):
        build_dataset(name="nonexistent_v99")
