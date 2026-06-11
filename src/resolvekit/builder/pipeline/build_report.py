"""Build-report serialization — observability output for the pipeline.

Lives on its own so callers (`pipeline.core.execute_build`,
`pipeline.core.run_stage`, `pipeline.discover._persist_discover_progress`)
can import it without pulling in `pipeline.core` — `core` imports
`pipeline.stages` at module top, which in turn imports `pipeline.discover`,
so any path that loops back through `core` during its own initialization
breaks. Keeping this function in a leaf module with no `pipeline.core`
dependency keeps the import graph acyclic.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from resolvekit.builder.pipeline.types import STAGES, LastError
from resolvekit.builder.sources.discovery_events import DiscoverProgress
from resolvekit.builder.utils import json_write, utc_now_iso

if TYPE_CHECKING:
    from resolvekit.builder.pipeline.core import BuildContext


class BuildReport(BaseModel):
    """Typed build-report snapshot persisted to build_report.json."""

    model_config = ConfigDict(extra="ignore")

    run_id: str
    timestamp: str = Field(default_factory=utc_now_iso)
    stage_statuses: dict[str, str] = Field(default_factory=dict)
    chunk_counts: dict[str, int] = Field(default_factory=dict)
    discovered_chunks: dict[str, int] = Field(default_factory=dict)
    discover_progress: DiscoverProgress = Field(default_factory=DiscoverProgress)
    skipped_modules: list[dict[str, str]] = Field(default_factory=list)
    last_error: LastError | None = None


def write_build_report(context: BuildContext) -> None:
    """Persist build status and chunk counters for observability."""
    raw_last_error = context.state.get_meta("last_error", default=None)
    last_error = LastError.model_validate(raw_last_error) if raw_last_error else None

    raw_progress = context.state.get_meta("discover_progress", default={})
    discover_progress = DiscoverProgress.model_validate(raw_progress)

    stage_statuses = context.state.get_all_stage_statuses()
    report = BuildReport(
        run_id=context.run_id,
        stage_statuses={
            stage: stage_statuses.get(stage, "pending") for stage in STAGES
        },
        chunk_counts=context.state.chunk_counts(),
        discovered_chunks=context.state.get_meta("discovered_chunks", default={}),
        discover_progress=discover_progress,
        skipped_modules=context.state.get_meta("skipped_modules", default=[]),
        last_error=last_error,
    )
    # `last_error` has bespoke serialization (legacy `error` field re-derived
    # for downstream tooling), so dump everything else and substitute it in.
    payload = report.model_dump(mode="json", exclude_none=True, exclude={"last_error"})
    if last_error is not None:
        payload["last_error"] = last_error.dump_for_build_report()
    json_write(context.reports_dir / "build_report.json", payload)
