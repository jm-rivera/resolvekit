"""Chunk-level extraction/normalization/materialization helpers."""

from __future__ import annotations

import gzip
import json
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from pydantic import BaseModel

from resolvekit.builder.pipeline.types import BuildExecutionError, ChunkWorkItem
from resolvekit.builder.sqlite import (
    insert_normalized_payload,
    staging_db_path,
)

if TYPE_CHECKING:
    from resolvekit.builder.pipeline.core import BuildContext


@dataclass(frozen=True, slots=True, kw_only=True)
class ChunkRetrySignature:
    """Identity tuple for a chunk retry-state row, used to detect progress."""

    chunk_id: Any
    status: Any
    failed_stage: Any
    extract_attempts: Any
    normalize_attempts: Any
    materialize_attempts: Any
    materialized: Any


def retry_parallel_stage(
    *,
    context: BuildContext,
    stage: str,
    load_chunks: Callable[[int], list[dict[str, Any]]],
    process: Callable[[BuildContext, ChunkWorkItem], None],
) -> None:
    """Run chunk workers with retries and failure budget checks."""

    def process_batch(
        batch_context: BuildContext, work_items: list[ChunkWorkItem]
    ) -> None:
        with ThreadPoolExecutor(
            max_workers=batch_context.options.max_workers
        ) as executor:
            futures = {
                executor.submit(process, batch_context, item): item
                for item in work_items
            }
            for future in as_completed(futures):
                item = futures[future]
                try:
                    future.result()
                except Exception as exc:
                    batch_context.state.mark_chunk_failure(
                        chunk_id=item.chunk_id,
                        stage=stage,
                        error=str(exc),
                    )

    retry_stage_batches(
        context=context,
        stage=stage,
        load_chunks=load_chunks,
        process_batch=process_batch,
    )


def retry_sequential_stage(
    *,
    context: BuildContext,
    stage: str,
    load_chunks: Callable[[int], list[dict[str, Any]]],
    process: Callable[[BuildContext, ChunkWorkItem], None],
) -> None:
    """Run chunk work sequentially with shared retry/backoff semantics."""

    def process_batch(
        batch_context: BuildContext, work_items: list[ChunkWorkItem]
    ) -> None:
        for item in work_items:
            try:
                process(batch_context, item)
            except Exception as exc:
                batch_context.state.mark_chunk_failure(
                    chunk_id=item.chunk_id,
                    stage=stage,
                    error=str(exc),
                )

    retry_stage_batches(
        context=context,
        stage=stage,
        load_chunks=load_chunks,
        process_batch=process_batch,
    )


def retry_stage_batches(
    *,
    context: BuildContext,
    stage: str,
    load_chunks: Callable[[int], list[dict[str, Any]]],
    process_batch: Callable[[BuildContext, list[ChunkWorkItem]], None],
) -> None:
    """Run stage batches with retry/backoff and blocking-failure checks."""
    max_retries = context.options.max_retries
    retry_round = 0

    while True:
        rows = load_chunks(max_retries)
        if not rows:
            return

        previous_signature = _chunk_retry_signature(rows)
        work_items = [
            ChunkWorkItem(chunk_id=str(row["chunk_id"]), domain=str(row["domain"]))
            for row in rows
        ]
        process_batch(context, work_items)

        if context.state.has_blocking_failures(stage, max_retries):
            raise BuildExecutionError(
                f"{stage} failed for one or more chunks after max retries."
            )

        next_rows = load_chunks(max_retries)
        if not next_rows:
            return
        if _chunk_retry_signature(next_rows) == previous_signature:
            raise BuildExecutionError(
                f"{stage} made no progress between retry rounds; aborting."
            )

        delay = min(
            context.options.retry_base_delay_sec * (2.0**retry_round),
            context.options.retry_max_delay_sec,
        )
        if delay > 0.0:
            time.sleep(delay)
        retry_round += 1


def _chunk_retry_signature(
    rows: list[dict[str, Any]],
) -> tuple[ChunkRetrySignature, ...]:
    return tuple(
        ChunkRetrySignature(
            chunk_id=row.get("chunk_id"),
            status=row.get("status"),
            failed_stage=row.get("failed_stage"),
            extract_attempts=row.get("extract_attempts"),
            normalize_attempts=row.get("normalize_attempts"),
            materialize_attempts=row.get("materialize_attempts"),
            materialized=row.get("materialized"),
        )
        for row in rows
    )


def extract_chunk(context: BuildContext, item: ChunkWorkItem) -> None:
    """Fetch one raw payload chunk from source adapter."""
    entity_ids = context.state.entity_ids_for_chunk(item.chunk_id)
    payload = context.adapters[item.domain].fetch_raw_chunk(item.domain, entity_ids)

    raw_path = context.raw_dir / f"{item.chunk_id.replace(':', '_')}.json.gz"
    gzip_json_write(raw_path, payload)

    context.state.mark_chunk_success(
        chunk_id=item.chunk_id,
        stage="extract",
        raw_path=str(raw_path),
    )


def normalize_chunk(context: BuildContext, item: ChunkWorkItem) -> None:
    """Normalize one raw chunk into canonical row payload."""
    row = context.state.get_chunk(item.chunk_id)
    raw_path = row.get("raw_path")
    if not raw_path:
        raise BuildExecutionError(f"Missing raw path for chunk: {item.chunk_id}")

    raw_payload = gzip_json_read(Path(raw_path))

    normalized_payload = context.adapters[item.domain].normalize_raw_chunk(
        item.domain,
        raw_payload,
    )
    normalized_path = (
        context.normalized_dir / f"{item.chunk_id.replace(':', '_')}.json.gz"
    )
    gzip_json_write(normalized_path, normalized_payload)

    context.state.mark_chunk_success(
        chunk_id=item.chunk_id,
        stage="normalize",
        normalized_path=str(normalized_path),
    )


def materialize_chunk(context: BuildContext, item: ChunkWorkItem) -> None:
    """Insert one normalized chunk payload into staging SQLite DB."""
    row = context.state.get_chunk(item.chunk_id)
    normalized_path = row.get("normalized_path")
    if not normalized_path:
        raise BuildExecutionError(
            f"Missing normalized payload path for chunk: {item.chunk_id}"
        )

    payload = gzip_json_read(Path(normalized_path))

    db_path = staging_db_path(context.staging_dir, item.domain)
    insert_normalized_payload(db_path, payload)
    context.state.mark_chunk_success(chunk_id=item.chunk_id, stage="materialize")


def gzip_json_read(path: Path) -> dict[str, Any]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise BuildExecutionError(
            f"Expected object payload in {path}, got {type(payload).__name__}."
        )
    return cast(dict[str, Any], payload)


def gzip_json_write(path: Path, payload: dict[str, Any] | BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    match payload:
        case BaseModel():
            with gzip.open(path, "wb") as handle:
                handle.write(payload.model_dump_json().encode())
        case _:
            with gzip.open(path, "wt", encoding="utf-8") as handle:
                json.dump(payload, handle)
