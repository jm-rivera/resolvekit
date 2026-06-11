"""Benchmark report structures and renderers.

A BenchmarkReport is the single object a run produces. It can be
written to JSON (stable, diffable) or rendered as Markdown.
"""

from __future__ import annotations

import dataclasses
import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from benchmarks.core.metricresults import ToolMetrics


@dataclass(frozen=True)
class HardwareInfo:
    """System hardware description captured at run time."""

    cpu: str
    cores: int | None
    memory_mb: int | None
    platform: str
    python: str


@dataclass(frozen=True)
class DatasetMeta:
    """Per-dataset provenance recorded in a report."""

    sha256: str
    row_count: int
    path: str


@dataclass(frozen=True)
class ToolResult:
    name: str
    version: str | None
    offline: bool
    dataset: str
    metrics: ToolMetrics | None  # None for skipped tools
    skipped_reason: str | None = None
    # Fraction of dataset rows this tool attempted (scoped to entity_types).
    # None for skipped results (zero-overlap or eval-restricted).
    coverage: float | None = None


@dataclass(frozen=True)
class BenchmarkReport:
    benchmark_version: str
    generated_at: str
    hardware: HardwareInfo
    datasets: dict[str, DatasetMeta]
    warmup: int
    seed: int
    tools: tuple[ToolResult, ...]

    def to_json(self, *, path: Path | None = None) -> str:
        # Sort tools, then asdict each ToolResult (recurses into ToolMetrics tree).
        # Outer payload keys are listed explicitly to preserve insertion order.
        sorted_tools = sorted(self.tools, key=lambda t: (t.dataset, t.name))
        payload: dict = {
            "benchmark_version": self.benchmark_version,
            "generated_at": self.generated_at,
            "hardware": dataclasses.asdict(self.hardware),
            "warmup": self.warmup,
            "seed": self.seed,
            "datasets": {k: dataclasses.asdict(v) for k, v in self.datasets.items()},
            "tools": [dataclasses.asdict(tool) for tool in sorted_tools],
        }
        text = json.dumps(payload, indent=2, sort_keys=False) + "\n"
        if path is not None:
            path.write_text(text, encoding="utf-8")
        return text

    def to_markdown(self, *, path: Path | None = None) -> str:
        lines: list[str] = []
        date = self.generated_at.split("T", 1)[0] if self.generated_at else ""
        lines.append(f"# resolvekit benchmark — {date}")
        lines.append("")

        cpu = self.hardware.cpu
        cores = self.hardware.cores
        memory_mb = self.hardware.memory_mb
        python = self.hardware.python
        mem_str = _fmt_int(memory_mb) if memory_mb is not None else "—"
        lines.append(
            f"Hardware: {cpu}, {cores} cores, {mem_str} MB RAM, Python {python}."
        )
        lines.append(f"Warmup: {self.warmup} queries discarded. Seed: {self.seed}.")
        lines.append("")

        lines.append("## Datasets")
        lines.append("")
        lines.append("| dataset | rows | sha256 |")
        lines.append("|---|---|---|")
        for name in sorted(self.datasets):
            meta = self.datasets[name]
            sha_short = (
                (meta.sha256[:12] + "…") if len(meta.sha256) > 12 else meta.sha256
            )
            lines.append(f"| {name} | {_fmt_int(meta.row_count)} | {sha_short} |")
        lines.append("")

        lines.append("## Results")
        lines.append("")

        by_dataset: dict[str, list[ToolResult]] = defaultdict(list)
        for tool in self.tools:
            by_dataset[tool.dataset].append(tool)

        has_typed = any(t.name == "resolvekit_typed" for t in self.tools)

        for dataset_name in sorted(by_dataset):
            tools = sorted(by_dataset[dataset_name], key=lambda t: t.name)
            lines.append(f"### {dataset_name}")
            lines.append("")

            if has_typed and any(t.name == "resolvekit_typed" for t in tools):
                lines.append(
                    "_resolvekit_typed passes entity_type + language hints from the "
                    "dataset; scores reflect a caller with structured input available._"
                )
                lines.append("")

            # Main table: tool, version, accuracy, acc CI, coverage, wrong-match,
            # abst P, p50, p95, qps, mem, wheel MB, data MB.
            # Throughput and latency percentiles are measured over scoped rows only.
            # wheel MB — installed wheel files (via importlib.metadata).
            # data MB  — separately downloaded data packs (remote distribution);
            #            — for tools whose data ships inside the wheel.
            lines.append(
                "| tool | version | accuracy | acc CI | coverage | wrong-match | "
                "abst P | p50 ms | p95 ms | qps | mem MB | wheel MB | data MB |"
            )
            lines.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
            skipped: list[ToolResult] = []
            for tool in tools:
                if tool.metrics is None:
                    skipped.append(tool)
                    continue
                m = tool.metrics
                version = tool.version or "—"
                accuracy = _fmt_rate(m.accuracy.overall)
                ci_low = m.accuracy.accuracy_ci_low
                ci_high = m.accuracy.accuracy_ci_high
                if ci_low is not None and ci_high is not None:
                    acc_ci = f"[{ci_low:.2f}, {ci_high:.2f}]"
                else:
                    acc_ci = "—"
                coverage = _fmt_coverage(tool.coverage)
                wrong = _fmt_rate(m.accuracy.wrong_match_rate)
                absten = _fmt_rate(m.accuracy.abstention_precision)
                p50 = _fmt_float(m.latency_ms.p50)
                p95 = (
                    _fmt_float(m.latency_ms.p95)
                    if m.latency_ms.p95 is not None
                    else "n/a"
                )
                qps = _fmt_float(m.throughput_qps)
                mem = _fmt_float(m.peak_rss_mb)
                wheel = _fmt_float(m.wheel_size_mb)
                data = _fmt_float(m.data_size_mb)
                lines.append(
                    f"| {tool.name} | {version} | {accuracy} | {acc_ci} | {coverage} | "
                    f"{wrong} | {absten} | {p50} | {p95} | {qps} | {mem} | {wheel} | {data} |"
                )
            for tool in skipped:
                dashes = " | ".join(["—"] * 11)
                lines.append(
                    f"| {tool.name} | *skipped ({tool.skipped_reason})* | {dashes} |"
                )
            lines.append("")

            # Secondary sub-table: amb recall + abst R.
            tools_with_metrics = [t for t in tools if t.metrics is not None]
            if tools_with_metrics:
                lines.append("#### recall metrics")
                lines.append("")
                lines.append("| tool | abst R | amb recall |")
                lines.append("|---|---|---|")
                for tool in tools_with_metrics:
                    m = tool.metrics  # type: ignore[union-attr]
                    abst_r = _fmt_rate(m.accuracy.abstention_recall)
                    amb_r = _fmt_rate(m.ambiguity_recall)
                    lines.append(f"| {tool.name} | {abst_r} | {amb_r} |")
                lines.append("")

            capability_tags = _collect_capability_tags(tools)
            if capability_tags:
                header = "| tool | " + " | ".join(capability_tags) + " |"
                sep = "|---|" + "|".join(["---"] * len(capability_tags)) + "|"
                lines.append("#### per-capability accuracy")
                lines.append("")
                lines.append(header)
                lines.append(sep)
                for tool in tools:
                    if tool.metrics is None:
                        continue
                    by_cap = tool.metrics.accuracy.by_capability
                    cells = [_fmt_rate(by_cap.get(tag)) for tag in capability_tags]
                    lines.append(f"| {tool.name} | " + " | ".join(cells) + " |")
                lines.append("")

            entity_type_tags = _collect_entity_type_tags(tools)
            if entity_type_tags:
                header = "| tool | " + " | ".join(entity_type_tags) + " |"
                sep = "|---|" + "|".join(["---"] * len(entity_type_tags)) + "|"
                lines.append("#### per-entity-type accuracy")
                lines.append("")
                lines.append(header)
                lines.append(sep)
                for tool in tools:
                    if tool.metrics is None:
                        continue
                    by_type = tool.metrics.accuracy.by_entity_type
                    by_type_n = tool.metrics.accuracy.by_entity_type_n
                    cells = []
                    for tag in entity_type_tags:
                        acc = by_type.get(tag)
                        n = by_type_n.get(tag)
                        if acc is None:
                            cells.append("—")
                        elif n is not None:
                            cells.append(f"{acc:.3f} (n={n:,})")
                        else:
                            cells.append(f"{acc:.3f}")
                    lines.append(f"| {tool.name} | " + " | ".join(cells) + " |")
                lines.append("")

        _render_entity_type_comparison(self.tools, lines)

        calibrated = [
            tool
            for tool in self.tools
            if tool.metrics is not None
            and tool.metrics.calibration is not None
            and tool.metrics.calibration.ece is not None
        ]
        if calibrated:
            lines.append("## Calibration")
            lines.append("")
            for tool in sorted(calibrated, key=lambda t: (t.name, t.dataset)):
                calib = tool.metrics.calibration  # type: ignore[union-attr]
                ece = _fmt_rate(calib.ece)
                brier = _fmt_rate(calib.brier)
                lines.append(f"### {tool.name} on {tool.dataset}")
                lines.append("")
                lines.append(f"ECE: {ece}. Brier: {brier}. Reliability diagram data:")
                lines.append("")
                lines.append("| bin | count | mean conf | observed acc |")
                lines.append("|---|---|---|---|")
                for entry in calib.reliability_bins:
                    mean_conf = _fmt_rate(entry.mean_confidence)
                    obs_acc = _fmt_rate(entry.observed_accuracy)
                    lines.append(
                        f"| [{entry.lower:.1f}, {entry.upper:.1f}) | "
                        f"{_fmt_int(entry.count)} | {mean_conf} | {obs_acc} |"
                    )
                lines.append("")

        caveats = [tool for tool in self.tools if tool.skipped_reason]
        if caveats:
            lines.append("## Caveats")
            lines.append("")
            for tool in sorted(caveats, key=lambda t: (t.dataset, t.name)):
                lines.append(f"- {tool.name} on {tool.dataset}: {tool.skipped_reason}")
            lines.append("")

        text = "\n".join(lines).rstrip("\n") + "\n"
        if path is not None:
            path.write_text(text, encoding="utf-8")
        return text


def _fmt_rate(value: object) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.3f}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "—"


def _fmt_float(value: object) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.1f}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return "—"


def _fmt_coverage(value: float | None) -> str:
    """Render a coverage fraction [0,1] as a percentage string, or '—' for None."""
    if value is None:
        return "—"
    return f"{value:.1%}"


def _fmt_int(value: object) -> str:
    if value is None:
        return "—"
    try:
        return f"{int(value):,}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)


def _collect_capability_tags(tools: list[ToolResult]) -> list[str]:
    tags: set[str] = set()
    for tool in tools:
        if tool.metrics is None:
            continue
        tags.update(tool.metrics.accuracy.by_capability.keys())
    return sorted(tags)


def _collect_entity_type_tags(tools: list[ToolResult]) -> list[str]:
    tags: set[str] = set()
    for tool in tools:
        if tool.metrics is None:
            continue
        tags.update(tool.metrics.accuracy.by_entity_type.keys())
    return sorted(tags)


def _render_entity_type_comparison(
    tools: tuple[ToolResult, ...], lines: list[str]
) -> None:
    """Append a '## Comparison by entity type' section to *lines*.

    For each entity_type observed across all tools, renders one sub-table
    per dataset that has data for that type. Each sub-table rows are tools,
    columns are: tool, accuracy, n, wrong-match.

    Comparisons are scoped per dataset so they are genuinely like-for-like
    (same rows). Cross-dataset roll-ups are intentionally omitted — different
    datasets have different difficulty profiles and aggregating them would be
    misleading.
    """
    # Collect all (entity_type, dataset) pairs that have at least one tool.
    # Structure: entity_type -> dataset -> list[ToolResult]
    by_type: dict[str, dict[str, list[ToolResult]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for tool in tools:
        if tool.metrics is None:
            continue
        for etype in tool.metrics.accuracy.by_entity_type:
            by_type[etype][tool.dataset].append(tool)

    if not by_type:
        return

    # Check whether at least one (entity_type, dataset) slice has ≥ 2 tools.
    # If every slice has only one tool, the section adds no value.
    has_any_comparison = any(
        len(tools_in_dataset) >= 2
        for datasets_for_type in by_type.values()
        for tools_in_dataset in datasets_for_type.values()
    )
    if not has_any_comparison:
        return

    lines.append("## Comparison by entity type")
    lines.append("")
    lines.append(
        "Each sub-table is scoped to a single dataset so comparisons are like-for-like. "
        "Cross-dataset roll-ups are omitted — datasets differ in difficulty."
    )
    lines.append("")

    for etype in sorted(by_type):
        etype_lines: list[str] = []
        datasets_for_type = by_type[etype]
        for dataset_name in sorted(datasets_for_type):
            tools_for_slice = sorted(
                datasets_for_type[dataset_name], key=lambda t: t.name
            )
            # Skip slices with only one tool (nothing to compare).
            if len(tools_for_slice) < 2:
                continue
            etype_lines.append(f"**{dataset_name}**")
            etype_lines.append("")
            etype_lines.append("| tool | accuracy | n | wrong-match |")
            etype_lines.append("|---|---|---|---|")
            for tool in tools_for_slice:
                m = tool.metrics
                if m is None:
                    continue
                acc = m.accuracy.by_entity_type.get(etype)
                n = m.accuracy.by_entity_type_n.get(etype)
                wm = m.accuracy.by_entity_type_wrong_match.get(etype)
                acc_str = _fmt_rate(acc)
                n_str = _fmt_int(n) if n is not None else "—"
                wm_str = _fmt_rate(wm)
                etype_lines.append(f"| {tool.name} | {acc_str} | {n_str} | {wm_str} |")
            etype_lines.append("")
        if etype_lines:
            lines.append(f"### {etype}")
            lines.append("")
            lines.extend(etype_lines)
