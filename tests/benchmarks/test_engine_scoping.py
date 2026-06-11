"""Tests for engine scoping: eval restriction, scoped accuracy, coverage, calibration gate."""

from __future__ import annotations

import pytest

from benchmarks.core.engine import _run_combo
from benchmarks.core.kernel import Query, Response
from benchmarks.core.toolspec import ToolSpec

# ---------------------------------------------------------------------------
# Stub adapters
# ---------------------------------------------------------------------------


class _CountryOnlyAdapter:
    """Offline adapter that supports country only, returning no_match always."""

    spec = ToolSpec(
        name="country_only_stub",
        distribution="stub",
        offline=True,
        entity_types=frozenset({"country"}),
        supports_calibration=False,
    )

    def warmup(self) -> None: ...

    def resolve(self, query: Query) -> Response:
        return Response(status="no_match")

    def version(self) -> str:
        return "0"


class _CalibrationAdapter:
    """Offline adapter that supports calibration and emits confidence."""

    spec = ToolSpec(
        name="calibration_stub",
        distribution="stub",
        offline=True,
        entity_types=frozenset({"country"}),
        supports_calibration=True,
    )

    def warmup(self) -> None: ...

    def resolve(self, query: Query) -> Response:
        return Response(status="match", match_ids=("country/USA",), confidence=0.9)

    def version(self) -> str:
        return "0"


class _CompetitorAdapter:
    """A non-resolvekit adapter used to test eval restriction."""

    spec = ToolSpec(
        name="competitor_stub",
        distribution="stub",
        offline=True,
        entity_types=frozenset({"country", "city"}),
        supports_calibration=False,
    )

    def warmup(self) -> None: ...

    def resolve(self, query: Query) -> Response:
        return Response(status="no_match")

    def version(self) -> str:
        return "0"


# ---------------------------------------------------------------------------
# Helper: build rows
# ---------------------------------------------------------------------------


def _make_row(
    *,
    entity_type: str,
    text: str = "France",
    expected: str = "country/FRA",
    query_id: str | None = None,
) -> Query:
    return Query(
        query_id=query_id or f"q-{entity_type}-{text}",
        text=text,
        expected_ids=(expected,),
        language="en",
        entity_type=entity_type,
        category="canonical",
        difficulty="easy",
        capabilities=(),
        source="synthetic",
        notes=None,
    )


# ---------------------------------------------------------------------------
# Scoped accuracy and coverage
# ---------------------------------------------------------------------------


def test_scoped_accuracy_country_only_on_mixed_dataset() -> None:
    """Country-only tool on a 2-country + 2-city dataset: coverage == 0.5."""
    rows = [
        _make_row(
            entity_type="country", text="France", expected="country/FRA", query_id="q1"
        ),
        _make_row(
            entity_type="country", text="Germany", expected="country/DEU", query_id="q2"
        ),
        _make_row(
            entity_type="city", text="Paris", expected="city/2988507", query_id="q3"
        ),
        _make_row(
            entity_type="city", text="Berlin", expected="city/2950159", query_id="q4"
        ),
    ]
    result = _run_combo(
        tool_name="country_only_stub",
        adapter_cls=_CountryOnlyAdapter,  # type: ignore[arg-type]
        dataset_name="ambiguous",
        rows=rows,
        warmup=0,
        seed=42,
        refresh_online_cache=False,
        measure_cold_start=False,
        profile_cache={},
    )
    assert result.metrics is not None
    # coverage = 2 country rows / 4 total rows
    assert result.coverage == pytest.approx(0.5)
    # accuracy is measured only over scoped (country) rows
    assert result.metrics.accuracy.row_count == 2


def test_scoped_accuracy_does_not_include_city_rows() -> None:
    """Accuracy.row_count equals number of scoped rows, not total dataset rows."""
    rows = [
        _make_row(entity_type="country", text="France", query_id="q1"),
        _make_row(entity_type="city", text="Paris", query_id="q2"),
        _make_row(entity_type="city", text="Lyon", query_id="q3"),
    ]
    result = _run_combo(
        tool_name="country_only_stub",
        adapter_cls=_CountryOnlyAdapter,  # type: ignore[arg-type]
        dataset_name="ambiguous",
        rows=rows,
        warmup=0,
        seed=42,
        refresh_online_cache=False,
        measure_cold_start=False,
        profile_cache={},
    )
    assert result.metrics is not None
    assert result.coverage == pytest.approx(1 / 3)
    assert result.metrics.accuracy.row_count == 1


# ---------------------------------------------------------------------------
# Measured latency count from scoped subset
# ---------------------------------------------------------------------------


def test_measured_latency_count_from_scoped_subset() -> None:
    """Small scoped subset of size k: measured count == k - k//5 (warmup fallback)."""
    # 5 country rows + many city rows → scoped k=5
    rows = [_make_row(entity_type="country", query_id=f"c{i}") for i in range(5)]
    rows += [_make_row(entity_type="city", query_id=f"city{i}") for i in range(20)]

    result = _run_combo(
        tool_name="country_only_stub",
        adapter_cls=_CountryOnlyAdapter,  # type: ignore[arg-type]
        dataset_name="ambiguous",
        rows=rows,
        warmup=100,  # warmup > len(scoped), so fallback triggers
        seed=42,
        refresh_online_cache=False,
        measure_cold_start=False,
        profile_cache={},
    )
    assert result.metrics is not None
    k = 5
    expected_warmup = k // 5  # fallback: len(scoped) // 5 = 1
    expected_measured = k - expected_warmup  # 5 - 1 = 4
    assert result.metrics.latency_ms.sample_count == expected_measured


# ---------------------------------------------------------------------------
# Eval restriction
# ---------------------------------------------------------------------------


def test_competitor_runs_on_eval_dataset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Competitors are no longer barred from eval datasets — they run, scoped to
    the entity types they support, so the eval tables show a per-type comparison."""
    from benchmarks.build import spec as spec_module
    from benchmarks.build.spec import DatasetSpec

    fake_spec = DatasetSpec(
        name="eval_geo",
        build_fn=None,
        eval=True,
    )
    monkeypatch.setitem(spec_module.DATASET_SPECS, "eval_geo", fake_spec)

    rows = [_make_row(entity_type="country")]
    result = _run_combo(
        tool_name="competitor_stub",
        adapter_cls=_CompetitorAdapter,  # type: ignore[arg-type]
        dataset_name="eval_geo",
        rows=rows,
        warmup=0,
        seed=42,
        refresh_online_cache=False,
        measure_cold_start=False,
        profile_cache={},
    )
    # Competitor supports "country", so it runs on the country row — not skipped.
    assert result.skipped_reason is None
    assert result.metrics is not None


def test_eval_restriction_allows_resolvekit(monkeypatch: pytest.MonkeyPatch) -> None:
    """resolvekit tool on eval=True dataset is NOT skipped by the eval gate."""
    from benchmarks.build import spec as spec_module
    from benchmarks.build.spec import DatasetSpec
    from benchmarks.tools.resolvekit import ResolvekitAdapter

    fake_spec = DatasetSpec(
        name="eval_geo",
        build_fn=None,
        eval=True,
    )
    monkeypatch.setitem(spec_module.DATASET_SPECS, "eval_geo", fake_spec)

    rows = [_make_row(entity_type="country")]
    # resolvekit must run on eval datasets (it is the system under test).
    # We only verify it doesn't return an eval skip reason (may skip for scope or import).
    result = _run_combo(
        tool_name="resolvekit",
        adapter_cls=ResolvekitAdapter,  # type: ignore[arg-type]
        dataset_name="eval_geo",
        rows=rows,
        warmup=0,
        seed=42,
        refresh_online_cache=False,
        measure_cold_start=False,
        profile_cache={},
    )
    if result.skipped_reason is not None:
        assert not result.skipped_reason.startswith("eval:")


# ---------------------------------------------------------------------------
# Calibration gate: supports_calibration flag
# ---------------------------------------------------------------------------


def test_calibration_present_when_supports_calibration_true() -> None:
    """Tool with supports_calibration=True gets calibration metrics."""
    rows = [_make_row(entity_type="country", query_id=f"q{i}") for i in range(30)]
    result = _run_combo(
        tool_name="calibration_stub",
        adapter_cls=_CalibrationAdapter,  # type: ignore[arg-type]
        dataset_name="ambiguous",
        rows=rows,
        warmup=0,
        seed=42,
        refresh_online_cache=False,
        measure_cold_start=False,
        profile_cache={},
    )
    assert result.metrics is not None
    assert result.metrics.calibration is not None


def test_calibration_absent_when_supports_calibration_false() -> None:
    """Tool with supports_calibration=False gets no calibration metrics."""
    rows = [_make_row(entity_type="country", query_id=f"q{i}") for i in range(30)]
    result = _run_combo(
        tool_name="country_only_stub",
        adapter_cls=_CountryOnlyAdapter,  # type: ignore[arg-type]
        dataset_name="ambiguous",
        rows=rows,
        warmup=0,
        seed=42,
        refresh_online_cache=False,
        measure_cold_start=False,
        profile_cache={},
    )
    assert result.metrics is not None
    assert result.metrics.calibration is None


# ---------------------------------------------------------------------------
# Coverage is None for skipped results
# ---------------------------------------------------------------------------


def test_coverage_none_for_scope_skipped() -> None:
    """Zero-overlap skip → coverage=None."""
    rows = [
        _make_row(entity_type="org")
    ]  # country_only supports {"country"}, not "org"
    result = _run_combo(
        tool_name="country_only_stub",
        adapter_cls=_CountryOnlyAdapter,  # type: ignore[arg-type]
        dataset_name="ambiguous",
        rows=rows,
        warmup=0,
        seed=42,
        refresh_online_cache=False,
        measure_cold_start=False,
        profile_cache={},
    )
    assert result.skipped_reason is not None
    assert result.skipped_reason.startswith("scope:")
    assert result.coverage is None
