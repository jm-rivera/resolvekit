"""Guard test: country benchmark datasets must not contain subnational entities.

For every row in geo_countries_en and geo_countries_multilingual, the
expected entity must be either:

  (a) in the ``country/`` namespace (ISO 3166-1 alpha-3 country codes and
      dependent territories — retained even if the entity store stores them
      as geo.admin1), or
  (b) stored as ``geo.country`` in the shared entity store.

Any other entity type (geo.admin1 / admin2 / admin3 / admin4 / admin5 /
geo.city) is contamination and must not appear.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

_DATA_DIR = Path(__file__).parent.parent.parent / "benchmarks" / "data"
_SQLITE_PATH = Path("data/build/shared/geo/entities.sqlite")

_SUBNATIONAL_TYPES = frozenset(
    {
        "geo.admin1",
        "geo.admin2",
        "geo.admin3",
        "geo.admin4",
        "geo.admin5",
        "geo.city",
    }
)


def _load_store_types() -> dict[str, str]:
    """Return {entity_id: entity_type} for the shared SQLite store."""
    if not _SQLITE_PATH.exists():
        return {}
    conn = sqlite3.connect(str(_SQLITE_PATH))
    try:
        rows = conn.execute("SELECT entity_id, entity_type FROM entities").fetchall()
        return dict(rows)
    finally:
        conn.close()


def _check_contamination(
    parquet_path: Path,
    store_types: dict[str, str],
) -> list[str]:
    """Return a list of contamination violation descriptions.

    A row is contaminated when its first expected_id:
    - is NOT in the ``country/`` namespace, AND
    - is stored in the entity store with a subnational entity_type.
    """
    try:
        import polars as pl
    except ImportError:
        pytest.skip("polars not available")

    df = pl.read_parquet(parquet_path)
    violations: list[str] = []
    for row in df.iter_rows(named=True):
        eids = row.get("expected_ids") or []
        if not eids:
            continue
        eid = eids[0]
        if eid.startswith("country/"):
            # country/ namespace is always legitimate (ISO 3166-1 territories).
            continue
        stype = store_types.get(eid, "")
        if stype in _SUBNATIONAL_TYPES:
            violations.append(
                f"query={row['query']!r} expected_id={eid!r} store_type={stype!r}"
            )
    return violations


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def store_types() -> dict[str, str]:
    return _load_store_types()


@pytest.mark.skipif(
    not _DATA_DIR.joinpath("geo_countries_en.parquet").exists(),
    reason="geo_countries_en.parquet not found",
)
def test_geo_countries_en_has_no_subnational_contamination(
    store_types: dict[str, str],
) -> None:
    """Every entity_type=country row in geo_countries_en resolves to a country/ ID
    or is stored as geo.country; no subnational entities must appear.
    """
    path = _DATA_DIR / "geo_countries_en.parquet"
    violations = _check_contamination(path, store_types)
    assert violations == [], (
        f"geo_countries_en contains {len(violations)} contaminated row(s):\n"
        + "\n".join(f"  {v}" for v in violations[:20])
        + ("\n  ... (truncated)" if len(violations) > 20 else "")
    )


@pytest.mark.skipif(
    not _DATA_DIR.joinpath("geo_countries_multilingual.parquet").exists(),
    reason="geo_countries_multilingual.parquet not found",
)
def test_geo_countries_multilingual_has_no_subnational_contamination(
    store_types: dict[str, str],
) -> None:
    """Every entity_type=country row in geo_countries_multilingual resolves to a
    country/ ID or is stored as geo.country; no subnational entities must appear.
    """
    path = _DATA_DIR / "geo_countries_multilingual.parquet"
    violations = _check_contamination(path, store_types)
    assert violations == [], (
        f"geo_countries_multilingual contains {len(violations)} contaminated row(s):\n"
        + "\n".join(f"  {v}" for v in violations[:20])
        + ("\n  ... (truncated)" if len(violations) > 20 else "")
    )


@pytest.mark.skipif(
    not _DATA_DIR.joinpath("geo_countries_en.parquet").exists(),
    reason="geo_countries_en.parquet not found",
)
def test_geo_countries_en_retains_iso_territories(
    store_types: dict[str, str],
) -> None:
    """ISO 3166-1 dependent territories stored as geo.admin1 must be retained.

    American Samoa (ASM), Guam (GUM), Guadeloupe (GLP), and Christmas Island
    (CXR) are ISO 3166-1 entries that the entity store stores as geo.admin1.
    They must appear in the EN dataset via their country/ IDs.
    """
    try:
        import polars as pl
    except ImportError:
        pytest.skip("polars not available")

    path = _DATA_DIR / "geo_countries_en.parquet"
    df = pl.read_parquet(path)
    all_ids = df["expected_ids"].explode().unique().to_list()

    required = {"country/ASM", "country/GUM", "country/GLP", "country/CXR"}
    missing = required - set(all_ids)
    assert not missing, (
        f"geo_countries_en is missing ISO 3166-1 territories: {sorted(missing)}"
    )


@pytest.mark.skipif(
    not (_DATA_DIR / "geo_countries_en.parquet").exists(),
    reason="geo_countries_en.parquet not found",
)
def test_wikidata_builder_drops_non_country_namespace_ids() -> None:
    """The wikidata builder must not emit rows whose expected_id is not country/.

    This test exercises the builder with a mock store that returns a non-country/
    entity for a Wikidata QID — simulating what happens when Q10864048 (admin1)
    or Q515 (city) bindings resolve to geo.admin1 entities in the store.
    The builder's ``country/``-prefix guard must silently drop them.
    """
    from unittest.mock import MagicMock, patch

    from benchmarks.build.sources.wikidata import build

    # Store where Q999 resolves to a non-country/ entity (as a contaminated admin1 would)
    store = MagicMock()

    def lookup_code(system: str, value: str) -> list[str]:
        mapping = {
            ("wikidata", "q999"): ["wikidataId/Q999"],  # non-country/ (would be admin1)
            ("wikidata", "q30"): ["country/USA"],  # legit country
        }
        return mapping.get((system, value), [])

    store.lookup_code.side_effect = lookup_code

    import json

    bindings = [
        {
            "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q999"},
            "itemLabel": {"type": "literal", "value": "Fake Province"},
        },
        {
            "item": {"type": "uri", "value": "http://www.wikidata.org/entity/Q30"},
            "itemLabel": {"type": "literal", "value": "United States of America"},
        },
    ]
    body = json.dumps({"results": {"bindings": bindings}}).encode("utf-8")
    resp = MagicMock()
    resp.read.return_value = body
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)

    with (
        patch(
            "resolvekit.calibration.adapters._wikidata_client.urllib.request.urlopen",
            return_value=resp,
        ),
        patch("benchmarks.build.sources.wikidata.time.sleep"),
    ):
        rows = build(store=store, languages=["en"])

    entity_ids = {r.expected_ids[0] for r in rows}
    assert "wikidataId/Q999" not in entity_ids, (
        "wikidata builder leaked a non-country/ entity (admin1/city contamination)"
    )
    assert "country/USA" in entity_ids, (
        "wikidata builder dropped a legitimate country/ entity"
    )
