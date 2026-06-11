"""Shared pipeline constants, errors, and typed stage artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from resolvekit.builder.models import ModuleRecipe
from resolvekit.builder.utils import utc_now_iso

if TYPE_CHECKING:
    from resolvekit.builder.pipeline.core import BuildContext

STAGES: tuple[str, ...] = (
    # Ordered stage names — position equals execution order.
    #
    # Adding a new pipeline stage requires THREE coordinated edits:
    #   1. ``STAGES`` (here) — insert the stage name at the desired position.
    #   2. ``STAGE_FUNCTIONS`` in ``core.py`` — add the stage name → callable
    #      mapping.
    #   3. A ``stage_*`` implementation function in ``stages.py``.
    #
    # Resume / done-skipping semantics:
    #   ``run_stage`` (``core.py``) checks the stage's persisted status before
    #   calling its function.  A stage already marked ``"done"`` in the run
    #   state is skipped on resume, so the three edits above must be present
    #   before the first run that is expected to execute the new stage.
    #
    # Conditional 4th edit site:
    #   If the new stage packages a domain artifact whose feature schema differs
    #   from the ``{domain}.features.v1`` default (see ``packaging.py``), also
    #   add an entry to ``FEATURE_SCHEMA_BY_DOMAIN`` below.
    "prepare",
    "discover",
    "extract",
    "normalize",
    "materialize",
    "canonicalize",
    "reconcile",
    "enrich",
    "validate",
    "package",
    "changelog",
)

FEATURE_SCHEMA_BY_DOMAIN = {
    "geo": "geo.features.v1",
    "org": "org.features.v1",
}


class BuildExecutionError(RuntimeError):
    """Raised when one build stage cannot complete successfully."""


@dataclass(frozen=True, slots=True)
class ChunkWorkItem:
    """Single chunk to process in extract/normalize/materialize stages."""

    chunk_id: str
    domain: str


@dataclass(frozen=True, slots=True)
class DomainArtifacts:
    """Produced datapack artifacts and QA status for one domain."""

    domain: str
    datapack_dir: Path
    sqlite_path: Path
    metrics: dict[str, float | int]
    qa_checks: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ReleaseCandidate:
    """Candidate release pending changelog and promotion."""

    recipe: ModuleRecipe
    version: str
    output_path: Path
    domain_artifacts: dict[str, DomainArtifacts]
    # Snapshot of the on-disk datapack this build replaced, captured before
    # overwrite; the baseline for the drift gate and changelog diff. ``None``
    # on a first build (nothing to compare against).
    previous_db_path: Path | None


class LastError(BaseModel):
    """Snapshot of the most recent build-stage failure (persisted to state.sqlite
    and surfaced in build_report.json)."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    stage: str
    error_type: str
    message: str
    timestamp: str = Field(default_factory=utc_now_iso)

    # Kept as plain @property — adding @computed_field would auto-serialize it
    # and break the legacy-error-only-at-write-boundary intent (state.sqlite
    # stores only the error_type and message to avoid redundancy with the dict field).
    @property
    def error(self) -> str:
        """Legacy `error = f'{error_type}: {message}'` string for build_report.json."""
        return f"{self.error_type}: {self.message}"

    def dump_for_build_report(self) -> dict[str, Any]:
        """Serialize to JSON dict including the legacy `error` field.

        Use this at the build_report.json write boundary (NOT for state.sqlite
        persistence — that path uses `model_dump(mode='json')` directly so `error`
        is not stored redundantly).
        """
        payload = self.model_dump(mode="json")
        payload["error"] = self.error
        return payload


# ---------------------------------------------------------------------------
# ReleaseCandidate serialization helpers
# ---------------------------------------------------------------------------
# Used by stage_package (persist) and load_release_candidates (reload on
# resume).  JSON-serializable dicts so RunStateStore.set_meta / get_meta
# can round-trip them without a custom encoder.
# ---------------------------------------------------------------------------


def _serialize_domain_artifacts(
    artifacts: dict[str, DomainArtifacts],
) -> list[dict[str, Any]]:
    return [
        {
            "domain": a.domain,
            "datapack_dir": str(a.datapack_dir),
            "sqlite_path": str(a.sqlite_path),
            "metrics": dict(a.metrics),
            "qa_checks": dict(a.qa_checks),
        }
        for a in artifacts.values()
    ]


def _deserialize_domain_artifacts(
    rows: list[dict[str, Any]],
) -> dict[str, DomainArtifacts]:
    return {
        row["domain"]: DomainArtifacts(
            domain=row["domain"],
            datapack_dir=Path(row["datapack_dir"]),
            sqlite_path=Path(row["sqlite_path"]),
            metrics=dict(row["metrics"]),
            qa_checks=dict(row["qa_checks"]),
        )
        for row in rows
    }


def serialize_release_candidate(c: ReleaseCandidate) -> dict[str, Any]:
    """Convert a ``ReleaseCandidate`` to a JSON-serializable dict."""
    return {
        "recipe": c.recipe.model_dump(mode="json"),
        "version": c.version,
        "output_path": str(c.output_path),
        "domain_artifacts": _serialize_domain_artifacts(c.domain_artifacts),
        "previous_db_path": str(c.previous_db_path) if c.previous_db_path else None,
    }


def deserialize_release_candidate(data: dict[str, Any]) -> ReleaseCandidate:
    """Reconstruct a ``ReleaseCandidate`` from a serialized dict."""
    return ReleaseCandidate(
        recipe=ModuleRecipe.model_validate(data["recipe"]),
        version=data["version"],
        output_path=Path(data["output_path"]),
        domain_artifacts=_deserialize_domain_artifacts(data["domain_artifacts"]),
        previous_db_path=(
            Path(data["previous_db_path"]) if data.get("previous_db_path") else None
        ),
    )


def load_release_candidates(context: BuildContext) -> list[ReleaseCandidate]:
    """Return release candidates, reloading from persisted state if needed.

    On a fresh run the candidates are already in-memory.  On a resume where
    the ``package`` stage was already ``done``, they were never re-populated
    from the stage function, so we reload from the ``"release_candidates"``
    meta key that ``stage_package`` persisted at end of its first (successful)
    run.

    The reloaded candidates are also written back onto ``context.release_candidates``
    so downstream stages (changelog, execute_build) see them without re-calling.
    """
    if context.release_candidates:
        return context.release_candidates
    raw = context.state.get_meta("release_candidates", default=None)
    if raw is None:
        return []
    candidates = [deserialize_release_candidate(row) for row in raw]
    context.release_candidates = candidates
    return candidates
