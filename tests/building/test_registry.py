"""Unit tests for build release registry behavior."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from resolvekit.builder import registry as registry_module
from resolvekit.builder.models import BuildOptions, ReleaseRecord
from resolvekit.builder.registry import append_releases
from resolvekit.builder.utils import json_read


def _record(
    tmp_path: Path,
    *,
    module_id: str = "geo.world",
    run_id: str,
    version: str,
) -> ReleaseRecord:
    return ReleaseRecord(
        module_id=module_id,
        version=version,
        run_id=run_id,
        output_path=tmp_path / run_id,
        domains=["geo"],
    )


def test_append_releases_serializes_read_modify_write(
    monkeypatch, tmp_path: Path
) -> None:
    options = BuildOptions(
        build_root=tmp_path / "build",
        datapacks_root=tmp_path / "datapacks",
    )

    entered_first_read = threading.Event()
    release_first_read = threading.Event()
    read_count_lock = threading.Lock()
    read_count = 0
    errors: list[Exception] = []
    real_json_read = registry_module.json_read

    def controlled_json_read(path: Path, default: Any = None) -> Any:
        nonlocal read_count
        with read_count_lock:
            read_count += 1
            call_number = read_count
        if call_number == 1:
            entered_first_read.set()
            if not release_first_read.wait(timeout=2):
                raise RuntimeError("Timed out waiting for first read release")
        return real_json_read(path, default=default)

    monkeypatch.setattr(registry_module, "json_read", controlled_json_read)

    def worker(record: ReleaseRecord) -> None:
        try:
            append_releases(options, [record])
        except Exception as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    t1 = threading.Thread(
        target=worker, args=(_record(tmp_path, run_id="run-a", version="1.0.0"),)
    )
    t2 = threading.Thread(
        target=worker, args=(_record(tmp_path, run_id="run-b", version="1.0.1"),)
    )

    t1.start()
    assert entered_first_read.wait(timeout=2)
    t2.start()

    time.sleep(0.1)
    assert read_count == 1
    assert t2.is_alive()

    release_first_read.set()
    t1.join(timeout=2)
    t2.join(timeout=2)

    assert not errors
    payload = json_read(options.registry_path, default={"releases": []})
    assert {row["run_id"] for row in payload["releases"]} == {"run-a", "run-b"}
