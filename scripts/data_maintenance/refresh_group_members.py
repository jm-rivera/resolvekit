"""Refresh group member data from Wikidata SPARQL.

Queries Wikidata for P463 (member of) with P580/P582 (start/end time) per group
listed in src/resolvekit/builder/data/groups.yaml, then prints a unified diff
against the current file. Does NOT auto-write.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml as _yaml  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dep
    _yaml = None  # type: ignore[assignment,invalid-assignment]  # ty:ignore[invalid-assignment]

from resolvekit.calibration.adapters._wikidata_client import sparql_request
from scripts.data_maintenance._common import emit_yaml_diff

_USER_AGENT = "resolvekit-refresh/1.0"
_GROUPS_YAML = (
    Path(__file__).resolve().parent.parent.parent
    / "src/resolvekit/builder/data/groups.yaml"
)

_GROUP_WIKIDATA_QID: dict[str, str] = {
    "EuropeanUnion": "Q458",
    "groups/NATO": "Q7184",
    "undata-geo/G00407000": "Q8908",
    "GroupOf7": "Q192350",
    "groups/G20": "Q19771",
    "groups/ASEAN": "Q7785",
    "groups/BRICS": "Q1054197",
    "groups/MERCOSUR": "Q190551",
    "groups/OPEC": "Q7795",
    "groups/G77": "Q190523",
    # Extend as groups.yaml is populated.
}

_SPARQL_TEMPLATE = """
SELECT ?country ?countryLabel ?iso3 ?startTime ?endTime WHERE {{
  ?country wdt:P463 wd:{qid} ;
           wdt:P298 ?iso3 .
  OPTIONAL {{
    ?country p:P463 ?statement .
    ?statement ps:P463 wd:{qid} .
    OPTIONAL {{ ?statement pq:P580 ?startTime . }}
    OPTIONAL {{ ?statement pq:P582 ?endTime . }}
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en" . }}
}}
"""


@dataclass(frozen=True, slots=True, kw_only=True)
class GroupRefreshSettings:
    group: str | None = None


def _sparql_query(qid: str) -> list[dict[str, Any]]:
    return sparql_request(
        query=_SPARQL_TEMPLATE.format(qid=qid),
        user_agent=_USER_AGENT,
        timeout=30,
    )


def _format_date(wd: str) -> str:
    return wd.lstrip("+").split("T")[0]


def run(*, settings: GroupRefreshSettings) -> None:
    """Query Wikidata for group members and print a unified diff against the checked-in snapshot."""
    if _yaml is None:
        print("pyyaml required: pip install 'resolvekit[data]'", file=sys.stderr)
        sys.exit(1)

    original_text = _GROUPS_YAML.read_text(encoding="utf-8")
    data = _yaml.safe_load(original_text)

    changed = False
    for group in data.get("groups", []):
        gid = group["id"]
        if settings.group and gid != settings.group:
            continue
        qid = _GROUP_WIKIDATA_QID.get(gid)
        if not qid:
            continue
        print(f"Querying Wikidata for {gid} ({qid})...", file=sys.stderr)
        try:
            bindings = _sparql_query(qid)
        except Exception as exc:
            print(f"  error: {exc}", file=sys.stderr)
            time.sleep(0.5)
            continue
        time.sleep(0.5)  # Wikidata rate-limit courtesy: always wait between queries

        new_members = []
        for b in bindings:
            iso3 = b.get("iso3", {}).get("value", "").upper()
            if not iso3:
                continue
            entry: dict[str, str] = {"iso3": iso3}
            if "startTime" in b:
                entry["valid_from"] = _format_date(b["startTime"]["value"])
            if "endTime" in b:
                entry["valid_until"] = _format_date(b["endTime"]["value"])
            new_members.append(entry)
        new_members.sort(key=lambda m: m["iso3"])
        if new_members != group.get("members", []):
            changed = True
            group["members"] = new_members

    if not changed:
        print("No changes detected.", file=sys.stderr)
        return

    new_text = _yaml.dump(
        data,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    emit_yaml_diff(
        original_text,
        new_text,
        fromfile="groups.yaml (current)",
        tofile="groups.yaml (proposed)",
    )


def main() -> None:
    """Entry point for direct invocation; edit settings below to customize."""
    run(settings=GroupRefreshSettings())


if __name__ == "__main__":
    main()
