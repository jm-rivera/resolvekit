"""Per-(tool, dataset) metric computation.

All metrics operate on a list of Observation objects. They return typed
dataclasses from ``benchmarks.core.metricresults``; ``dataclasses.asdict``
on those results reproduces the dict structure byte-for-byte.
"""

from __future__ import annotations

import fnmatch
import importlib.metadata
import importlib.util
import json
import math
from collections import defaultdict
from pathlib import Path

from benchmarks.core._math import percentile
from benchmarks.core.kernel import Observation, Query, Response
from benchmarks.core.metricresults import (
    AccuracyResult,
    CalibrationResult,
    LatencyResult,
    ReliabilityBin,
)


def _wilson_interval(*, successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score 95% CI (z=1.96) for a proportion.

    Returns (low, high) clamped to [0, 1].
    """
    phat = successes / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = (z / denom) * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    low = max(0.0, centre - half)
    high = min(1.0, centre + half)
    return low, high


def is_row_correct(query: Query, response: Response) -> bool:
    if response.status == "error":
        return False
    expected = set(query.expected_ids)
    if not expected:
        return response.status == "no_match"
    return bool(expected & set(response.match_ids))


_STRATUM_KEYS = ("capability", "language", "difficulty", "entity_type")


def accuracy_metrics(*, observations: list[Observation]) -> AccuracyResult:
    total = len(observations)
    strata: dict[str, dict[str, list[int]]] = {
        key: defaultdict(lambda: [0, 0]) for key in _STRATUM_KEYS
    }
    if total == 0:
        return AccuracyResult(
            overall=0.0,
            by_capability={},
            by_language={},
            by_difficulty={},
            by_entity_type={},
            wrong_match_rate=0.0,
            abstention_precision=0.0,
            abstention_recall=0.0,
            error_rate=0.0,
            row_count=0,
            accuracy_ci_low=None,
            accuracy_ci_high=None,
            by_entity_type_n={},
            by_entity_type_wrong_match={},
        )

    correct_total = 0
    wrong_match = 0
    error_count = 0
    abstention_said = 0
    abstention_said_correct = 0
    abstention_should = 0
    abstention_should_correct = 0
    # Per entity_type wrong-match accumulator: [wrong_match_count, total_rows]
    entity_type_wrong_match: dict[str, list[int]] = defaultdict(lambda: [0, 0])

    for obs in observations:
        query, response = obs.query, obs.response
        correct = is_row_correct(query, response)
        correct_int = int(correct)
        if correct:
            correct_total += 1
        if response.status == "error":
            error_count += 1
        is_wrong_match = False
        if response.status == "match":
            expected = set(query.expected_ids)
            if not expected or not (expected & set(response.match_ids)):
                wrong_match += 1
                is_wrong_match = True
        if response.status == "no_match":
            abstention_said += 1
            if not query.expected_ids:
                abstention_said_correct += 1
        if not query.expected_ids:
            abstention_should += 1
            if response.status == "no_match":
                abstention_should_correct += 1

        for tag in query.capabilities:
            bucket = strata["capability"][tag]
            bucket[0] += correct_int
            bucket[1] += 1
        for stratum, key in (
            ("language", query.language),
            ("difficulty", query.difficulty),
            ("entity_type", query.entity_type),
        ):
            bucket = strata[stratum][key]
            bucket[0] += correct_int
            bucket[1] += 1

        wm_bucket = entity_type_wrong_match[query.entity_type]
        wm_bucket[0] += int(is_wrong_match)
        wm_bucket[1] += 1

    def _ratio_map(source: dict[str, list[int]]) -> dict[str, float]:
        return {key: (num / denom) for key, (num, denom) in source.items() if denom > 0}

    by_entity_type_n = {
        key: denom for key, (_, denom) in strata["entity_type"].items() if denom > 0
    }
    by_entity_type_wrong_match = {
        key: (wm / n) for key, (wm, n) in entity_type_wrong_match.items() if n > 0
    }

    ci_low, ci_high = _wilson_interval(successes=correct_total, n=total)
    return AccuracyResult(
        overall=correct_total / total,
        by_capability=_ratio_map(strata["capability"]),
        by_language=_ratio_map(strata["language"]),
        by_difficulty=_ratio_map(strata["difficulty"]),
        by_entity_type=_ratio_map(strata["entity_type"]),
        wrong_match_rate=wrong_match / total,
        abstention_precision=(
            abstention_said_correct / abstention_said if abstention_said else 0.0
        ),
        abstention_recall=(
            abstention_should_correct / abstention_should if abstention_should else 0.0
        ),
        error_rate=error_count / total,
        row_count=total,
        accuracy_ci_low=ci_low,
        accuracy_ci_high=ci_high,
        by_entity_type_n=by_entity_type_n,
        by_entity_type_wrong_match=by_entity_type_wrong_match,
    )


def ambiguity_recall(*, observations: list[Observation]) -> float:
    ambiguous = [obs for obs in observations if len(obs.query.expected_ids) >= 2]
    if not ambiguous:
        return 0.0
    hits = sum(
        1
        for obs in ambiguous
        if bool(set(obs.query.expected_ids) & set(obs.response.match_ids))
    )
    return hits / len(ambiguous)


def latency_metrics(*, latencies_ms: list[float]) -> LatencyResult:
    n = len(latencies_ms)
    if not latencies_ms:
        return LatencyResult(
            p50=0.0, p95=None, p99=None, mean=0.0, min=0.0, max=0.0, sample_count=0
        )
    p95 = percentile(latencies_ms, 95) if n >= 20 else None
    p99 = percentile(latencies_ms, 99) if n >= 20 else None
    return LatencyResult(
        p50=percentile(latencies_ms, 50),
        p95=p95,
        p99=p99,
        mean=sum(latencies_ms) / n,
        min=min(latencies_ms),
        max=max(latencies_ms),
        sample_count=n,
    )


def calibration_metrics(*, observations: list[Observation]) -> CalibrationResult:
    with_conf = [obs for obs in observations if obs.response.confidence is not None]
    n = len(with_conf)

    bin_edges = [(i / 10.0, (i + 1) / 10.0) for i in range(10)]
    # Mutable bin accumulators; converted to ReliabilityBin at the end.
    lower_vals = [lower for lower, _ in bin_edges]
    upper_vals = [upper for _, upper in bin_edges]
    conf_sums = [0.0] * 10
    correct_sums = [0.0] * 10
    counts = [0] * 10

    if n == 0:
        bins = tuple(
            ReliabilityBin(
                lower=lower_vals[i],
                upper=upper_vals[i],
                count=0,
                mean_confidence=0.0,
                observed_accuracy=0.0,
            )
            for i in range(10)
        )
        return CalibrationResult(
            n_with_confidence=0,
            ece=None,
            brier=None,
            reliability_bins=bins,
        )

    brier_sum = 0.0

    for obs in with_conf:
        query, response = obs.query, obs.response
        confidence = float(response.confidence or 0.0)
        confidence_clamped = max(0.0, min(1.0, confidence))
        correct = 1.0 if is_row_correct(query, response) else 0.0
        brier_sum += (confidence_clamped - correct) ** 2
        index = min(int(confidence_clamped * 10), 9)
        conf_sums[index] += confidence_clamped
        correct_sums[index] += correct
        counts[index] += 1

    bins = tuple(
        ReliabilityBin(
            lower=lower_vals[i],
            upper=upper_vals[i],
            count=counts[i],
            mean_confidence=conf_sums[i] / counts[i] if counts[i] > 0 else 0.0,
            observed_accuracy=correct_sums[i] / counts[i] if counts[i] > 0 else 0.0,
        )
        for i in range(10)
    )

    if n < 20:
        return CalibrationResult(
            n_with_confidence=n,
            ece=None,
            brier=None,
            reliability_bins=bins,
        )

    ece = 0.0
    for idx, count in enumerate(counts):
        if count == 0:
            continue
        mean_conf = conf_sums[idx] / count
        obs_acc = correct_sums[idx] / count
        ece += (count / n) * abs(mean_conf - obs_acc)

    return CalibrationResult(
        n_with_confidence=n,
        ece=ece,
        brier=brier_sum / n,
        reliability_bins=bins,
    )


def throughput_qps(*, latencies_ms: list[float], wall_elapsed_seconds: float) -> float:
    if wall_elapsed_seconds <= 0:
        return 0.0
    return len(latencies_ms) / wall_elapsed_seconds


def _is_editable_install(dist: importlib.metadata.Distribution) -> bool:
    """Return True when *dist* is installed in editable (development) mode.

    Checks the PEP 610 ``direct_url.json`` marker first; falls back to
    detecting a ``.pth`` stub in the recorded files list (the pattern used by
    uv and pip for editable installs).
    """
    direct_url_text = dist.read_text("direct_url.json")
    if direct_url_text:
        try:
            direct_url = json.loads(direct_url_text)
            if direct_url.get("dir_info", {}).get("editable") is True:
                return True
        except (ValueError, KeyError):
            pass
    for f in dist.files or []:
        name = str(f)
        if "__editable__" in name or name.endswith(".pth"):
            return True
    return False


def _wheel_size_mb_from_pkg_dir(pkg_dir: Path, dist_name: str) -> float | None:
    """Compute wheel footprint by walking *pkg_dir* and applying wheel-exclude rules.

    Used as an editable-install fallback when ``importlib.metadata`` only returns
    the stub files.  The function reads ``{pkg_dir}/_data/manifest.json`` (if
    present) to identify which data sub-directories are "remote" (downloaded at
    runtime and excluded from the wheel), then sums every file that would ship
    inside the built wheel.

    Excluded from the count:
    - ``__pycache__`` trees
    - Build-provenance files: ``changelog.md``, ``diff_*.json``, ``qa_report.json``,
      ``reports/`` trees, ``*.sqlite.gz``, ``*.dict.gz``
    - ``entities.sqlite`` and ``symspell.dict`` inside *remote* module directories
      (those files are downloaded on first use and are not part of the wheel)
    """
    data_dir = pkg_dir / "_data"
    remote_dirs: set[Path] = set()
    if data_dir.is_dir():
        manifest_path = data_dir / "manifest.json"
        if manifest_path.is_file():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                for module in manifest.get("modules", []):
                    if module.get("distribution") == "remote":
                        module_id: str = module.get("module_id", "")
                        if module_id:
                            parts = module_id.split(".")
                            remote_dirs.add(data_dir.joinpath(*parts))
            except (ValueError, KeyError):
                pass

    def _excluded(path: Path) -> bool:
        if "__pycache__" in path.parts:
            return True
        if not str(path).startswith(str(data_dir)):
            return False
        name = path.name
        is_provenance = (
            name in ("changelog.md", "qa_report.json")
            or fnmatch.fnmatch(name, "diff_*.json")
            or "reports" in path.parts
            or name.endswith((".sqlite.gz", ".dict.gz"))
        )
        is_remote_data = name in ("entities.sqlite", "symspell.dict") and any(
            str(path).startswith(str(rdir)) for rdir in remote_dirs
        )
        return is_provenance or is_remote_data

    total = 0
    for f in pkg_dir.rglob("*"):
        if not f.is_file():
            continue
        if _excluded(f):
            continue
        try:
            total += f.stat().st_size
        except OSError:
            continue
    if total == 0:
        return None
    return total / (1024 * 1024)


def wheel_size_mb(*, dist_name: str) -> float | None:
    """Return the on-disk size (in MB) of the installed wheel files for *dist_name*.

    For regular installs, uses ``importlib.metadata`` to locate each file
    recorded in the distribution and sums their ``stat().st_size`` values.

    For editable installs (e.g. a dev checkout), ``importlib.metadata`` only
    returns the tiny ``.pth`` stub, not the real package files.  In that case
    the function falls back to walking the package directory directly, applying
    the same exclusion rules as the wheel build configuration: build-provenance
    files, compressed artifacts, and data files for remote-distribution modules
    (those downloaded on first use) are excluded.  Bundled data files that ship
    inside the wheel are included.

    Returns ``None`` when the distribution is not installed or has no recorded files.
    """
    if not dist_name:
        return None
    try:
        dist = importlib.metadata.distribution(dist_name)
    except importlib.metadata.PackageNotFoundError:
        return None

    if _is_editable_install(dist):
        spec = importlib.util.find_spec(dist_name)
        if spec and spec.submodule_search_locations:
            pkg_dir = Path(spec.submodule_search_locations[0])
            return _wheel_size_mb_from_pkg_dir(pkg_dir, dist_name)
        return None

    return _installed_dist_size_mb(dist)


def _installed_dist_size_mb(dist: importlib.metadata.Distribution) -> float | None:
    """Sum the on-disk size (in MB) of every file recorded for a regular install."""
    total = 0
    for entry in dist.files or []:
        try:
            total += Path(str(dist.locate_file(entry))).stat().st_size
        except OSError:
            continue
    if total == 0:
        return None
    return total / (1024 * 1024)


# Back-compat alias used by engine.py fallback path (no-cold-start mode).
install_size_mb = wheel_size_mb


def data_size_mb_from_manifest(*, manifest_path: Path) -> float | None:
    """Sum ``size_mb`` for all *remote*-distribution modules in a resolvekit manifest.

    Remote modules are downloaded on first use and stored outside the wheel, so
    their footprint is not captured by ``wheel_size_mb``.  Bundled modules ship
    inside the wheel and are already counted there.

    Returns ``None`` when the manifest file cannot be read or contains no remote
    entries.
    """
    try:
        import json

        text = manifest_path.read_text(encoding="utf-8")
        manifest = json.loads(text)
    except (OSError, ValueError):
        return None
    total = 0.0
    found_any = False
    for module in manifest.get("modules", []):
        if module.get("distribution") == "remote":
            size = module.get("size_mb")
            if isinstance(size, (int, float)):
                total += float(size)
                found_any = True
    return total if found_any else None
