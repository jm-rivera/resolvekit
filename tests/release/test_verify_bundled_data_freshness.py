"""Tests for the _verify_yaml_freshness helper in verify_bundled_data.py.

Pins: fresh → [], stale → message, bare date.date object handled,
missing key → message (no exception).  Injects `today` for determinism.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from scripts.release.verify_bundled_data import _verify_yaml_freshness

# ---------------------------------------------------------------------------
# Helper: write a minimal YAML with generated_from
# ---------------------------------------------------------------------------


def _write_yaml(path: Path, date_key: str, date_value: object) -> None:
    """Write a YAML with generated_from[date_key] = date_value."""
    payload = {"generated_from": {date_key: date_value}}
    path.write_text(yaml.dump(payload))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_fresh_yaml_returns_no_messages(tmp_path) -> None:
    """A date well within the window produces an empty list."""
    yaml_file = tmp_path / "data.yaml"
    today = date(2026, 5, 26)
    recent = date(2026, 4, 1)  # 55 days old, limit 365
    _write_yaml(yaml_file, "my_date", recent.isoformat())

    result = _verify_yaml_freshness(
        yaml_file, date_key="my_date", max_age_days=365, today=today
    )

    assert result == []


def test_stale_yaml_returns_message(tmp_path) -> None:
    """A date older than max_age_days produces exactly one message."""
    yaml_file = tmp_path / "data.yaml"
    today = date(2026, 5, 26)
    stale = date(2023, 1, 1)  # >3 years old, limit 1095 days
    _write_yaml(yaml_file, "oecd_query_date", stale.isoformat())

    result = _verify_yaml_freshness(
        yaml_file, date_key="oecd_query_date", max_age_days=1095, today=today
    )

    assert len(result) == 1
    assert "oecd_query_date" in result[0]
    assert "please refresh" in result[0]


def test_stale_date_object_handled(tmp_path) -> None:
    """A bare datetime.date (as PyYAML parses groups.yaml) is accepted."""
    yaml_file = tmp_path / "groups.yaml"
    today = date(2026, 5, 26)
    # PyYAML writes bare dates without quotes — round-trip via yaml.dump
    # to confirm we exercise the datetime.date branch.
    bare_date = date(2024, 1, 1)  # >365 days old
    payload = {"generated_from": {"wikidata_query_date": bare_date}}
    yaml_file.write_text(yaml.dump(payload))

    loaded = yaml.safe_load(yaml_file.read_text())
    assert isinstance(loaded["generated_from"]["wikidata_query_date"], date)

    result = _verify_yaml_freshness(
        yaml_file, date_key="wikidata_query_date", max_age_days=365, today=today
    )

    assert len(result) == 1
    assert "wikidata_query_date" in result[0]


def test_missing_date_key_returns_message(tmp_path) -> None:
    """A YAML without the expected key produces a message, not an exception."""
    yaml_file = tmp_path / "data.yaml"
    payload = {"generated_from": {"some_other_key": "2026-01-01"}}
    yaml_file.write_text(yaml.dump(payload))

    result = _verify_yaml_freshness(
        yaml_file,
        date_key="oecd_query_date",
        max_age_days=1095,
        today=date(2026, 5, 26),
    )

    assert len(result) == 1
    assert "oecd_query_date" in result[0]
    assert "not found" in result[0]


def test_missing_yaml_returns_message(tmp_path) -> None:
    """A non-existent YAML produces a message, not an exception."""
    missing = tmp_path / "nonexistent.yaml"

    result = _verify_yaml_freshness(
        missing, date_key="oecd_query_date", max_age_days=1095, today=date(2026, 5, 26)
    )

    assert len(result) == 1
    assert "not found" in result[0]


def test_exactly_at_age_limit_is_fresh(tmp_path) -> None:
    """A date exactly max_age_days old is still considered fresh (boundary)."""
    yaml_file = tmp_path / "data.yaml"
    today = date(2026, 5, 26)
    max_age_days = 365
    boundary_date = date(2025, 5, 26)  # exactly 365 days ago
    _write_yaml(yaml_file, "query_date", boundary_date.isoformat())

    result = _verify_yaml_freshness(
        yaml_file, date_key="query_date", max_age_days=max_age_days, today=today
    )

    assert result == []


def test_one_day_over_limit_is_stale(tmp_path) -> None:
    """A date max_age_days+1 old crosses into stale territory."""
    yaml_file = tmp_path / "data.yaml"
    today = date(2026, 5, 26)
    max_age_days = 365
    # 366 days before today
    stale_date = date(2025, 5, 25)
    _write_yaml(yaml_file, "query_date", stale_date.isoformat())

    result = _verify_yaml_freshness(
        yaml_file, date_key="query_date", max_age_days=max_age_days, today=today
    )

    assert len(result) == 1
