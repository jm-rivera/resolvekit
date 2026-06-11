"""Release changelog and machine diff report generation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from resolvekit.builder.pipeline.types import load_release_candidates
from resolvekit.builder.sqlite import TABLE_DIFF_SPECS, write_domain_diffs
from resolvekit.builder.utils import ensure_dir, json_write, utc_now_iso

if TYPE_CHECKING:
    from resolvekit.builder.pipeline.core import BuildContext

DIFF_KINDS: tuple[str, ...] = ("added", "removed", "changed")


def stage_changelog(context: BuildContext) -> None:
    """Generate per-release changelog, QA report, and machine diffs."""
    for release in load_release_candidates(context):
        reports_root = release.output_path / "reports"
        ensure_dir(reports_root)
        release_id = release.recipe.module_id

        changelog_lines = [
            f"# Changelog: {release_id} {release.version}",
            "",
            f"- Run ID: `{context.run_id}`",
            f"- Generated at: `{utc_now_iso()}`",
            "",
        ]
        qa_report: dict[str, Any] = {
            "release_id": release_id,
            "version": release.version,
            "run_id": context.run_id,
            "domains": {},
        }
        diff_files_by_table: dict[str, dict[str, Any]] = {
            table: {} for table in TABLE_DIFF_SPECS
        }

        for domain, artifact in release.domain_artifacts.items():
            domain_reports = reports_root / domain
            ensure_dir(domain_reports)

            table_diffs = write_domain_diffs(
                current_db=artifact.sqlite_path,
                previous_db=release.previous_db_path,
                report_dir=domain_reports,
            )

            qa_report["domains"][domain] = _build_domain_qa_report(
                artifact, table_diffs
            )
            for table, payload in table_diffs.items():
                diff_files_by_table[table][domain] = payload

            changelog_lines.extend(
                render_domain_changelog_lines(
                    domain=domain,
                    metrics=artifact.metrics,
                    diffs=table_diffs,
                )
            )

        _write_combined_diffs(
            output_path=release.output_path,
            diff_files_by_table=diff_files_by_table,
        )

        (release.output_path / "changelog.md").write_text(
            "\n".join(changelog_lines), encoding="utf-8"
        )
        json_write(release.output_path / "qa_report.json", qa_report)


def _combined_diff_payload(
    payload_by_domain: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not payload_by_domain:
        return {
            "domains": {},
            "counts": dict.fromkeys(DIFF_KINDS, 0),
            "samples": {kind: [] for kind in DIFF_KINDS},
            "truncated": dict.fromkeys(DIFF_KINDS, False),
        }

    first_payload = next(iter(payload_by_domain.values()))
    counts = {
        kind: sum(
            int(domain_payload.get("counts", {}).get(kind, 0))
            for domain_payload in payload_by_domain.values()
        )
        for kind in DIFF_KINDS
    }
    samples = {
        kind: [
            sample
            for domain_payload in payload_by_domain.values()
            for sample in domain_payload.get("samples", {}).get(kind, [])
        ]
        for kind in DIFF_KINDS
    }
    truncated = {
        kind: any(
            bool(domain_payload.get("truncated", {}).get(kind, False))
            for domain_payload in payload_by_domain.values()
        )
        for kind in DIFF_KINDS
    }

    payload = {
        "domains": payload_by_domain,
        "counts": counts,
        "samples": samples,
        "truncated": truncated,
    }
    if table := first_payload.get("table"):
        payload["table"] = table
    return payload


def _build_domain_qa_report(
    artifact: Any,
    table_diffs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "metrics": artifact.metrics,
        "checks": artifact.qa_checks,
        "diff_counts": {
            table: payload["counts"] for table, payload in table_diffs.items()
        },
    }


def _write_combined_diffs(
    *,
    output_path: Any,
    diff_files_by_table: dict[str, dict[str, Any]],
) -> None:
    for table, payload_by_domain in diff_files_by_table.items():
        payload = _combined_diff_payload(payload_by_domain)
        json_write(output_path / f"diff_{table}.json", payload)


def render_domain_changelog_lines(
    *,
    domain: str,
    metrics: dict[str, float | int],
    diffs: dict[str, dict[str, Any]],
) -> list[str]:
    """Render one domain section for ``changelog.md``."""
    lines = [
        f"## Domain `{domain}`",
        f"- Entities: {int(metrics['entity_count']):,}",
        f"- Names: {int(metrics['names_count']):,}",
        f"- Codes: {int(metrics['codes_count']):,}",
        f"- Relations: {int(metrics['relations_count']):,}",
    ]

    for table, payload in diffs.items():
        counts = payload["counts"]
        lines.append(
            f"- {table}: +{counts['added']} / -{counts['removed']} / ~{counts['changed']}"
        )

    lines.append("")
    return lines
