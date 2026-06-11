"""CI assertion that the committed geo.countries pack ships with prominence.

Prominence enrichment runs out-of-band (``scripts/build/enrich_prominence.py``)
and writes into the shared geo staging store; a plain ``build_data`` rebuild
that skips the enrich step silently produces a countries pack with **zero**
prominence, dropping the popularity prior the resolver and ``suggest()`` rely
on. That regression shipped once already. This guard makes it loud: the
committed pack must carry prominence on the country tier.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

_COUNTRIES_DB = (
    Path(__file__).resolve().parents[1]
    / "src/resolvekit/_data/geo/countries/entities.sqlite"
)

# 238/239 countries carry prominence today (only entities with no Wikidata
# sitelink/population signal are missing it). The floor sits well below that
# so ordinary signal drift is fine, but a wholesale 0% regression fails.
_MIN_COVERAGE = 0.90


def _country_prominence_coverage() -> tuple[int, int]:
    """Return (with_prominence, total) for the geo.country tier."""
    conn = sqlite3.connect(f"file:{_COUNTRIES_DB}?mode=ro", uri=True)
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM entities WHERE entity_type = 'geo.country'"
        ).fetchone()[0]
        with_prom = conn.execute(
            """
            SELECT COUNT(*) FROM entities
            WHERE entity_type = 'geo.country'
              AND json_extract(attrs_json, '$.prominence') IS NOT NULL
            """
        ).fetchone()[0]
    finally:
        conn.close()
    return with_prom, total


def test_committed_countries_pack_has_prominence() -> None:
    with_prom, total = _country_prominence_coverage()
    assert total > 0, f"No geo.country entities found in {_COUNTRIES_DB}"
    coverage = with_prom / total
    assert coverage >= _MIN_COVERAGE, (
        f"Committed geo.countries pack has prominence on only {with_prom}/{total} "
        f"entities ({coverage:.1%} < {_MIN_COVERAGE:.0%}). The enrich step was likely "
        "skipped on the last rebuild. Regenerate with the 3-step flow: "
        "build_data -> `uv run python -m scripts.build.enrich_prominence` -> build_data."
    )


def test_committed_countries_prominence_is_normalized() -> None:
    """Prominence is a min-max-normalized [0, 1] signal — guard the range."""
    conn = sqlite3.connect(f"file:{_COUNTRIES_DB}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT entity_id, attrs_json FROM entities WHERE entity_type = 'geo.country'"
        ).fetchall()
    finally:
        conn.close()
    for entity_id, attrs_json in rows:
        prominence = json.loads(attrs_json).get("prominence")
        if prominence is None:
            continue
        assert 0.0 <= prominence <= 1.0, (
            f"{entity_id} has out-of-range prominence {prominence!r}; expected [0, 1]."
        )
