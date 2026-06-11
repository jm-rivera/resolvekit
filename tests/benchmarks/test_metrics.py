"""Characterization tests for benchmarks.metrics.

Pins the current observable behavior of: is_row_correct, accuracy_metrics,
ambiguity_recall, latency_metrics, calibration_metrics, throughput_qps,
wheel_size_mb, data_size_mb_from_manifest. All fixtures are hand-built
(Query + Response + Observation) — offline, deterministic, no network or parquet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmarks.core.kernel import Observation, Query, Response
from benchmarks.core.metrics import (
    _is_editable_install,
    _wheel_size_mb_from_pkg_dir,
    _wilson_interval,
    accuracy_metrics,
    ambiguity_recall,
    calibration_metrics,
    data_size_mb_from_manifest,
    is_row_correct,
    latency_metrics,
    throughput_qps,
    wheel_size_mb,
)


def _row(
    *,
    expected_ids: tuple[str, ...] = ("country/USA",),
    language: str = "en",
    entity_type: str = "country",
    difficulty: str = "easy",
    capabilities: tuple[str, ...] = (),
) -> Query:
    return Query(
        query_id="q",
        text="x",
        expected_ids=expected_ids,
        language=language,
        entity_type=entity_type,
        category="canonical",
        difficulty=difficulty,
        capabilities=capabilities,
        source="synthetic",
        notes=None,
    )


def _resp(
    *,
    status: str = "match",
    match_ids: tuple[str, ...] = ("country/USA",),
    confidence: float | None = None,
) -> Response:
    return Response(status=status, match_ids=match_ids, confidence=confidence)  # type: ignore[arg-type]


def _obs(
    row: Query,
    resp: Response,
    latency_ms: float = 1.0,
) -> Observation:
    return Observation(query=row, response=resp, latency_ms=latency_ms)


def test_is_row_correct_error() -> None:
    assert is_row_correct(_row(), _resp(status="error")) is False


def test_is_row_correct_abstain_expected() -> None:
    # empty expected_ids + no_match → correct
    assert (
        is_row_correct(_row(expected_ids=()), _resp(status="no_match", match_ids=()))
        is True
    )
    # empty expected_ids + match → incorrect
    assert (
        is_row_correct(_row(expected_ids=()), _resp(status="match", match_ids=("x",)))
        is False
    )


def test_is_row_correct_match() -> None:
    # non-empty expected, intersection with match_ids → correct
    assert (
        is_row_correct(_row(expected_ids=("a", "b")), _resp(match_ids=("b",))) is True
    )
    # non-empty expected, no intersection → incorrect
    assert is_row_correct(_row(expected_ids=("a",)), _resp(match_ids=("z",))) is False


def test_accuracy_empty_returns_zero_dict() -> None:
    result = accuracy_metrics(observations=[])
    # Verify all expected fields are present via attribute access.
    assert result.overall == pytest.approx(0.0)
    assert result.wrong_match_rate == pytest.approx(0.0)
    assert result.abstention_precision == pytest.approx(0.0)
    assert result.abstention_recall == pytest.approx(0.0)
    assert result.error_rate == pytest.approx(0.0)
    assert result.row_count == 0
    assert result.by_capability == {}
    assert result.by_language == {}
    assert result.by_difficulty == {}
    assert result.by_entity_type == {}
    assert result.by_entity_type_n == {}
    assert result.by_entity_type_wrong_match == {}


def test_accuracy_overall_ratio() -> None:
    # 3 rows: 2 correct, 1 wrong
    observations = [
        _obs(_row(expected_ids=("a",)), _resp(match_ids=("a",))),
        _obs(_row(expected_ids=("b",)), _resp(match_ids=("b",))),
        _obs(_row(expected_ids=("c",)), _resp(match_ids=("z",))),
    ]
    result = accuracy_metrics(observations=observations)
    assert result.overall == pytest.approx(2 / 3)
    assert result.row_count == 3


def test_accuracy_abstention_precision() -> None:
    # 2 correct abstentions (no expected_ids), 1 incorrect (abstained on expected_ids).
    # abstention_precision = correct / total_abstained = 2/3.
    observations = [
        _obs(_row(expected_ids=()), _resp(status="no_match", match_ids=())),
        _obs(_row(expected_ids=()), _resp(status="no_match", match_ids=())),
        _obs(_row(expected_ids=("a",)), _resp(status="no_match", match_ids=())),
    ]
    result = accuracy_metrics(observations=observations)
    assert result.abstention_precision == pytest.approx(2 / 3)


def test_accuracy_abstention_recall() -> None:
    # 3 rows where expected_ids=() (should abstain); 2 did, 1 falsely matched.
    # abstention_recall = correct_abstentions / total_should_abstain = 2/3.
    observations = [
        _obs(_row(expected_ids=()), _resp(status="no_match", match_ids=())),
        _obs(_row(expected_ids=()), _resp(status="no_match", match_ids=())),
        _obs(_row(expected_ids=()), _resp(status="match", match_ids=("x",))),
    ]
    result = accuracy_metrics(observations=observations)
    assert result.abstention_recall == pytest.approx(2 / 3)


def test_accuracy_wrong_match_rate() -> None:
    # 3 rows with status="match"; 2 wrong (no intersection), 1 correct
    observations = [
        _obs(_row(expected_ids=("a",)), _resp(status="match", match_ids=("z",))),
        _obs(_row(expected_ids=("b",)), _resp(status="match", match_ids=("z",))),
        _obs(_row(expected_ids=("c",)), _resp(status="match", match_ids=("c",))),
    ]
    result = accuracy_metrics(observations=observations)
    assert result.wrong_match_rate == pytest.approx(2 / 3)


def test_accuracy_error_rate() -> None:
    observations = [
        _obs(_row(), _resp(status="error")),
        _obs(_row(), _resp(status="error")),
        _obs(_row(), _resp(status="match")),
    ]
    result = accuracy_metrics(observations=observations)
    assert result.error_rate == pytest.approx(2 / 3)


def test_accuracy_row_count() -> None:
    observations = [_obs(_row(), _resp())] * 5
    result = accuracy_metrics(observations=observations)
    assert result.row_count == 5


def test_accuracy_strata_ratios() -> None:
    # 2 language buckets (en, fr), 2 difficulty buckets (easy, hard)
    observations = [
        _obs(
            _row(language="en", difficulty="easy", expected_ids=("a",)),
            _resp(match_ids=("a",)),
        ),
        _obs(
            _row(language="en", difficulty="easy", expected_ids=("b",)),
            _resp(match_ids=("z",)),
        ),
        _obs(
            _row(language="fr", difficulty="hard", expected_ids=("c",)),
            _resp(match_ids=("c",)),
        ),
    ]
    result = accuracy_metrics(observations=observations)
    # en: 1/2; fr: 1/1
    assert result.by_language["en"] == pytest.approx(0.5)
    assert result.by_language["fr"] == pytest.approx(1.0)
    # easy: 1/2; hard: 1/1
    assert result.by_difficulty["easy"] == pytest.approx(0.5)
    assert result.by_difficulty["hard"] == pytest.approx(1.0)


def test_accuracy_strata_zero_denominator_omitted() -> None:
    # Only "en" rows → no "fr" key in by_language (zero denominator omitted)
    observations = [_obs(_row(language="en"), _resp())]
    result = accuracy_metrics(observations=observations)
    assert "fr" not in result.by_language


def test_ambiguity_recall_no_ambiguous_rows() -> None:
    # All rows have 0 or 1 expected_id → no ambiguous rows → 0.0
    observations = [
        _obs(_row(expected_ids=("a",)), _resp()),
        _obs(_row(expected_ids=()), _resp(status="no_match", match_ids=())),
    ]
    assert ambiguity_recall(observations=observations) == pytest.approx(0.0)


def test_ambiguity_recall_partial_hit() -> None:
    # expected=("a","b"), match_ids=("a",) → intersection non-empty → 1.0
    observations = [
        _obs(_row(expected_ids=("a", "b")), _resp(match_ids=("a",))),
    ]
    assert ambiguity_recall(observations=observations) == pytest.approx(1.0)


def test_ambiguity_recall_full_miss() -> None:
    # expected=("a","b"), match_ids=("x","y") → no intersection → 0.0
    observations = [
        _obs(_row(expected_ids=("a", "b")), _resp(match_ids=("x", "y"))),
    ]
    assert ambiguity_recall(observations=observations) == pytest.approx(0.0)


def test_ambiguity_recall_full_hit() -> None:
    # expected=("a","b"), match_ids=("a","b") → intersection → 1.0
    observations = [
        _obs(_row(expected_ids=("a", "b")), _resp(match_ids=("a", "b"))),
    ]
    assert ambiguity_recall(observations=observations) == pytest.approx(1.0)


def test_ambiguity_recall_mixed() -> None:
    # 2 rows: 1 hit, 1 miss → 0.5
    observations = [
        _obs(_row(expected_ids=("a", "b")), _resp(match_ids=("a",))),
        _obs(_row(expected_ids=("c", "d")), _resp(match_ids=("x",))),
    ]
    assert ambiguity_recall(observations=observations) == pytest.approx(0.5)


def test_latency_small_n_nulls_p95_p99() -> None:
    # n=5 < 20 threshold: p95 and p99 are None (insufficient sample for tail estimates).
    # p50 is still computed; min/mean/max present. sample_count == 5.
    lats = [10.0, 20.0, 30.0, 40.0, 50.0]
    result = latency_metrics(latencies_ms=lats)
    assert result.mean == pytest.approx(30.0)
    assert result.min == pytest.approx(10.0)
    assert result.max == pytest.approx(50.0)
    assert result.p50 == pytest.approx(30.0)
    assert result.p95 is None
    assert result.p99 is None
    assert result.sample_count == 5


def test_latency_n19_nulls() -> None:
    # n=19 < 20: p95 and p99 are None. sample_count == 19.
    lats = list(range(1, 20, 1))  # 1..19
    lats_f = [float(v) for v in lats]
    result = latency_metrics(latencies_ms=lats_f)
    assert result.p95 is None
    assert result.p99 is None
    assert result.sample_count == 19


def test_latency_n20_floats() -> None:
    # n=20 >= 20 threshold: p95 and p99 are populated as floats.
    lats = [float(v) for v in range(1, 21)]  # 1..20
    result = latency_metrics(latencies_ms=lats)
    assert isinstance(result.p95, float)
    assert isinstance(result.p99, float)
    assert result.sample_count == 20


def test_latency_metrics_empty() -> None:
    result = latency_metrics(latencies_ms=[])
    assert result.p50 == 0.0
    assert result.p95 is None
    assert result.p99 is None
    assert result.mean == 0.0
    assert result.min == 0.0
    assert result.max == 0.0
    assert result.sample_count == 0


def test_wilson_interval_pinned_value() -> None:
    # Wilson score interval for successes=58, n=100.
    # With z=1.96 (95% CI): low≈0.4821, high≈0.6720.
    low, high = _wilson_interval(successes=58, n=100)
    assert low == pytest.approx(0.4821, abs=1e-3)
    assert high == pytest.approx(0.6720, abs=1e-3)
    assert 0.0 <= low <= high <= 1.0


def test_wilson_interval_clamp_extremes() -> None:
    # all correct: successes==n → high clamped to 1.0
    low, high = _wilson_interval(successes=100, n=100)
    assert high == pytest.approx(1.0, abs=1e-6)
    assert low < 1.0
    # all wrong: successes==0 → low clamped to 0.0
    low, high = _wilson_interval(successes=0, n=100)
    assert low == pytest.approx(0.0, abs=1e-6)
    assert high > 0.0


def test_accuracy_ci_none_when_empty() -> None:
    result = accuracy_metrics(observations=[])
    assert result.accuracy_ci_low is None
    assert result.accuracy_ci_high is None
    assert result.row_count == 0


def test_accuracy_ci_bounds_populated() -> None:
    # 58 correct out of 100 total; CI should bracket the point estimate
    correct = [_obs(_row(expected_ids=("a",)), _resp(match_ids=("a",)))] * 58
    wrong = [_obs(_row(expected_ids=("b",)), _resp(match_ids=("z",)))] * 42
    result = accuracy_metrics(observations=correct + wrong)
    assert result.overall == pytest.approx(0.58)
    assert result.accuracy_ci_low is not None
    assert result.accuracy_ci_high is not None
    assert result.accuracy_ci_low < result.overall < result.accuracy_ci_high
    assert 0.0 <= result.accuracy_ci_low <= 1.0
    assert 0.0 <= result.accuracy_ci_high <= 1.0


def test_calibration_no_confidence_sentinels() -> None:
    # All confidence=None → n_with_confidence==0
    observations = [_obs(_row(), _resp(confidence=None))] * 5
    result = calibration_metrics(observations=observations)
    assert result.n_with_confidence == 0
    assert result.ece is None
    assert result.brier is None
    assert len(result.reliability_bins) == 10
    for b in result.reliability_bins:
        assert b.count == 0


def test_calibration_below_20_sentinels() -> None:
    # 19 confident rows → n<20 → ece/brier are None but bins populated
    observations = [
        _obs(_row(expected_ids=("a",)), _resp(match_ids=("a",), confidence=0.95))
    ] * 19
    result = calibration_metrics(observations=observations)
    assert result.n_with_confidence == 19
    assert result.ece is None
    assert result.brier is None
    # Bin 9 should be populated (confidence=0.95 → index=9)
    bin9 = result.reliability_bins[9]
    assert bin9.count == 19


def test_calibration_ece_formula() -> None:
    # 20 rows all with confidence=0.95: 18 correct, 2 wrong.
    # Observed accuracy in bin=0.9. ECE = |0.95 - 0.9| * (20/20) = 0.05.
    # Brier score = (18*0.05² + 2*0.95²) / 20 ≈ 0.0925.
    correct_observations = [
        _obs(_row(expected_ids=("a",)), _resp(match_ids=("a",), confidence=0.95))
    ] * 18
    wrong_observations = [
        _obs(_row(expected_ids=("a",)), _resp(match_ids=("z",), confidence=0.95))
    ] * 2
    observations = correct_observations + wrong_observations

    result = calibration_metrics(observations=observations)
    assert result.n_with_confidence == 20
    assert result.ece == pytest.approx(0.05)
    assert result.brier == pytest.approx(0.0925)

    bin9 = result.reliability_bins[9]
    assert bin9.count == 20
    assert bin9.mean_confidence == pytest.approx(0.95)
    assert bin9.observed_accuracy == pytest.approx(0.9)


def test_calibration_ece_two_bins() -> None:
    # 10 rows @confidence=0.95 (all correct) + 10 @confidence=0.15 (all wrong).
    # Bin 0.9-1.0: 10 rows, obs_acc=1.0 -> |0.95-1.0|*(10/20) = 0.025.
    # Bin 0.1-0.2: 10 rows, obs_acc=0.0 -> |0.15-0.0|*(10/20) = 0.075.
    # ECE = 0.025 + 0.075 = 0.1.
    high_conf = [
        _obs(_row(expected_ids=("a",)), _resp(match_ids=("a",), confidence=0.95))
    ] * 10
    low_conf = [
        _obs(_row(expected_ids=("a",)), _resp(match_ids=("z",), confidence=0.15))
    ] * 10
    observations = high_conf + low_conf

    result = calibration_metrics(observations=observations)
    assert result.n_with_confidence == 20
    assert result.ece == pytest.approx(0.1)


def test_throughput_zero_guard() -> None:
    assert throughput_qps(latencies_ms=[1.0, 2.0], wall_elapsed_seconds=0.0) == 0.0
    assert throughput_qps(latencies_ms=[1.0, 2.0], wall_elapsed_seconds=-1.0) == 0.0


def test_throughput_normal() -> None:
    result = throughput_qps(latencies_ms=[1.0] * 10, wall_elapsed_seconds=2.0)
    assert result == pytest.approx(5.0)


def test_wheel_size_empty_name() -> None:
    # empty dist_name → None, no import.metadata access
    assert wheel_size_mb(dist_name="") is None


def test_wheel_size_unknown_dist() -> None:
    # unknown distribution → None (PackageNotFoundError handled)
    assert wheel_size_mb(dist_name="__nonexistent_pkg_xyz__") is None


def test_is_editable_install_via_direct_url(tmp_path: Path) -> None:
    """direct_url.json with dir_info.editable=true → True."""
    import importlib.metadata as _meta
    import json as _json

    dist_info = tmp_path / "fake-1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: fake\nVersion: 1.0\n"
    )
    (dist_info / "RECORD").write_text("")
    (dist_info / "direct_url.json").write_text(
        _json.dumps({"url": "file:///some/path", "dir_info": {"editable": True}})
    )

    dist = _meta.Distribution.at(dist_info)
    assert _is_editable_install(dist) is True


def test_is_editable_install_non_editable_direct_url(tmp_path: Path) -> None:
    """direct_url.json with dir_info.editable=false → not editable (no .pth stub either)."""
    import importlib.metadata as _meta
    import json as _json

    dist_info = tmp_path / "fake-1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: fake\nVersion: 1.0\n"
    )
    (dist_info / "RECORD").write_text("")
    (dist_info / "direct_url.json").write_text(
        _json.dumps(
            {
                "url": "https://files.example/fake-1.0.whl",
                "dir_info": {"editable": False},
            }
        )
    )

    dist = _meta.Distribution.at(dist_info)
    assert _is_editable_install(dist) is False


def test_is_editable_install_via_pth_stub(tmp_path: Path) -> None:
    """A .pth file in the recorded files list → editable."""
    import importlib.metadata as _meta

    dist_info = tmp_path / "fake-1.0.dist-info"
    dist_info.mkdir()
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: fake\nVersion: 1.0\n"
    )
    # The .pth file must physically exist in the parent directory (site-packages level)
    # and be listed in RECORD for dist.files to include it.
    (tmp_path / "fake.pth").write_bytes(b"import sys\n")
    (dist_info / "RECORD").write_text("fake.pth,,\nfake-1.0.dist-info/RECORD,,\n")

    dist = _meta.Distribution.at(dist_info)
    assert _is_editable_install(dist) is True


def _make_pkg_tree(
    root: Path, *, with_manifest: bool = True, remote_modules: list[str] | None = None
) -> Path:
    """Build a minimal fake package directory for testing _wheel_size_mb_from_pkg_dir."""
    import json as _json

    pkg = root / "mypkg"
    pkg.mkdir()
    # Python source
    (pkg / "__init__.py").write_bytes(b"x" * 500)
    (pkg / "core.py").write_bytes(b"x" * 1000)
    # py.typed marker
    (pkg / "py.typed").write_bytes(b"")
    # __pycache__ — must be excluded
    cache = pkg / "__pycache__"
    cache.mkdir()
    (cache / "core.cpython-312.pyc").write_bytes(b"y" * 2000)

    data_dir = pkg / "_data"
    data_dir.mkdir()

    remote_ids = remote_modules or []
    bundled_ids = ["geo.countries"]
    all_ids = bundled_ids + remote_ids

    if with_manifest:
        modules = []
        for mid in bundled_ids:
            modules.append({"module_id": mid, "distribution": "bundled"})
        for mid in remote_ids:
            modules.append({"module_id": mid, "distribution": "remote"})
        (data_dir / "manifest.json").write_text(_json.dumps({"modules": modules}))

    for mid in all_ids:
        parts = mid.split(".")
        mod_dir = data_dir.joinpath(*parts)
        mod_dir.mkdir(parents=True)
        # Files that ship in wheel for any module
        (mod_dir / "metadata.json").write_bytes(b"m" * 100)
        # Bundled-only runtime files (in wheel)
        (mod_dir / "entities.sqlite").write_bytes(b"s" * 4000)
        (mod_dir / "symspell.dict").write_bytes(b"d" * 1000)
        # Excluded build-provenance files
        (mod_dir / "changelog.md").write_bytes(b"c" * 200)
        (mod_dir / "diff_names.json").write_bytes(b"n" * 300)
        (mod_dir / "qa_report.json").write_bytes(b"q" * 400)
        reports = mod_dir / "reports"
        reports.mkdir()
        (reports / "summary.json").write_bytes(b"r" * 500)
        # Compressed artifacts (excluded)
        (mod_dir / f"{mid.replace('.', '-')}-entities.sqlite.gz").write_bytes(
            b"z" * 600
        )
        (mod_dir / f"{mid.replace('.', '-')}-symspell.dict.gz").write_bytes(b"z" * 700)

    return pkg


def test_pkg_dir_fallback_no_manifest(tmp_path: Path) -> None:
    """Without a manifest, all non-__pycache__ non-provenance files are counted."""
    pkg = _make_pkg_tree(tmp_path, with_manifest=False)
    result = _wheel_size_mb_from_pkg_dir(pkg, "mypkg")
    assert result is not None
    # Should count: __init__.py (500), core.py (1000), py.typed (0),
    # manifest absent, metadata.json (100), entities.sqlite (4000), symspell.dict (1000)
    # — but NOT __pycache__, changelog.md, diff_*.json, qa_report.json, reports/, *.gz
    # geo.countries dir has: metadata.json=100, entities.sqlite=4000, symspell.dict=1000
    expected_bytes = 500 + 1000 + 0 + 100 + 4000 + 1000
    expected_mb = expected_bytes / (1024 * 1024)
    assert result == pytest.approx(expected_mb, rel=1e-4)


def test_pkg_dir_fallback_bundled_only(tmp_path: Path) -> None:
    """With a manifest that has only bundled modules, all data files are counted."""
    pkg = _make_pkg_tree(tmp_path, with_manifest=True, remote_modules=[])
    result = _wheel_size_mb_from_pkg_dir(pkg, "mypkg")
    assert result is not None
    # Same as no-manifest case: bundled sqlite+dict are counted
    # manifest.json itself: small JSON
    # metadata.json (100), entities.sqlite (4000), symspell.dict (1000)
    # __init__.py (500), core.py (1000), py.typed (0)
    # Provenance excluded
    import json as _json

    manifest_size = len(
        _json.dumps(
            {"modules": [{"module_id": "geo.countries", "distribution": "bundled"}]}
        ).encode()
    )
    expected_bytes = 500 + 1000 + 0 + manifest_size + 100 + 4000 + 1000
    expected_mb = expected_bytes / (1024 * 1024)
    assert result == pytest.approx(expected_mb, rel=1e-4)


def test_pkg_dir_fallback_remote_module_excluded(tmp_path: Path) -> None:
    """Remote module's entities.sqlite and symspell.dict are excluded; metadata.json stays."""
    pkg = _make_pkg_tree(tmp_path, with_manifest=True, remote_modules=["geo.admin1"])
    result = _wheel_size_mb_from_pkg_dir(pkg, "mypkg")
    assert result is not None
    # Remote module (geo.admin1): entities.sqlite (4000) + symspell.dict (1000) excluded
    # But metadata.json (100) stays
    # Bundled module (geo.countries): all runtime files included
    import json as _json

    manifest_size = len(
        _json.dumps(
            {
                "modules": [
                    {"module_id": "geo.countries", "distribution": "bundled"},
                    {"module_id": "geo.admin1", "distribution": "remote"},
                ]
            }
        ).encode()
    )
    # py sources: 500+1000+0, manifest: manifest_size
    # bundled geo.countries: 100+4000+1000
    # remote geo.admin1: metadata.json(100) only (sqlite + dict excluded)
    expected_bytes = 500 + 1000 + 0 + manifest_size + (100 + 4000 + 1000) + 100
    expected_mb = expected_bytes / (1024 * 1024)
    assert result == pytest.approx(expected_mb, rel=1e-4)


def test_pkg_dir_fallback_empty_dir_returns_none(tmp_path: Path) -> None:
    """An empty package directory → None (total would be 0)."""
    pkg = tmp_path / "emptypkg"
    pkg.mkdir()
    assert _wheel_size_mb_from_pkg_dir(pkg, "emptypkg") is None


def test_wheel_size_editable_resolvekit_nonzero() -> None:
    """The live resolvekit editable install returns a realistic wheel size (> 1 MB)."""
    result = wheel_size_mb(dist_name="resolvekit")
    assert result is not None
    assert result > 1.0, f"Expected > 1 MB for resolvekit wheel, got {result:.4f} MB"


def test_data_size_mb_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "no_such_manifest.json"
    assert data_size_mb_from_manifest(manifest_path=missing) is None


def test_data_size_mb_no_remote_entries(tmp_path: Path) -> None:
    import json as _json

    manifest = {
        "schema_version": 1,
        "modules": [
            {"module_id": "geo.countries", "distribution": "bundled", "size_mb": 2.6},
        ],
    }
    p = tmp_path / "manifest.json"
    p.write_text(_json.dumps(manifest))
    # No remote entries → None (nothing downloaded separately)
    assert data_size_mb_from_manifest(manifest_path=p) is None


def test_data_size_mb_sums_remote_only(tmp_path: Path) -> None:
    import json as _json

    manifest = {
        "schema_version": 1,
        "modules": [
            {"module_id": "geo.countries", "distribution": "bundled", "size_mb": 2.6},
            {"module_id": "geo.admin1", "distribution": "remote", "size_mb": 11.81},
            {"module_id": "geo.admin2", "distribution": "remote", "size_mb": 100.37},
        ],
    }
    p = tmp_path / "manifest.json"
    p.write_text(_json.dumps(manifest))
    result = data_size_mb_from_manifest(manifest_path=p)
    assert result is not None
    assert result == pytest.approx(11.81 + 100.37)


# ---------------------------------------------------------------------------
# Tests for by_entity_type_n and by_entity_type_wrong_match (new fields)
# ---------------------------------------------------------------------------


def test_by_entity_type_n_counts_total_rows() -> None:
    """by_entity_type_n counts all rows for each entity_type (correct + wrong)."""
    observations = [
        _obs(_row(entity_type="country", expected_ids=("a",)), _resp(match_ids=("a",))),
        _obs(_row(entity_type="country", expected_ids=("b",)), _resp(match_ids=("z",))),
        _obs(_row(entity_type="city", expected_ids=("c",)), _resp(match_ids=("c",))),
    ]
    result = accuracy_metrics(observations=observations)
    assert result.by_entity_type_n["country"] == 2
    assert result.by_entity_type_n["city"] == 1


def test_by_entity_type_n_matches_by_entity_type_keys() -> None:
    """by_entity_type_n has the same keys as by_entity_type."""
    observations = [
        _obs(_row(entity_type="country"), _resp()),
        _obs(_row(entity_type="admin1"), _resp()),
    ]
    result = accuracy_metrics(observations=observations)
    assert set(result.by_entity_type_n.keys()) == set(result.by_entity_type.keys())


def test_by_entity_type_n_consistent_with_accuracy() -> None:
    """by_entity_type_n * by_entity_type gives correct count (integer-valued)."""
    correct = [
        _obs(_row(entity_type="country", expected_ids=("a",)), _resp(match_ids=("a",)))
    ] * 3
    wrong = [
        _obs(_row(entity_type="country", expected_ids=("b",)), _resp(match_ids=("z",)))
    ] * 2
    result = accuracy_metrics(observations=correct + wrong)
    n = result.by_entity_type_n["country"]
    assert n == 5
    acc = result.by_entity_type["country"]
    assert acc == pytest.approx(3 / 5)
    # correct count is exactly n * accuracy
    assert round(n * acc) == 3


def test_by_entity_type_wrong_match_rate() -> None:
    """by_entity_type_wrong_match tracks wrong-match rate per type."""
    observations = [
        # country: 2 wrong matches, 1 correct → rate = 2/3
        _obs(
            _row(entity_type="country", expected_ids=("a",)),
            _resp(status="match", match_ids=("z",)),
        ),
        _obs(
            _row(entity_type="country", expected_ids=("b",)),
            _resp(status="match", match_ids=("z",)),
        ),
        _obs(
            _row(entity_type="country", expected_ids=("c",)),
            _resp(status="match", match_ids=("c",)),
        ),
        # city: 0 wrong matches → rate = 0
        _obs(
            _row(entity_type="city", expected_ids=("d",)),
            _resp(status="match", match_ids=("d",)),
        ),
    ]
    result = accuracy_metrics(observations=observations)
    assert result.by_entity_type_wrong_match["country"] == pytest.approx(2 / 3)
    assert result.by_entity_type_wrong_match["city"] == pytest.approx(0.0)


def test_by_entity_type_wrong_match_excludes_abstentions() -> None:
    """Abstentions (no_match) are not counted as wrong matches."""
    observations = [
        _obs(
            _row(entity_type="country", expected_ids=("a",)),
            _resp(status="no_match", match_ids=()),
        ),
        _obs(
            _row(entity_type="country", expected_ids=("b",)),
            _resp(status="match", match_ids=("b",)),
        ),
    ]
    result = accuracy_metrics(observations=observations)
    # 1 row is no_match (not wrong-match), 1 is correct match → wrong-match rate = 0
    assert result.by_entity_type_wrong_match["country"] == pytest.approx(0.0)
