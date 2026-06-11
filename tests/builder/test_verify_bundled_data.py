"""Tests for run() in scripts/release/verify_bundled_data.py.

Pins: strict + checksum mismatch → SystemExit(1); non-strict missing manifest
→ sys.exit(0).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts.release.verify_bundled_data import VerifySettings, run


def _make_sqlite(path: Path) -> None:
    """Write a minimal SQLite database at *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.close()


def test_run_strict_checksum_mismatch_exits_1(tmp_path: Path, monkeypatch) -> None:
    """strict=True + SHA-256 mismatch in bundled module → SystemExit with code 1."""
    import scripts.release.verify_bundled_data as mod

    # Build a minimal SQLite file.
    # module_id_to_suffix("geo.countries") → "countries", so the dir is geo/countries/
    sqlite_path = tmp_path / "geo" / "countries" / "store.sqlite"
    _make_sqlite(sqlite_path)

    # Manifest references the file with a wrong checksum.
    manifest = {
        "modules": [
            {
                "module_id": "geo.countries",
                "distribution": "bundled",
                "domain": "geo",
                "store_file": "store.sqlite",
                "checksums": {"sqlite": "deadbeef" * 8},
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr(mod, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(mod, "DATA_ROOT", tmp_path)
    # Disable freshness checks by pointing BUILDER_DATA at a dir with no YAMLs.
    monkeypatch.setattr(mod, "BUILDER_DATA", tmp_path / "no_yamls")

    with pytest.raises(SystemExit) as exc_info:
        run(settings=VerifySettings(strict=True))

    assert exc_info.value.code == 1


def test_run_non_strict_missing_manifest_exits_0(tmp_path: Path, monkeypatch) -> None:
    """strict=False + no manifest → sys.exit(0) (warning printed, not failure)."""
    import scripts.release.verify_bundled_data as mod

    monkeypatch.setattr(mod, "MANIFEST_PATH", tmp_path / "nonexistent.json")

    with pytest.raises(SystemExit) as exc_info:
        run(settings=VerifySettings(strict=False))

    assert exc_info.value.code == 0


def test_run_strict_missing_manifest_exits_1(tmp_path: Path, monkeypatch) -> None:
    """strict=True + no manifest → sys.exit(1)."""
    import scripts.release.verify_bundled_data as mod

    monkeypatch.setattr(mod, "MANIFEST_PATH", tmp_path / "nonexistent.json")

    with pytest.raises(SystemExit) as exc_info:
        run(settings=VerifySettings(strict=True))

    assert exc_info.value.code == 1


def test_run_checksum_match_exits_0(tmp_path: Path, monkeypatch) -> None:
    """Correct SHA-256 in manifest → no SystemExit (returns normally)."""
    import scripts.release.verify_bundled_data as mod
    from resolvekit.builder.utils import sha256_file

    # module_id_to_suffix("geo.countries") → "countries", so the dir is geo/countries/
    sqlite_path = tmp_path / "geo" / "countries" / "store.sqlite"
    _make_sqlite(sqlite_path)
    checksum = sha256_file(sqlite_path)

    manifest = {
        "modules": [
            {
                "module_id": "geo.countries",
                "distribution": "bundled",
                "domain": "geo",
                "store_file": "store.sqlite",
                "checksums": {"sqlite": checksum},
            }
        ]
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    monkeypatch.setattr(mod, "MANIFEST_PATH", manifest_path)
    monkeypatch.setattr(mod, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(mod, "BUILDER_DATA", tmp_path / "no_yamls")

    # Should return normally without raising SystemExit.
    run(settings=VerifySettings(strict=False))
