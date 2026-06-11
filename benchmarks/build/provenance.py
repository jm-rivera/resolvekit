"""Dataset build provenance records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True)
class BuildRecord:
    dataset: str
    row_count: int
    sources: tuple[dict[str, str], ...]
    seed: int
    sha256: str = ""
    notes: str | None = None


def dataset_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def write_provenance(
    *,
    data_dir: Path,
    datasets: dict[str, BuildRecord],
) -> None:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "datasets": {name: asdict(record) for name, record in datasets.items()},
    }
    (data_dir / "provenance.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True)
    )
