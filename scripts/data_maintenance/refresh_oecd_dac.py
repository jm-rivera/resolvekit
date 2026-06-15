"""Refresh OECD DAC codelist snapshots.

Fetches four OECD DAC codelists (Recipients, Providers, Channels, Agencies)
via the two-step ASPX POST endpoint and prints a unified diff against the
checked-in snapshot at src/resolvekit/builder/data/oecd_dac.yaml. Does NOT
auto-write.
"""

from __future__ import annotations

import datetime
import http.cookiejar
import json
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml as _yaml  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dep
    _yaml = None  # type: ignore[assignment,invalid-assignment]  # ty:ignore[invalid-assignment]

from scripts.data_maintenance._common import emit_yaml_diff

_OECD_URL = "https://development-finance-codelists.oecd.org/CodesList.aspx"
_OECD_DAC_YAML = (
    Path(__file__).resolve().parent.parent.parent
    / "src/resolvekit/builder/data/oecd_dac.yaml"
)
_CODELIST_IDS: dict[str, str] = {
    "recipients": "13",
    "providers": "5",
    "channels": "3",
    "agencies": "16",
}


@dataclass(frozen=True, slots=True, kw_only=True)
class OecdRefreshSettings:
    codelist: str | None = None
    capture_fixtures: Path | None = None


def fetch_codelist_json(codelist_id: str, *, standard: str = "0") -> bytes:
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [("User-Agent", "resolvekit/refresh-oecd")]

    def hidden(html: str, name: str) -> str:
        m = re.search(rf'<input[^>]*name="{re.escape(name)}"[^>]*value="([^"]*)"', html)
        return m.group(1) if m else ""

    with opener.open(_OECD_URL, timeout=30) as r:
        html = r.read().decode("utf-8", "replace")
    base = {
        "__EVENTARGUMENT": "",
        "__LASTFOCUS": "",
        "__VIEWSTATE": hidden(html, "__VIEWSTATE"),
        "__VIEWSTATEGENERATOR": hidden(html, "__VIEWSTATEGENERATOR"),
        "__VIEWSTATEENCRYPTED": "",
        "__EVENTVALIDATION": hidden(html, "__EVENTVALIDATION"),
        "DDl_codeslist": codelist_id,
        "DDL_CRSTOSSD": standard,
        "Cblstatus$0": "on",
        "Cblstatus$2": "on",
        "tb_search": "",
    }
    p1 = dict(base, __EVENTTARGET="DDl_codeslist")
    with opener.open(
        urllib.request.Request(
            _OECD_URL,
            data=urllib.parse.urlencode(p1).encode(),
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ),
        timeout=30,
    ) as r2:
        h2 = r2.read().decode("utf-8", "replace")
    base["__VIEWSTATE"] = hidden(h2, "__VIEWSTATE")
    base["__VIEWSTATEGENERATOR"] = hidden(h2, "__VIEWSTATEGENERATOR")
    base["__EVENTVALIDATION"] = hidden(h2, "__EVENTVALIDATION")
    p2 = dict(base, __EVENTTARGET="", b_json="JSON")
    with opener.open(
        urllib.request.Request(
            _OECD_URL,
            data=urllib.parse.urlencode(p2).encode(),
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        ),
        timeout=30,
    ) as r3:
        return r3.read()


def _narrative_en_fr(node: dict[str, Any]) -> tuple[str, str | None]:
    """Extract (English, French) from a narrative node."""
    items = node.get("narrative", [])
    en = items[0] if items and isinstance(items[0], str) else ""
    fr = None
    for item in items[1:]:
        if isinstance(item, dict) and item.get("xml:lang") == "fr":
            fr = item.get("#text")
            break
    return en, fr


def _unwrap_rows(raw: bytes) -> tuple[list[dict[str, Any]], str | None]:
    """Unwrap the OECD JSON envelope and return (rows, date_last_modified)."""
    payload = json.loads(raw)
    codelist_list = payload["codelists"]["codelist"]
    if not codelist_list:
        raise ValueError(
            "Expected at least one codelist in payload[codelists][codelist]; got empty list"
        )
    codelist_node = codelist_list[0]
    rows = codelist_node["codelist-items"]["codelist-item"]
    date_last_modified: str | None = payload["codelists"].get("date-last-modified")
    return rows, date_last_modified


def _acronym_en(row: dict[str, Any]) -> str | None:
    node = row.get("acronym")
    if not node:
        return None
    acronym_en, _ = _narrative_en_fr(node)
    return acronym_en or None


def _project_country_like(
    row: dict[str, Any], *, name_en: str, name_fr: str | None
) -> dict[str, Any]:
    """Shape for recipients (id 13) and providers (id 5) — identical column set."""
    return {
        "code": str(row["code"]),
        "name_en": name_en,
        "name_fr": name_fr,
        "iso3": row.get("iso-alpha-3-code") or None,
        "type": row.get("type", ""),
        "dotstatcode": row.get("dotstatcode") or None,
    }


def _project_channel(
    row: dict[str, Any], *, name_en: str, name_fr: str | None
) -> dict[str, Any]:
    return {
        "code": str(row["code"]),
        "name_en": name_en,
        "name_fr": name_fr,
        "category": str(row.get("category", row["code"])),
        "acronym": _acronym_en(row),
    }


def _project_agency(
    row: dict[str, Any], *, name_en: str, name_fr: str | None
) -> dict[str, Any]:
    return {
        "code": str(row["code"]),
        "name_en": name_en,
        "name_fr": name_fr,
        "donor_code": str(row.get("donor-code", "")),
        "acronym": _acronym_en(row),
    }


_PROJECTORS = {
    "13": (_project_country_like, lambda r: r["code"]),
    "5": (_project_country_like, lambda r: r["code"]),
    "3": (_project_channel, lambda r: r["code"]),
    "16": (_project_agency, lambda r: (r["donor_code"], r["code"])),
}


def parse_codelist(raw_json: bytes, *, codelist_id: str) -> list[dict[str, Any]]:
    """Parse raw OECD JSON into a list of dicts matching the YAML row shape."""
    if codelist_id not in _PROJECTORS:
        raise ValueError(
            f"unknown codelist_id: {codelist_id!r}; expected one of {set(_PROJECTORS)}"
        )
    project, sort_key = _PROJECTORS[codelist_id]
    rows, _ = _unwrap_rows(raw_json)

    result: list[dict[str, Any]] = []
    for row in rows:
        if row.get("status", "").lower() != "active":
            continue
        name_en, name_fr = _narrative_en_fr(row.get("name", {}))
        result.append(project(row, name_en=name_en, name_fr=name_fr))
    result.sort(key=sort_key)
    return result


def _regenerate_text(
    fetched: dict[str, list[dict[str, Any]]],
    *,
    query_date: str,
) -> str:
    """Render the YAML document text from fetched codelist data."""
    assert _yaml is not None
    data = {
        "version": 1,
        "generated_from": {
            "oecd_query_date": query_date,
            "source_url": _OECD_URL,
            "aspx_codelist_ids": dict(_CODELIST_IDS),
        },
        "recipients": fetched.get("recipients", []),
        "providers": fetched.get("providers", []),
        "channels": fetched.get("channels", []),
        "agencies": fetched.get("agencies", []),
    }
    return _yaml.dump(
        data, allow_unicode=True, sort_keys=False, default_flow_style=False
    )


# Codelists merged additively (keyed by unique ``code``). Recipients and
# providers are the only codelists where the OECD app drops retired codes
# (graduated territories, dissolved states) that old ODA data still references,
# and the only ones whose ``code`` is unique. Channels and agencies carry
# duplicate rows in the OECD feed (no unique key) and have no historical-
# preservation need, so they pass through from the live fetch unchanged.
_ADDITIVE_CODELISTS = frozenset(
    {_CODELIST_IDS["recipients"], _CODELIST_IDS["providers"]}
)


def _merge_codelist(
    committed: list[dict[str, Any]],
    live: list[dict[str, Any]],
    *,
    codelist_id: str,
) -> tuple[list[dict[str, Any]], dict[str, list[Any]]]:
    """Additively merge committed rows with a freshly fetched live codelist.

    The OECD app publishes only currently-active codes, but old ODA data
    references retired codes (graduated territories, dissolved states). A
    wholesale regenerate would drop every committed code absent from the live
    feed. This merge instead preserves committed-only rows (historical), adds
    live-only rows (new active codes), and adopts live values for shared codes
    while reporting any value change so it is reviewed, not applied silently.

    Keyed by ``code`` — valid only for recipients and providers (see
    ``_ADDITIVE_CODELISTS``).
    """
    _, sort_key = _PROJECTORS[codelist_id]
    committed_by = {r["code"]: r for r in committed}
    live_by = {r["code"]: r for r in live}

    merged = dict(committed_by)
    new_keys: list[Any] = []
    changed: list[Any] = []
    for key, row in live_by.items():
        if key not in committed_by:
            new_keys.append(key)
        elif committed_by[key] != row:
            changed.append((key, committed_by[key], row))
        merged[key] = row
    historical = [key for key in committed_by if key not in live_by]

    report = {"new": new_keys, "changed": changed, "historical": historical}
    return sorted(merged.values(), key=sort_key), report


def run(*, settings: OecdRefreshSettings) -> None:
    """Fetch OECD DAC codelists and print a unified diff against the checked-in snapshot."""
    if _yaml is None:
        print("pyyaml required: pip install 'resolvekit[data]'", file=sys.stderr)
        sys.exit(1)

    if settings.codelist:
        to_fetch = {k: v for k, v in _CODELIST_IDS.items() if v == settings.codelist}
        if not to_fetch:
            print(f"error: unknown codelist id {settings.codelist!r}", file=sys.stderr)
            sys.exit(1)
    else:
        to_fetch = dict(_CODELIST_IDS)

    capture_dir = settings.capture_fixtures
    if capture_dir is not None:
        capture_dir.mkdir(parents=True, exist_ok=True)

    fetched: dict[str, list[dict[str, Any]]] = {}

    for name, cid in to_fetch.items():
        print(f"Fetching {name} (codelist {cid})...", file=sys.stderr)
        try:
            raw = fetch_codelist_json(cid)
        except Exception as exc:
            print(f"error: {exc}", file=sys.stderr)
            continue

        if capture_dir is not None:
            out_path = capture_dir / f"codelist_{cid}.json"
            out_path.write_bytes(raw)
            print(f"  wrote {out_path}", file=sys.stderr)
        else:
            fetched[name] = parse_codelist(raw, codelist_id=cid)

    if capture_dir is not None:
        return

    committed_doc: dict[str, Any] = {}
    if _OECD_DAC_YAML.exists():
        committed_doc = (
            _yaml.safe_load(_OECD_DAC_YAML.read_text(encoding="utf-8")) or {}
        )

    # Merge each codelist against the committed snapshot. Recipients and
    # providers merge additively (preserve historical, add new, report changes);
    # channels and agencies pass through from the live fetch. A codelist not
    # fetched this run (single-codelist refresh, or a fetch error) keeps its
    # committed rows untouched rather than being dropped.
    merged: dict[str, list[dict[str, Any]]] = {}
    for name, cid in _CODELIST_IDS.items():
        committed_rows = committed_doc.get(name) or []
        if cid in _ADDITIVE_CODELISTS:
            live_rows = fetched.get(name, committed_rows)
            rows, report = _merge_codelist(committed_rows, live_rows, codelist_id=cid)
            merged[name] = rows
            print(
                f"{name}: {len(rows)} rows (+{len(report['new'])} new, "
                f"{len(report['historical'])} preserved historical, "
                f"{len(report['changed'])} value change(s))",
                file=sys.stderr,
            )
            for key, old, new in report["changed"]:
                print(f"  CHANGED {name} {key!r}: {old} -> {new}", file=sys.stderr)
        else:
            rows = fetched.get(name, committed_rows)
            merged[name] = rows
            print(f"{name}: {len(rows)} rows (passthrough)", file=sys.stderr)

    query_date = datetime.date.today().isoformat()
    new_text = _regenerate_text(merged, query_date=query_date)

    original_text = (
        _OECD_DAC_YAML.read_text(encoding="utf-8") if _OECD_DAC_YAML.exists() else ""
    )

    if original_text == new_text:
        print("No changes detected.", file=sys.stderr)
        return

    emit_yaml_diff(
        original_text,
        new_text,
        fromfile="oecd_dac.yaml (current)",
        tofile="oecd_dac.yaml (proposed)",
    )


def main() -> None:
    """Entry point for direct invocation; edit settings below to customize."""
    run(settings=OecdRefreshSettings())


if __name__ == "__main__":
    main()
