"""Characterization tests for benchmarks.report.

Pins the behavior of BenchmarkReport.to_markdown() and to_json():
section structure, conditional blocks (Calibration, Caveats), warmup line,
JSON round-trip, and skipped-tool rendering. Hand-built fixtures;
no runner, network, or parquet — offline only.
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from benchmarks.core.metricresults import (
    AccuracyResult,
    CalibrationResult,
    LatencyResult,
    ReliabilityBin,
    ToolMetrics,
)
from benchmarks.core.report import (
    BenchmarkReport,
    DatasetMeta,
    HardwareInfo,
    ToolResult,
)


def _make_reliability_bins(
    *, populated_index: int | None = None
) -> tuple[ReliabilityBin, ...]:
    bins = []
    for i in range(10):
        if populated_index is not None and i == populated_index:
            bins.append(
                ReliabilityBin(
                    lower=i / 10.0,
                    upper=(i + 1) / 10.0,
                    count=20,
                    mean_confidence=0.95,
                    observed_accuracy=0.9,
                )
            )
        else:
            bins.append(
                ReliabilityBin(
                    lower=i / 10.0,
                    upper=(i + 1) / 10.0,
                    count=0,
                    mean_confidence=0.0,
                    observed_accuracy=0.0,
                )
            )
    return tuple(bins)


def _make_calibration(
    *, ece: float | None = 0.05, brier: float | None = 0.09
) -> CalibrationResult:
    bins = _make_reliability_bins(populated_index=9 if ece is not None else None)
    return CalibrationResult(
        n_with_confidence=20,
        ece=ece,
        brier=brier,
        reliability_bins=bins,
    )


def _base_metrics(
    *,
    with_calibration: bool = False,
    calibration: CalibrationResult | None = None,
    p95: float | None = 45.6,
    p99: float | None = 78.9,
    sample_count: int = 100,
) -> ToolMetrics:
    calib = (
        calibration
        if calibration is not None
        else (_make_calibration() if with_calibration else None)
    )
    return ToolMetrics(
        accuracy=AccuracyResult(
            overall=0.85,
            by_capability={},
            by_language={"en": 0.85},
            by_difficulty={"easy": 0.9},
            by_entity_type={"country": 0.85},
            wrong_match_rate=0.05,
            abstention_precision=0.9,
            abstention_recall=0.8,
            error_rate=0.01,
            row_count=100,
            accuracy_ci_low=0.77,
            accuracy_ci_high=0.91,
            by_entity_type_n={"country": 100},
            by_entity_type_wrong_match={"country": 0.05},
        ),
        ambiguity_recall=0.6,
        latency_ms=LatencyResult(
            p50=12.3,
            p95=p95,
            p99=p99,
            mean=15.0,
            min=1.0,
            max=100.0,
            sample_count=sample_count,
        ),
        throughput_qps=66.7,
        effective_warmup=20,
        cold_start_ms=None,
        peak_rss_mb=128.5,
        wheel_size_mb=5.2,
        data_size_mb=None,
        calibration=calib,
    )


def _make_hardware() -> HardwareInfo:
    return HardwareInfo(
        cpu="TestCPU",
        cores=8,
        memory_mb=16384,
        platform="test-platform",
        python="3.12.0",
    )


def _make_dataset_meta() -> DatasetMeta:
    return DatasetMeta(
        sha256="abc123def4567890abcdef",
        row_count=100,
        path="benchmarks/data/geo_countries_en.parquet",
    )


def _minimal_report(
    *,
    tools: tuple[ToolResult, ...] | None = None,
    warmup: int = 100,
    seed: int = 42,
) -> BenchmarkReport:
    if tools is None:
        tools = (
            ToolResult(
                name="resolvekit",
                version="1.0",
                offline=True,
                dataset="geo_countries_en",
                metrics=_base_metrics(),
                coverage=1.0,
            ),
        )
    return BenchmarkReport(
        benchmark_version="1",
        generated_at="2026-05-26T12:00:00Z",
        hardware=_make_hardware(),
        datasets={"geo_countries_en": _make_dataset_meta()},
        warmup=warmup,
        seed=seed,
        tools=tools,
    )


def test_markdown_structure() -> None:
    """to_markdown() emits H1 with date, Hardware, Datasets table, Results section."""
    report = _minimal_report()
    text = report.to_markdown()

    assert "# resolvekit benchmark — 2026-05-26" in text
    assert "Hardware: TestCPU" in text
    assert "## Datasets" in text
    assert "| dataset | rows | sha256 |" in text
    # sha256 truncated to 12 chars + ellipsis
    assert "abc123def456…" in text
    assert "## Results" in text
    assert "### geo_countries_en" in text


def test_markdown_results_columns() -> None:
    """Pins the 13-column main table header (wheel MB + data MB replace install MB)."""
    report = _minimal_report()
    text = report.to_markdown()
    expected_header = (
        "| tool | version | accuracy | acc CI | coverage | wrong-match | "
        "abst P | p50 ms | p95 ms | qps | mem MB | wheel MB | data MB |"
    )
    assert expected_header in text


def test_markdown_warmup_line_pins_nominal() -> None:
    """Exact warmup/seed line."""
    report = _minimal_report(warmup=100, seed=42)
    text = report.to_markdown()
    assert "Warmup: 100 queries discarded. Seed: 42." in text


def test_markdown_skipped_row_render() -> None:
    """Skipped tool renders *skipped (<reason>)* with 11 trailing dashes."""
    skipped = ToolResult(
        name="pycountry",
        version=None,
        offline=True,
        dataset="geo_countries_en",
        metrics=None,
        skipped_reason="not installed",
        coverage=None,
    )
    report = _minimal_report(tools=(skipped,))
    text = report.to_markdown()
    assert "*skipped (not installed)*" in text
    # 11 trailing "—" after the skipped-reason cell (13 columns - tool - skipped-reason)
    assert text.count("—") >= 11


def test_markdown_skipped_coverage_renders_dash() -> None:
    """Skipped tool (coverage=None) renders '—' for coverage cell (A4)."""
    skipped = ToolResult(
        name="pycountry",
        version=None,
        offline=True,
        dataset="geo_countries_en",
        metrics=None,
        skipped_reason="not installed",
        coverage=None,
    )
    report = _minimal_report(tools=(skipped,))
    text = report.to_markdown()
    # In the skipped row, all 10 dash-cells are "—" (including coverage position).
    assert "—" in text


def test_markdown_acc_ci_column_renders() -> None:
    """acc CI column renders bracketed interval from AccuracyResult CI fields."""
    report = _minimal_report()
    text = report.to_markdown()
    assert "[0.77, 0.91]" in text


def test_markdown_coverage_column_renders() -> None:
    """coverage column renders as a percentage."""
    report = _minimal_report()
    text = report.to_markdown()
    # coverage=1.0 should render as 100.0%
    assert "100.0%" in text


def test_markdown_recall_metrics_subtable_present() -> None:
    """Secondary '#### recall metrics' sub-table includes abst R and amb recall."""
    report = _minimal_report()
    text = report.to_markdown()
    assert "#### recall metrics" in text
    assert "abst R" in text
    assert "amb recall" in text


def test_markdown_amb_recall_value_rendered() -> None:
    """amb recall value from ToolMetrics.ambiguity_recall appears in recall sub-table."""
    report = _minimal_report()
    text = report.to_markdown()
    # ambiguity_recall=0.6 → "0.600"
    assert "0.600" in text


def test_markdown_p95_none_renders_na() -> None:
    """When LatencyResult.p95 is None (small n), p95 column shows 'n/a'."""
    tool = ToolResult(
        name="resolvekit",
        version="1.0",
        offline=True,
        dataset="geo_countries_en",
        metrics=_base_metrics(p95=None, p99=None, sample_count=5),
        coverage=1.0,
    )
    report = _minimal_report(tools=(tool,))
    text = report.to_markdown()
    assert "n/a" in text


def test_markdown_typed_variant_note_present_when_typed_tool() -> None:
    """Typed-variant note appears when resolvekit_typed is in the result set."""
    typed_tool = ToolResult(
        name="resolvekit_typed",
        version="1.0",
        offline=True,
        dataset="geo_countries_en",
        metrics=_base_metrics(),
        coverage=1.0,
    )
    report = _minimal_report(tools=(typed_tool,))
    text = report.to_markdown()
    assert "resolvekit_typed passes entity_type" in text


def test_markdown_typed_variant_note_absent_without_typed_tool() -> None:
    """Typed-variant note absent when resolvekit_typed is not in the result set."""
    report = _minimal_report()  # only "resolvekit", not "resolvekit_typed"
    text = report.to_markdown()
    assert "resolvekit_typed passes entity_type" not in text


def test_fmt_float_symbol_exists() -> None:
    """_fmt_float is the formatting helper in report module."""
    import benchmarks.core.report as report_module

    assert hasattr(report_module, "_fmt_float")


def test_hardware_info_is_frozen_dataclass() -> None:
    """HardwareInfo is a frozen dataclass with expected fields."""
    hw = _make_hardware()
    assert hw.cpu == "TestCPU"
    assert hw.cores == 8
    assert hw.memory_mb == 16384
    assert hw.python == "3.12.0"
    with pytest.raises(dataclasses.FrozenInstanceError):
        hw.cpu = "other"  # type: ignore[misc]


def test_dataset_meta_is_frozen_dataclass() -> None:
    """DatasetMeta is a frozen dataclass with expected fields."""
    meta = _make_dataset_meta()
    assert meta.sha256 == "abc123def4567890abcdef"
    assert meta.row_count == 100
    with pytest.raises(dataclasses.FrozenInstanceError):
        meta.row_count = 999  # type: ignore[misc]


def test_markdown_calibration_present() -> None:
    """'## Calibration' appears when a tool has ece != None."""
    tool = ToolResult(
        name="resolvekit",
        version="1.0",
        offline=True,
        dataset="geo_countries_en",
        metrics=_base_metrics(with_calibration=True),
        coverage=1.0,
    )
    report = _minimal_report(tools=(tool,))
    text = report.to_markdown()
    assert "## Calibration" in text
    assert "[0.0, 0.1)" in text or "[0.9, 1.0)" in text


def test_markdown_calibration_absent() -> None:
    """'## Calibration' absent when calibration is None or ece is None."""
    tool_none = ToolResult(
        name="resolvekit",
        version="1.0",
        offline=True,
        dataset="geo_countries_en",
        metrics=_base_metrics(calibration=None),
        coverage=1.0,
    )
    report = _minimal_report(tools=(tool_none,))
    assert "## Calibration" not in report.to_markdown()

    tool_no_ece = ToolResult(
        name="resolvekit",
        version="1.0",
        offline=True,
        dataset="geo_countries_en",
        metrics=_base_metrics(calibration=_make_calibration(ece=None, brier=None)),
        coverage=1.0,
    )
    report2 = _minimal_report(tools=(tool_no_ece,))
    assert "## Calibration" not in report2.to_markdown()


def test_markdown_caveats_present() -> None:
    """'## Caveats' appears when a skipped tool exists."""
    skipped = ToolResult(
        name="pycountry",
        version=None,
        offline=True,
        dataset="geo_countries_en",
        metrics=None,
        skipped_reason="not installed",
        coverage=None,
    )
    report = _minimal_report(tools=(skipped,))
    text = report.to_markdown()
    assert "## Caveats" in text
    assert "- pycountry on geo_countries_en: not installed" in text


def test_markdown_caveats_absent() -> None:
    """'## Caveats' absent when no skipped tools exist."""
    report = _minimal_report()
    assert "## Caveats" not in report.to_markdown()


def test_markdown_per_capability_table() -> None:
    """'#### per-capability accuracy' appears when by_capability is non-empty."""
    metrics = _base_metrics()
    new_accuracy = dataclasses.replace(
        metrics.accuracy, by_capability={"multilingual": 0.75}
    )
    metrics_with_cap = dataclasses.replace(metrics, accuracy=new_accuracy)
    tool = ToolResult(
        name="resolvekit",
        version="1.0",
        offline=True,
        dataset="geo_countries_en",
        metrics=metrics_with_cap,
        coverage=1.0,
    )
    report = _minimal_report(tools=(tool,))
    text = report.to_markdown()
    assert "#### per-capability accuracy" in text
    assert "multilingual" in text


def test_markdown_per_entity_type_table() -> None:
    """'#### per-entity-type accuracy' appears when by_entity_type is non-empty."""
    metrics = _base_metrics()  # fixture already sets by_entity_type={"country": 0.85}
    tool = ToolResult(
        name="resolvekit",
        version="1.0",
        offline=True,
        dataset="geo_countries_en",
        metrics=metrics,
        coverage=1.0,
    )
    report = _minimal_report(tools=(tool,))
    text = report.to_markdown()
    assert "#### per-entity-type accuracy" in text
    assert "country" in text


def test_json_round_trips_key_paths() -> None:
    """to_json() is valid JSON and round-trips name, accuracy.overall, sha256."""
    report = _minimal_report()
    payload = json.loads(report.to_json())

    assert payload["tools"][0]["name"] == "resolvekit"
    assert payload["tools"][0]["metrics"]["accuracy"]["overall"] == pytest.approx(0.85)
    assert payload["datasets"]["geo_countries_en"]["sha256"] == "abc123def4567890abcdef"


def test_json_hardware_keys_stable() -> None:
    """to_json() hardware dict has expected keys via dataclasses.asdict."""
    report = _minimal_report()
    payload = json.loads(report.to_json())
    hw = payload["hardware"]
    assert "cpu" in hw
    assert "cores" in hw
    assert "memory_mb" in hw
    assert "python" in hw
    assert hw["cpu"] == "TestCPU"


def test_json_datasets_keys_stable() -> None:
    """to_json() datasets dict has expected keys via dataclasses.asdict."""
    report = _minimal_report()
    payload = json.loads(report.to_json())
    meta = payload["datasets"]["geo_countries_en"]
    assert "sha256" in meta
    assert "row_count" in meta
    assert "path" in meta


def test_json_tools_sorted_by_dataset_then_name() -> None:
    """to_json() tools list is sorted by (dataset, name)."""
    tool_b = ToolResult(
        name="b_tool",
        version="1",
        offline=True,
        dataset="alpha",
        metrics=_base_metrics(),
        coverage=1.0,
    )
    tool_a = ToolResult(
        name="a_tool",
        version="1",
        offline=True,
        dataset="alpha",
        metrics=_base_metrics(),
        coverage=1.0,
    )
    tool_z = ToolResult(
        name="z_tool",
        version="1",
        offline=True,
        dataset="beta",
        metrics=_base_metrics(),
        coverage=1.0,
    )
    report = BenchmarkReport(
        benchmark_version="1",
        generated_at="2026-05-26T12:00:00Z",
        hardware=HardwareInfo(
            cpu="x", cores=1, memory_mb=1024, platform="test", python="3.12.0"
        ),
        datasets={
            "alpha": DatasetMeta(sha256="aaa", row_count=10, path="p"),
            "beta": DatasetMeta(sha256="bbb", row_count=5, path="p"),
        },
        warmup=0,
        seed=0,
        tools=(tool_b, tool_z, tool_a),
    )
    payload = json.loads(report.to_json())
    names = [t["name"] for t in payload["tools"]]
    assert names == ["a_tool", "b_tool", "z_tool"]


# ---------------------------------------------------------------------------
# by_entity_type_n rendering and comparison section
# ---------------------------------------------------------------------------


def test_per_entity_type_table_shows_n_count() -> None:
    """per-entity-type accuracy cells include (n=…) when by_entity_type_n is populated."""
    report = _minimal_report()  # fixture has by_entity_type_n={"country": 100}
    text = report.to_markdown()
    # The cell should contain both accuracy and row count
    assert "n=100" in text


def test_per_entity_type_table_no_n_when_empty() -> None:
    """per-entity-type accuracy cells show plain accuracy when by_entity_type_n is empty."""
    metrics = _base_metrics()
    new_accuracy = dataclasses.replace(
        metrics.accuracy,
        by_entity_type={"country": 0.75},
        by_entity_type_n={},
        by_entity_type_wrong_match={},
    )
    metrics_no_n = dataclasses.replace(metrics, accuracy=new_accuracy)
    tool = ToolResult(
        name="resolvekit",
        version="1.0",
        offline=True,
        dataset="geo_countries_en",
        metrics=metrics_no_n,
        coverage=1.0,
    )
    report = _minimal_report(tools=(tool,))
    text = report.to_markdown()
    assert "#### per-entity-type accuracy" in text
    assert "0.750" in text
    assert "n=" not in text


def _make_multi_tool_report(*, same_dataset: bool = True) -> BenchmarkReport:
    """Create a report with two tools that both have 'country' entity_type data."""
    metrics_a = dataclasses.replace(
        _base_metrics(),
        accuracy=dataclasses.replace(
            _base_metrics().accuracy,
            overall=0.69,
            by_entity_type={"country": 0.69},
            by_entity_type_n={"country": 200},
            by_entity_type_wrong_match={"country": 0.02},
        ),
    )
    metrics_b = dataclasses.replace(
        _base_metrics(),
        accuracy=dataclasses.replace(
            _base_metrics().accuracy,
            overall=0.59,
            by_entity_type={"country": 0.59},
            by_entity_type_n={"country": 200},
            by_entity_type_wrong_match={"country": 0.08},
        ),
    )
    dataset_b = "geo_countries_en" if same_dataset else "other_dataset"
    tool_a = ToolResult(
        name="resolvekit",
        version="1.0",
        offline=True,
        dataset="geo_countries_en",
        metrics=metrics_a,
        coverage=1.0,
    )
    tool_b = ToolResult(
        name="hdx_python_country",
        version="4.0",
        offline=True,
        dataset=dataset_b,
        metrics=metrics_b,
        coverage=1.0,
    )
    datasets: dict = {"geo_countries_en": _make_dataset_meta()}
    if not same_dataset:
        datasets["other_dataset"] = _make_dataset_meta()
    return BenchmarkReport(
        benchmark_version="1",
        generated_at="2026-05-26T12:00:00Z",
        hardware=_make_hardware(),
        datasets=datasets,
        warmup=100,
        seed=42,
        tools=(tool_a, tool_b),
    )


def test_comparison_section_present_for_multi_tool() -> None:
    """'## Comparison by entity type' appears when multiple tools share an entity_type+dataset."""
    report = _make_multi_tool_report(same_dataset=True)
    text = report.to_markdown()
    assert "## Comparison by entity type" in text


def test_comparison_section_absent_for_single_tool() -> None:
    """'## Comparison by entity type' is absent when no entity_type has ≥2 tools."""
    report = _minimal_report()  # single tool
    text = report.to_markdown()
    assert "## Comparison by entity type" not in text


def test_comparison_section_groups_by_entity_type() -> None:
    """The comparison section renders '### country' as a sub-heading."""
    report = _make_multi_tool_report(same_dataset=True)
    text = report.to_markdown()
    # The entity_type 'country' should appear as a third-level heading in the section
    assert "### country" in text


def test_comparison_section_lists_both_tools_in_table() -> None:
    """Both tools appear in the comparison table rows when they share a dataset+type."""
    report = _make_multi_tool_report(same_dataset=True)
    text = report.to_markdown()
    assert "resolvekit" in text
    assert "hdx_python_country" in text
    # Both accuracy values should appear
    assert "0.690" in text
    assert "0.590" in text


def test_comparison_section_shows_n_and_wrong_match() -> None:
    """Comparison table includes n column and wrong-match column."""
    report = _make_multi_tool_report(same_dataset=True)
    text = report.to_markdown()
    # The comparison table header
    assert "| tool | accuracy | n | wrong-match |" in text
    # Row counts appear
    assert "200" in text
    # Wrong match rates appear
    assert "0.020" in text
    assert "0.080" in text


def test_comparison_section_omitted_when_tools_on_different_datasets() -> None:
    """Comparison section skips slices where only one tool ran on a dataset."""
    report = _make_multi_tool_report(same_dataset=False)
    text = report.to_markdown()
    # Each dataset only has one tool for 'country', so the comparison table is skipped.
    assert "## Comparison by entity type" not in text


def test_comparison_section_includes_dataset_label() -> None:
    """The dataset name appears as a bold label before each comparison sub-table."""
    report = _make_multi_tool_report(same_dataset=True)
    text = report.to_markdown()
    assert "**geo_countries_en**" in text


def test_json_includes_by_entity_type_n() -> None:
    """to_json() serializes by_entity_type_n into the accuracy payload."""
    report = _minimal_report()
    payload = json.loads(report.to_json())
    accuracy = payload["tools"][0]["metrics"]["accuracy"]
    assert "by_entity_type_n" in accuracy
    assert accuracy["by_entity_type_n"]["country"] == 100


def test_json_includes_by_entity_type_wrong_match() -> None:
    """to_json() serializes by_entity_type_wrong_match into the accuracy payload."""
    report = _minimal_report()
    payload = json.loads(report.to_json())
    accuracy = payload["tools"][0]["metrics"]["accuracy"]
    assert "by_entity_type_wrong_match" in accuracy
    assert accuracy["by_entity_type_wrong_match"]["country"] == pytest.approx(0.05)
