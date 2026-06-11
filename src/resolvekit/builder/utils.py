"""Shared utility helpers for module-oriented build orchestration."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from itertools import batched
from pathlib import Path
from typing import Any


def utc_now_iso() -> str:
    """Return current UTC timestamp in ISO format."""
    return datetime.now(UTC).isoformat()


def new_run_id() -> str:
    """Build a unique run identifier with UTC timestamp prefix."""
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{ts}-{uuid.uuid4().hex[:8]}"


def ensure_dir(path: Path) -> None:
    """Create directory and all missing parents."""
    path.mkdir(parents=True, exist_ok=True)


def json_write(path: Path, payload: Any) -> None:
    """Write JSON payload with stable indentation."""
    ensure_dir(path.parent)
    tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp_path.replace(path)


def json_read(path: Path, default: Any = None) -> Any:
    """Read JSON payload if present, else return default."""
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    """Compute SHA256 digest for a file."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def parse_semver(value: str) -> tuple[int, int, int]:
    """Parse ``MAJOR.MINOR.PATCH`` semantic version string."""
    parts = value.split(".")
    if len(parts) != 3:
        raise ValueError(f"Invalid semantic version: {value}")
    return int(parts[0]), int(parts[1]), int(parts[2])


def chunk_list(values: list[str], chunk_size: int) -> list[list[str]]:
    """Split values into fixed-size chunks preserving order."""
    return [list(chunk) for chunk in batched(values, chunk_size)]
