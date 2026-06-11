"""Characterization tests for unit-testable skip/dispatch behaviors in benchmarks.runner.

Pins three behaviors without network, subprocess, or real parquet:
  1. _run_combo entity-type skip → ToolResult(skipped_reason="scope:...")
  2. _construct_adapter refresh=True dispatch for online adapters
  3. _load_datasets zero-row skip (datasets=None) vs. keep (datasets=[name])
  4. Scoped-row coverage assertion: partial-overlap dataset returns correct coverage
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.core.engine import _construct_adapter, _load_datasets, _run_combo
from benchmarks.core.kernel import Query, Response
from benchmarks.core.loader import DATASET_NAMES
from benchmarks.core.toolspec import ToolSpec

# ---------------------------------------------------------------------------
# Stub adapters
# ---------------------------------------------------------------------------


class _StubOfflineAdapter:
    """Minimal offline adapter that captures __init__ kwargs."""

    spec = ToolSpec(
        name="stub_offline",
        distribution="stub",
        offline=True,
        entity_types=frozenset({"country"}),
    )

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def warmup(self) -> None: ...

    def resolve(self, query: Query) -> Response:
        return Response(status="no_match")

    def version(self) -> str:
        return "0"


class _StubOnlineAdapter:
    """Minimal online adapter that captures __init__ kwargs."""

    spec = ToolSpec(
        name="stub_online",
        distribution="stub",
        offline=False,
        entity_types=frozenset({"country"}),
    )

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs

    def warmup(self) -> None: ...

    def resolve(self, query: Query) -> Response:
        return Response(status="no_match")

    def version(self) -> str:
        return "0"


class _WarmupFailsAdapter:
    """Online adapter whose warmup() raises, as a 403 from the DC instance does in CI."""

    spec = ToolSpec(
        name="warmup_fails",
        distribution="stub",
        offline=False,
        entity_types=frozenset({"country"}),
    )

    def __init__(self, **kwargs: object) -> None: ...

    def warmup(self) -> None:
        raise RuntimeError("403 Client Error: Forbidden")

    def resolve(self, query: Query) -> Response:
        return Response(status="no_match")

    def version(self) -> str:
        return "0"


def _make_row(*, entity_type: str = "country") -> Query:
    return Query(
        query_id="q",
        text="France",
        expected_ids=("country/FRA",),
        language="en",
        entity_type=entity_type,
        category="canonical",
        difficulty="easy",
        capabilities=(),
        source="synthetic",
        notes=None,
    )


# ---------------------------------------------------------------------------
# _run_combo entity-type skip
# ---------------------------------------------------------------------------


def test_run_combo_skips_on_entity_type_mismatch() -> None:
    """_run_combo returns skipped_reason starting 'scope:' when no entity type overlap."""
    rows = [_make_row(entity_type="org")]  # stub supports {"country"}, not "org"
    result = _run_combo(
        tool_name="stub_offline",
        adapter_cls=_StubOfflineAdapter,  # type: ignore[arg-type]
        dataset_name="geo_countries_en",
        rows=rows,
        warmup=0,
        seed=42,
        refresh_online_cache=False,
        measure_cold_start=False,
        profile_cache={},
    )
    assert result.skipped_reason is not None
    assert result.skipped_reason.startswith("scope:")
    assert result.metrics is None
    assert result.coverage is None


def test_run_combo_skips_when_warmup_fails() -> None:
    """A warmup failure (e.g. DC 403 in CI) skips the tool instead of aborting the run."""
    result = _run_combo(
        tool_name="warmup_fails",
        adapter_cls=_WarmupFailsAdapter,  # type: ignore[arg-type]
        dataset_name="geo_countries_en",
        rows=[_make_row()],
        warmup=0,
        seed=42,
        refresh_online_cache=False,
        measure_cold_start=False,
        profile_cache={},
    )
    assert result.skipped_reason is not None
    assert result.skipped_reason.startswith("warmup failed:")
    assert result.metrics is None


# ---------------------------------------------------------------------------
# _construct_adapter refresh dispatch
# ---------------------------------------------------------------------------


def test_construct_adapter_passes_refresh_when_online() -> None:
    """Online adapter + refresh_online_cache=True → constructed with refresh=True."""
    instance = _construct_adapter(
        adapter_cls=_StubOnlineAdapter,  # type: ignore[arg-type]
        refresh_online_cache=True,
    )
    assert isinstance(instance, _StubOnlineAdapter)
    assert instance.kwargs.get("refresh") is True


def test_construct_adapter_no_refresh_when_offline() -> None:
    """Offline adapter + refresh_online_cache=True → no refresh kwarg passed."""
    instance = _construct_adapter(
        adapter_cls=_StubOfflineAdapter,  # type: ignore[arg-type]
        refresh_online_cache=True,
    )
    assert isinstance(instance, _StubOfflineAdapter)
    assert "refresh" not in instance.kwargs


def test_construct_adapter_no_refresh_flag_off() -> None:
    """Online adapter + refresh_online_cache=False → no refresh kwarg passed."""
    instance = _construct_adapter(
        adapter_cls=_StubOnlineAdapter,  # type: ignore[arg-type]
        refresh_online_cache=False,
    )
    assert isinstance(instance, _StubOnlineAdapter)
    assert "refresh" not in instance.kwargs


# ---------------------------------------------------------------------------
# _load_datasets zero-row skip
# ---------------------------------------------------------------------------

# Use the first two known dataset names for the monkeypatch fixture.
_EMPTY_NAME = DATASET_NAMES[0]
_FULL_NAME = DATASET_NAMES[1]


def _stub_load_dataset(name: str, *, data_dir: Path | None = None) -> list[Query]:
    """Return zero rows for _EMPTY_NAME, one row for _FULL_NAME."""
    if name == _EMPTY_NAME:
        return []
    if name == _FULL_NAME:
        return [_make_row()]
    return []


def _stub_sha256(path: Path) -> str:
    return "deadbeef"


def test_load_datasets_skips_zero_row_on_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """datasets=None → empty-row dataset is dropped from result."""
    monkeypatch.setattr("benchmarks.core.engine.load_dataset", _stub_load_dataset)
    monkeypatch.setattr("benchmarks.core.engine._sha256_file", _stub_sha256)

    # Create stub parquet files so _sha256_file can resolve a path
    (tmp_path / f"{_EMPTY_NAME}.parquet").touch()
    (tmp_path / f"{_FULL_NAME}.parquet").touch()

    result = _load_datasets(None, data_dir=tmp_path)

    assert _EMPTY_NAME not in result
    assert _FULL_NAME in result
    assert result[_FULL_NAME]["row_count"] == 1


def test_load_datasets_keeps_zero_row_when_explicit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """datasets=[empty_name] → zero-row dataset kept (explicit request)."""
    monkeypatch.setattr("benchmarks.core.engine.load_dataset", _stub_load_dataset)
    monkeypatch.setattr("benchmarks.core.engine._sha256_file", _stub_sha256)

    (tmp_path / f"{_EMPTY_NAME}.parquet").touch()

    result = _load_datasets([_EMPTY_NAME], data_dir=tmp_path)

    assert _EMPTY_NAME in result
    assert result[_EMPTY_NAME]["row_count"] == 0


# ---------------------------------------------------------------------------
# Scoped-row coverage assertion
# ---------------------------------------------------------------------------


def test_run_combo_coverage_partial_overlap() -> None:
    """Country-only tool on 1-country + 1-city dataset: coverage==0.5, row_count==1."""
    rows = [
        _make_row(entity_type="country"),
        _make_row(entity_type="city"),
    ]
    result = _run_combo(
        tool_name="stub_offline",
        adapter_cls=_StubOfflineAdapter,  # type: ignore[arg-type]
        dataset_name="geo_countries_en",
        rows=rows,
        warmup=0,
        seed=42,
        refresh_online_cache=False,
        measure_cold_start=False,
        profile_cache={},
    )
    assert result.metrics is not None
    assert result.coverage == pytest.approx(0.5)
    assert result.metrics.accuracy.row_count == 1


def test_run_combo_coverage_full_overlap() -> None:
    """All-country dataset with country-only tool: coverage==1.0."""
    rows = [_make_row(entity_type="country") for _ in range(5)]
    result = _run_combo(
        tool_name="stub_offline",
        adapter_cls=_StubOfflineAdapter,  # type: ignore[arg-type]
        dataset_name="geo_countries_en",
        rows=rows,
        warmup=0,
        seed=42,
        refresh_online_cache=False,
        measure_cold_start=False,
        profile_cache={},
    )
    assert result.metrics is not None
    assert result.coverage == pytest.approx(1.0)
