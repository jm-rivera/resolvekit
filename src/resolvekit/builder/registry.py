"""Release ledger helpers.

The ledger records published releases. It is written only by the release path
(``scripts/release/release_data.py``); a plain ``build()`` rebuilds in place and
records nothing here.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from resolvekit.builder.models import BuildOptions, ReleaseRecord
from resolvekit.builder.utils import json_read, json_write

try:
    import fcntl as _fcntl
except ImportError:  # pragma: no cover - non-Unix fallback
    _fcntl = None  # type: ignore[assignment]

_REGISTRY_THREAD_LOCK = threading.Lock()


@contextmanager
def _registry_lock(registry_path: Path) -> Iterator[None]:
    """Serialize registry file read/modify/write across threads and processes."""
    with _REGISTRY_THREAD_LOCK:
        if _fcntl is None:
            yield
            return

        lock_path = registry_path.with_suffix(f"{registry_path.suffix}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as handle:
            _fcntl.flock(handle.fileno(), _fcntl.LOCK_EX)
            try:
                yield
            finally:
                _fcntl.flock(handle.fileno(), _fcntl.LOCK_UN)


def list_releases(
    *,
    options: BuildOptions,
    module_id: str | None = None,
) -> list[ReleaseRecord]:
    """Load successful releases sorted newest-first."""
    records = _load_registry_records(options)
    if module_id:
        records = [record for record in records if record.release_id == module_id]
    return sorted(records, key=lambda record: record.created_at, reverse=True)


def append_releases(options: BuildOptions, new_records: list[ReleaseRecord]) -> None:
    """Append release records to the ledger (serialized read-modify-write)."""
    with _registry_lock(options.registry_path):
        payload = json_read(options.registry_path, default={"releases": []})
        rows = list(payload.get("releases", []))
        rows.extend(record.model_dump(mode="json") for record in new_records)
        payload["releases"] = rows
        json_write(options.registry_path, payload)


def _load_registry_records(options: BuildOptions) -> list[ReleaseRecord]:
    payload = json_read(options.registry_path, default={"releases": []})
    return [ReleaseRecord.model_validate(row) for row in payload.get("releases", [])]
