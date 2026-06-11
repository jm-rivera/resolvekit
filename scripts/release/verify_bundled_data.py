"""Verify bundled data integrity against the module manifest.

Checks that every bundled module in src/resolvekit/_data/manifest.json has:
- Its SQLite file present at the expected path.
- A SHA-256 checksum matching checksums["sqlite"] in the manifest.

Remote modules are checked for the presence of metadata.json and a populated
``remote_artifacts['sqlite']`` spec — no local SQLite or symspell is expected,
those ship from the GitHub Release and are fetched on first use.

Also checks that curated YAML data files are not stale (i.e. were refreshed
within a policy window). Staleness warnings are printed by default; under
``strict`` they are treated as hard failures.

Exit 0 on success. Exit 1 on any failure with a descriptive message.

Usage::

    uv run python -m scripts.release.verify_bundled_data
    RESOLVEKIT_VERIFY_STRICT=1 uv run python -m scripts.release.verify_bundled_data
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from resolvekit.builder.utils import sha256_file
from resolvekit.core.module_registry import module_id_to_suffix
from scripts.release._common import PROJECT_ROOT

MANIFEST_PATH = PROJECT_ROOT / "src" / "resolvekit" / "_data" / "manifest.json"
DATA_ROOT = PROJECT_ROOT / "src" / "resolvekit" / "_data"
BUILDER_DATA = PROJECT_ROOT / "src" / "resolvekit" / "builder" / "data"


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifySettings:
    strict: bool = False


def _verify_yaml_freshness(
    yaml_path: Path,
    *,
    date_key: str,
    max_age_days: int,
    today: date | None = None,
) -> list[str]:
    """Return staleness messages for one curated YAML (empty list = fresh).

    Reads ``generated_from[date_key]`` and compares it against ``today``
    (defaults to ``date.today()``).  Accepts both ``str`` (ISO YYYY-MM-DD,
    as in oecd_dac.yaml) and ``datetime.date`` (as PyYAML parses bare dates
    like groups.yaml).  A missing YAML or missing key produces a message
    rather than raising.
    """
    today = today or date.today()
    if not yaml_path.exists():
        return [f"{yaml_path.name}: file not found — cannot check freshness"]

    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"{yaml_path.name}: failed to parse YAML — {exc}"]

    generated_from = (data or {}).get("generated_from", {}) or {}
    raw = generated_from.get(date_key)
    if raw is None:
        return [f"{yaml_path.name}: 'generated_from.{date_key}' not found"]

    # PyYAML parses bare dates (groups.yaml) as datetime.date; quoted dates
    # (oecd_dac.yaml) as str — accept both.
    if isinstance(raw, date):
        query_date = raw
    else:
        try:
            query_date = date.fromisoformat(str(raw))
        except ValueError:
            return [f"{yaml_path.name}: '{date_key}' is not a valid ISO date: {raw!r}"]

    age_days = (today - query_date).days
    if age_days > max_age_days:
        return [
            f"{yaml_path.name}: '{date_key}' is {age_days} days old"
            f" (limit {max_age_days}); please refresh the data"
        ]
    return []


def _module_dir(module_id: str, domain: str) -> Path:
    suffix = module_id_to_suffix(module_id)
    if suffix is None:
        raise ValueError(f"cannot derive on-disk suffix for {module_id!r}")
    return DATA_ROOT / domain / suffix


def _verify_bundled(module_id: str, entry: dict) -> list[str]:
    """Return a list of error strings (empty = OK) for a bundled module."""
    errors: list[str] = []
    module_dir = _module_dir(module_id, entry.get("domain", ""))
    checksums = entry.get("checksums", {})
    sqlite_checksum = checksums.get("sqlite")

    store_file = entry.get("store_file")
    if store_file:
        sqlite_path = module_dir / store_file
    else:
        sqlite_path = next(module_dir.glob("*.sqlite"), None)
        if sqlite_path is None:
            errors.append(f"[{module_id}] SQLite not found in {module_dir}")
            return errors

    if not sqlite_path.exists():
        errors.append(f"[{module_id}] SQLite not found: {sqlite_path}")
        return errors

    if sqlite_checksum:
        actual = sha256_file(sqlite_path)
        if actual != sqlite_checksum:
            errors.append(
                f"[{module_id}] SHA-256 mismatch for {sqlite_path.name}:\n"
                f"  expected: {sqlite_checksum}\n"
                f"  actual:   {actual}"
            )
    else:
        print(
            f"WARNING [{module_id}] no checksums.sqlite in manifest — skipping hash check"
        )

    return errors


def _verify_remote(module_id: str, entry: dict) -> list[str]:
    """Return a list of error strings (empty = OK) for a remote module.

    For remote-distribution modules only ``metadata.json`` and a populated
    ``remote_artifacts['sqlite']`` spec are expected locally; the sqlite and
    any other artifacts (symspell, calibrator) are fetched from the GitHub
    Release at runtime.
    """
    errors: list[str] = []
    module_dir = _module_dir(module_id, entry.get("domain", ""))

    meta_path = module_dir / "metadata.json"
    if not meta_path.exists():
        errors.append(f"[{module_id}] metadata.json not found: {meta_path}")
        return errors

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception as exc:
        errors.append(f"[{module_id}] metadata.json failed to parse: {exc}")
        return errors

    remote_artifacts = meta.get("remote_artifacts") or {}
    sqlite_spec = (
        remote_artifacts.get("sqlite") if isinstance(remote_artifacts, dict) else None
    )
    if not isinstance(sqlite_spec, dict) or not sqlite_spec.get("url"):
        errors.append(
            f"[{module_id}] metadata.json missing remote_artifacts['sqlite'].url — "
            f"re-run scripts.release.release_data"
        )

    return errors


def run(*, settings: VerifySettings) -> None:
    """Verify bundled data integrity; sys.exit(1) on any failure."""
    if not MANIFEST_PATH.exists():
        if settings.strict:
            print(f"ERROR: manifest not found at {MANIFEST_PATH}", file=sys.stderr)
            sys.exit(1)
        print(f"WARNING: no manifest yet at {MANIFEST_PATH}; skipping verification")
        sys.exit(0)

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    modules = manifest.get("modules", [])

    if not modules:
        print("WARNING: manifest contains no modules; skipping verification")
        sys.exit(0)

    all_errors: list[str] = []

    # Curated-data freshness checks — warn by default, hard-fail under strict.
    freshness_checks = [
        (BUILDER_DATA / "oecd_dac.yaml", "oecd_query_date", 1095),
        (BUILDER_DATA / "groups.yaml", "wikidata_query_date", 365),
    ]
    freshness_messages: list[str] = []
    for yaml_path, date_key, max_age_days in freshness_checks:
        freshness_messages.extend(
            _verify_yaml_freshness(
                yaml_path, date_key=date_key, max_age_days=max_age_days
            )
        )
    if freshness_messages:
        if settings.strict:
            all_errors.extend(freshness_messages)
        else:
            for msg in freshness_messages:
                print(f"WARNING: {msg}")

    for entry in modules:
        module_id = entry.get("module_id", "<unknown>")
        distribution = entry.get("distribution", "")

        if distribution == "bundled":
            all_errors.extend(_verify_bundled(module_id, entry))
        elif distribution == "remote":
            all_errors.extend(_verify_remote(module_id, entry))
        else:
            print(
                f"WARNING [{module_id}] unknown distribution '{distribution}' — skipping"
            )

    if all_errors:
        for err in all_errors:
            print(f"FAIL: {err}", file=sys.stderr)
        sys.exit(1)

    print(f"OK: verified {len(modules)} module(s) from {MANIFEST_PATH}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raise SystemExit(
            "verify_bundled_data.py takes no CLI arguments. "
            "Set RESOLVEKIT_VERIFY_STRICT=1 for strict mode."
        )
    strict = os.environ.get("RESOLVEKIT_VERIFY_STRICT") == "1"
    run(settings=VerifySettings(strict=strict))
