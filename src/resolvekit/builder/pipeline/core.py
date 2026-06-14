"""Core orchestration for the deterministic module build pipeline."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from resolvekit.builder.geo_shared import GeoSharedStore
from resolvekit.builder.models import (
    BuildOptions,
    BuildOutcome,
    BuildPlan,
    BuildStatus,
    ReleaseRecord,
)
from resolvekit.builder.pipeline import stages as stage_module
from resolvekit.builder.pipeline.build_report import write_build_report
from resolvekit.builder.pipeline.promote import build_release_records
from resolvekit.builder.pipeline.types import (
    STAGES,
    LastError,
    ReleaseCandidate,
    load_release_candidates,
)
from resolvekit.builder.sources import (
    DataCommonsGeoSourceAdapter,
    DataCommonsOrgSourceAdapter,
)
from resolvekit.builder.sources.protocol import SourceAdapter
from resolvekit.builder.state import RunStateStore
from resolvekit.builder.utils import utc_now_iso

# Registering a new domain source adapter requires updating BOTH dicts:
#   • ``ADAPTER_FACTORIES`` — used by ``build_adapter_registry`` for full
#     (mutating) builds.
#   • ``INSPECTION_ADAPTER_FACTORIES`` — used by
#     ``build_inspection_adapter_registry`` for read-only inspection.
#
# Both dicts map domain name → factory callable matching the
# ``SourceAdapter`` protocol defined in
# ``resolvekit/builder/sources/protocol.py``.  The built-in geo/org entries
# (added below) show the expected shape.
ADAPTER_FACTORIES: dict[str, Callable[[BuildOptions], SourceAdapter]] = {}
INSPECTION_ADAPTER_FACTORIES: dict[str, Callable[[BuildOptions], SourceAdapter]] = {}
UNAVAILABLE_BUILTIN_DOMAINS: dict[str, str] = {}


@dataclass(slots=True)
class BuildContext:
    """Mutable build context shared across stage functions."""

    plan: BuildPlan
    run_id: str
    started_at: str
    resume_mode: bool = False
    adapter_builder: Callable[[BuildPlan], dict[str, SourceAdapter]] | None = None
    options: BuildOptions = field(init=False)
    run_dir: Path = field(init=False)
    raw_dir: Path = field(init=False)
    normalized_dir: Path = field(init=False)
    staging_dir: Path = field(init=False)
    reports_dir: Path = field(init=False)
    plan_path: Path = field(init=False)
    state: RunStateStore = field(init=False)
    adapters: dict[str, SourceAdapter] = field(init=False)
    release_candidates: list[ReleaseCandidate] = field(default_factory=list)
    geo_shared: GeoSharedStore = field(init=False)
    _last_discover_persist_time: float = field(default=0.0, init=False, repr=False)

    def __post_init__(self) -> None:
        self.options = self.plan.options
        self.run_dir = self.options.runs_root / self.run_id
        self.raw_dir = self.run_dir / "raw"
        self.normalized_dir = self.run_dir / "normalized"
        self.staging_dir = self.run_dir / "staging"
        self.reports_dir = self.run_dir / "reports"
        self.plan_path = self.run_dir / "plan.json"
        builder = self.adapter_builder or build_adapter_registry
        self.adapters = builder(self.plan)
        self.state = RunStateStore(self.run_dir / "state.sqlite")
        self.geo_shared = GeoSharedStore(self.options.shared_geo_root)


# Stage name → implementation callable.  Must stay in sync with ``STAGES``
# in ``types.py`` (which owns execution order) and the ``stage_*`` functions
# in ``stages.py`` (which own the implementations).  See ``STAGES`` for the
# full stage-addition checklist.
STAGE_FUNCTIONS: dict[str, Callable[[BuildContext], None]] = {
    "prepare": stage_module.stage_prepare,
    "discover": stage_module.stage_discover,
    "extract": stage_module.stage_extract,
    "normalize": stage_module.stage_normalize,
    "materialize": stage_module.stage_materialize,
    "canonicalize": stage_module.stage_canonicalize,
    "reconcile": stage_module.stage_reconcile,
    "enrich": stage_module.stage_enrich,
    "validate": stage_module.stage_validate,
    "package": stage_module.stage_package,
    "changelog": stage_module.stage_changelog,
}


def _build_registry(
    plan: BuildPlan,
    factories: dict[str, Callable[[BuildOptions], SourceAdapter]],
    fallback_errors: dict[str, str] | None = None,
) -> dict[str, SourceAdapter]:
    """Create source adapters from a factory dict for requested domains."""
    requested_domains = {
        recipe.domain for recipe in plan.recipes if recipe.domain.strip()
    }
    adapters: dict[str, SourceAdapter] = {}
    errors: list[str] = []

    for domain in sorted(requested_domains):
        factory = factories.get(domain)
        if factory is not None:
            adapters[domain] = factory(plan.options)
            continue
        errors.append(
            (fallback_errors or {}).get(
                domain,
                f"No built-in source adapter registered for domain '{domain}'.",
            )
        )

    if errors:
        raise NotImplementedError(" ".join(errors))

    return adapters


def build_adapter_registry(plan: BuildPlan) -> dict[str, SourceAdapter]:
    """Create source adapters required by requested domains."""
    return _build_registry(plan, ADAPTER_FACTORIES, UNAVAILABLE_BUILTIN_DOMAINS)


def build_inspection_adapter_registry(plan: BuildPlan) -> dict[str, SourceAdapter]:
    """Create adapters required for non-mutating inspection."""
    return _build_registry(plan, INSPECTION_ADAPTER_FACTORIES)


def _build_datacommons_geo_adapter(options: BuildOptions) -> SourceAdapter:
    """Create the built-in geo adapter from build options."""
    return DataCommonsGeoSourceAdapter(
        dc_instance=options.datacommons_instance,
        api_key=options.datacommons_api_key,
        discovery_parent_batch_size=options.discovery_parent_batch_size,
        wikidata_cache_dir=options.shared_geo_root,
        dc_cache_dir=options.shared_geo_root / "dc_cache",
    )


def _build_datacommons_org_adapter(options: BuildOptions) -> SourceAdapter:
    """Create the built-in org adapter from build options."""
    return DataCommonsOrgSourceAdapter(
        dc_instance=options.datacommons_instance,
        api_key=options.datacommons_api_key,
    )


ADAPTER_FACTORIES.update(
    {
        "geo": _build_datacommons_geo_adapter,
        "org": _build_datacommons_org_adapter,
    }
)
INSPECTION_ADAPTER_FACTORIES.update(
    {
        "geo": _build_datacommons_geo_adapter,
        "org": _build_datacommons_org_adapter,
    }
)


def execute_build(context: BuildContext) -> BuildOutcome:
    """Execute all fixed pipeline stages and return build outcome."""
    stage = "prepare"
    errors: list[str] = []
    releases: list[ReleaseRecord] = []
    context.state.set_meta("last_error", None)

    try:
        for stage in STAGES:
            run_stage(context, stage)
        # In-place rebuild: the outcome reports what this build produced, read
        # straight from the candidates. Publishing to the release ledger is a
        # separate, explicit step (scripts/release/release_data.py).
        releases = build_release_records(
            load_release_candidates(context), run_id=context.run_id
        )
        status = BuildStatus.SUCCESS
    except Exception as exc:
        error_message = f"{type(exc).__name__}: {exc}"
        errors.append(error_message)
        status = BuildStatus.FAILED
        context.state.set_stage_status(stage, "failed")
        context.state.set_meta(
            "last_error",
            LastError(
                stage=stage,
                error_type=type(exc).__name__,
                message=str(exc),
            ).model_dump(mode="json"),
        )
        context.reports_dir.mkdir(parents=True, exist_ok=True)
        write_build_report(context)

    report_paths: dict[str, str] = {}
    build_report = context.reports_dir / "build_report.json"
    if build_report.exists():
        report_paths["build_report"] = str(build_report)

    return BuildOutcome(
        run_id=context.run_id,
        status=status,
        stage=stage,
        releases=releases,
        errors=errors,
        reports=report_paths,
        started_at=context.started_at,
        finished_at=utc_now_iso(),
    )


def run_stage(context: BuildContext, stage: str) -> None:
    """Run one stage and persist stage state and build report."""
    current = context.state.get_stage_status(stage)
    if current == "done":
        return

    context.state.set_stage_status(stage, "running")
    STAGE_FUNCTIONS[stage](context)

    context.state.set_stage_status(stage, "done")
    write_build_report(context)
