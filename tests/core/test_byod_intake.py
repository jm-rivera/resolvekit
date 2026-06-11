"""Tests for core/byod/intake.py.

Covers:
- read_records: list, dict, CSV, JSON, JSONL, pandas DataFrame, polars DataFrame
- RecordSchema.resolve: inference, explicit codes (list + dict), attrs="rest",
  missing name, dict-form codes with missing column
- RecordSchema.row_to_record: empty-cell skipping (None, NaN, whitespace)
- normalize_records
- validate_namespace: valid and invalid namespaces
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

import pytest

from resolvekit.core.byod.intake import (
    RecordSchema,
    read_records,
    validate_namespace,
)

# ---------------------------------------------------------------------------
# Minimal stub normalizer (avoids pulling in real normalizers)
# ---------------------------------------------------------------------------


@dataclass
class _IdentityNormalizer:
    """Normalizer that returns values unchanged."""

    def normalize_name(self, name: str) -> str:
        return name.lower()

    def normalize_code(self, system: str, value: str) -> str:
        return value.lower()


_NORM = _IdentityNormalizer()


# ---------------------------------------------------------------------------
# validate_namespace
# ---------------------------------------------------------------------------


class TestValidateNamespace:
    def test_simple_alphanumeric(self):
        assert validate_namespace("mycities") == "mycities"

    def test_with_underscores_and_dashes(self):
        assert validate_namespace("my_cities-v2") == "my_cities-v2"

    def test_starts_with_digit(self):
        assert validate_namespace("2024data") == "2024data"

    def test_path_traversal_raises(self):
        with pytest.raises(ValueError, match="Invalid namespace"):
            validate_namespace("../evil")

    def test_slash_raises(self):
        with pytest.raises(ValueError):
            validate_namespace("foo/bar")

    def test_dot_raises(self):
        with pytest.raises(ValueError):
            validate_namespace("foo.bar")

    def test_leading_dash_raises(self):
        with pytest.raises(ValueError):
            validate_namespace("-start")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            validate_namespace("")

    def test_colon_raises(self):
        with pytest.raises(ValueError):
            validate_namespace("foo:bar")


# ---------------------------------------------------------------------------
# read_records — list input
# ---------------------------------------------------------------------------


class TestReadRecordsList:
    def test_empty_list(self):
        assert read_records([]) == []

    def test_list_of_dicts(self):
        rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
        result = read_records(rows)
        assert result == rows

    def test_returns_copy(self):
        rows = [{"a": 1}]
        result = read_records(rows)
        assert result is not rows


# ---------------------------------------------------------------------------
# read_records — dict (id→record) input
# ---------------------------------------------------------------------------


class TestReadRecordsDict:
    def test_dict_injects_id_key(self):
        data = {"alpha": {"name": "Alpha"}, "beta": {"name": "Beta"}}
        rows = read_records(data)
        assert len(rows) == 2
        ids = {r["__id__"] for r in rows}
        assert ids == {"alpha", "beta"}

    def test_dict_preserves_record_fields(self):
        data = {"key1": {"name": "Widget", "sku": "ABC"}}
        rows = read_records(data)
        assert rows[0]["name"] == "Widget"
        assert rows[0]["sku"] == "ABC"
        assert rows[0]["__id__"] == "key1"


# ---------------------------------------------------------------------------
# read_records — file paths
# ---------------------------------------------------------------------------


class TestReadRecordsCSV:
    def test_csv_round_trip(self, tmp_path: Path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("name,code\nFrance,FRA\nGermany,DEU\n", encoding="utf-8")
        rows = read_records(csv_file)
        assert len(rows) == 2
        assert rows[0]["name"] == "France"
        assert rows[1]["code"] == "DEU"

    def test_csv_str_path(self, tmp_path: Path):
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("x,y\n1,2\n", encoding="utf-8")
        rows = read_records(str(csv_file))
        assert rows == [{"x": "1", "y": "2"}]

    def test_csv_empty_file(self, tmp_path: Path):
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("name,code\n", encoding="utf-8")
        rows = read_records(csv_file)
        assert rows == []


class TestReadRecordsJSON:
    def test_json_array(self, tmp_path: Path):
        json_file = tmp_path / "data.json"
        payload = [
            {"name": "France", "iso3": "FRA"},
            {"name": "Germany", "iso3": "DEU"},
        ]
        json_file.write_text(json.dumps(payload), encoding="utf-8")
        rows = read_records(json_file)
        assert rows == payload

    def test_json_object_injects_id(self, tmp_path: Path):
        json_file = tmp_path / "data.json"
        payload = {"alpha": {"name": "Alpha"}}
        json_file.write_text(json.dumps(payload), encoding="utf-8")
        rows = read_records(json_file)
        assert len(rows) == 1
        assert rows[0]["__id__"] == "alpha"
        assert rows[0]["name"] == "Alpha"


class TestReadRecordsJSONL:
    def test_jsonl_round_trip(self, tmp_path: Path):
        jsonl_file = tmp_path / "data.jsonl"
        lines = [{"name": "France"}, {"name": "Germany"}]
        jsonl_file.write_text("\n".join(json.dumps(r) for r in lines), encoding="utf-8")
        rows = read_records(jsonl_file)
        assert rows == lines

    def test_jsonl_skips_blank_lines(self, tmp_path: Path):
        jsonl_file = tmp_path / "data.jsonl"
        jsonl_file.write_text('{"a":1}\n\n{"a":2}\n', encoding="utf-8")
        rows = read_records(jsonl_file)
        assert len(rows) == 2


class TestReadRecordsBadExtension:
    def test_unsupported_extension_raises(self, tmp_path: Path):
        bad_file = tmp_path / "data.xlsx"
        bad_file.write_bytes(b"dummy")
        with pytest.raises(ValueError, match=r"Unsupported file extension"):
            read_records(bad_file)

    def test_txt_extension_raises(self, tmp_path: Path):
        bad_file = tmp_path / "data.txt"
        bad_file.write_text("x,y\n1,2\n", encoding="utf-8")
        with pytest.raises(ValueError):
            read_records(bad_file)


# ---------------------------------------------------------------------------
# read_records — pandas DataFrame
# ---------------------------------------------------------------------------


class TestReadRecordsPandas:
    def test_pandas_dataframe(self):
        pd = pytest.importorskip("pandas")
        df = pd.DataFrame([{"name": "France", "iso3": "FRA"}])
        rows = read_records(df)
        assert len(rows) == 1
        assert rows[0]["name"] == "France"

    def test_pandas_nan_preserved(self):
        """NaN cells in the DataFrame are preserved; empty-cell skip is in row_to_record."""
        pd = pytest.importorskip("pandas")
        df = pd.DataFrame([{"name": "France", "code": float("nan")}])
        rows = read_records(df)
        # NaN survives read_records; row_to_record will filter it
        assert math.isnan(rows[0]["code"])


# ---------------------------------------------------------------------------
# read_records — polars DataFrame
# ---------------------------------------------------------------------------


class TestReadRecordsPolars:
    def test_polars_dataframe(self):
        pl = pytest.importorskip("polars")
        df = pl.DataFrame({"name": ["France"], "iso3": ["FRA"]})
        rows = read_records(df)
        assert rows == [{"name": "France", "iso3": "FRA"}]

    def test_polars_null_preserved(self):
        pl = pytest.importorskip("polars")
        df = pl.DataFrame({"name": ["France"], "code": [None]})
        rows = read_records(df)
        assert rows[0]["code"] is None


# ---------------------------------------------------------------------------
# RecordSchema.resolve — basic cases
# ---------------------------------------------------------------------------


_SAMPLE_ROWS = [{"label": "Widget", "sku": "ABC", "price": 9.99}]


class TestRecordSchemaResolve:
    def test_missing_name_raises(self):
        with pytest.raises((ValueError, TypeError)):
            RecordSchema.resolve(_SAMPLE_ROWS, name="")

    def test_minimal_schema(self):
        schema = RecordSchema.resolve(_SAMPLE_ROWS, name="label")
        assert schema.names == ["label"]
        assert schema.id is None
        assert schema.codes == {}
        assert schema.aliases == []
        assert schema.attrs is None

    def test_explicit_id(self):
        schema = RecordSchema.resolve(_SAMPLE_ROWS, name="label", id="sku")
        assert schema.id == "sku"

    def test_explicit_codes_list(self):
        rows = [{"name": "France", "iso3": "FRA", "iso2": "FR"}]
        schema = RecordSchema.resolve(rows, name="name", codes=["iso3", "iso2"])
        assert schema.codes == {"iso3": "iso3", "iso2": "iso2"}

    def test_explicit_codes_dict_override(self):
        rows = [{"name": "France", "country_code": "FRA"}]
        schema = RecordSchema.resolve(rows, name="name", codes={"iso3": "country_code"})
        assert schema.codes == {"iso3": "country_code"}

    def test_codes_dict_missing_column_raises(self):
        """dict-form codes with a column absent from rows → ValueError."""
        rows = [{"name": "France", "iso3": "FRA"}]
        with pytest.raises(ValueError, match="country_code"):
            RecordSchema.resolve(rows, name="name", codes={"iso3": "country_code"})

    def test_codes_list_missing_column_raises(self):
        """list-form codes with a missing column → ValueError."""
        rows = [{"name": "France"}]
        with pytest.raises(ValueError, match="iso3"):
            RecordSchema.resolve(rows, name="name", codes=["iso3"])

    def test_attrs_rest(self):
        schema = RecordSchema.resolve(_SAMPLE_ROWS, name="label", attrs="rest")
        assert schema.attrs == "rest"

    def test_attrs_list(self):
        schema = RecordSchema.resolve(_SAMPLE_ROWS, name="label", attrs=["price"])
        assert schema.attrs == ["price"]

    def test_attrs_none_drops_unlisted(self):
        schema = RecordSchema.resolve(_SAMPLE_ROWS, name="label")
        assert schema.attrs is None

    def test_known_systems_infers_codes(self):
        rows = [{"name": "France", "iso3": "FRA", "wikidata": "Q142"}]
        schema = RecordSchema.resolve(
            rows, name="name", known_systems=frozenset({"iso3", "wikidata"})
        )
        assert "iso3" in schema.codes
        assert "wikidata" in schema.codes

    def test_known_systems_not_inferred_when_codes_explicit(self):
        """When codes is supplied explicitly, known_systems inference is skipped."""
        rows = [{"name": "France", "iso3": "FRA", "wikidata": "Q142"}]
        schema = RecordSchema.resolve(
            rows,
            name="name",
            codes=["iso3"],
            known_systems=frozenset({"wikidata"}),
        )
        # wikidata should NOT appear — explicit codes= was given
        assert "wikidata" not in schema.codes
        assert schema.codes == {"iso3": "iso3"}

    def test_name_never_becomes_attr_with_rest(self):
        rows = [{"label": "Widget", "price": 9.99}]
        schema = RecordSchema.resolve(rows, name="label", attrs="rest")
        record = schema.row_to_record(rows[0], normalizer=_NORM)
        assert "label" not in record.attrs

    def test_entity_type_literal(self):
        """entity_type value absent from columns → treated as a literal."""
        rows = [{"name": "France"}]
        schema = RecordSchema.resolve(rows, name="name", entity_type="geo.country")
        assert schema.entity_type_is_literal is True

    def test_entity_type_column(self):
        rows = [{"name": "France", "type": "country"}]
        schema = RecordSchema.resolve(rows, name="name", entity_type="type")
        assert schema.entity_type_is_literal is False


# ---------------------------------------------------------------------------
# RecordSchema.resolve — columns= rename
# ---------------------------------------------------------------------------


class TestRecordSchemaColumnsRename:
    def test_name_column_renamed(self):
        """columns={"name": "country_name"} remaps the name role to the actual column."""
        rows = [{"country_name": "France"}]
        schema = RecordSchema.resolve(
            rows, name="name", columns={"name": "country_name"}
        )
        assert schema.names == ["country_name"]

    def test_list_form_codes_system_key_preserved(self):
        """list-form codes rename: system key stays logical token; column is renamed."""
        rows = [{"name": "France", "iso3_col": "FRA"}]
        schema = RecordSchema.resolve(
            rows, name="name", codes=["iso3"], columns={"iso3": "iso3_col"}
        )
        # System key must remain "iso3", column renamed to "iso3_col".
        assert schema.codes == {"iso3": "iso3_col"}

    def test_list_form_codes_renamed_target_absent_raises(self):
        """list-form codes rename where the target column is absent → ValueError."""
        rows = [{"name": "France"}]
        with pytest.raises(ValueError, match="iso3_col"):
            RecordSchema.resolve(
                rows, name="name", codes=["iso3"], columns={"iso3": "iso3_col"}
            )


# ---------------------------------------------------------------------------
# RecordSchema.row_to_record — empty-cell skipping
# ---------------------------------------------------------------------------


class TestRowToRecord:
    def _schema(self, **kwargs: object) -> RecordSchema:
        rows = [{"label": "Widget", "sku": "ABC", "price": 9.99}]
        return RecordSchema.resolve(rows, name="label", **kwargs)  # type: ignore[arg-type]

    def test_none_value_dropped_from_codes(self):
        rows = [{"name": "France", "iso3": None}]
        schema = RecordSchema.resolve(rows, name="name", codes=["iso3"])
        record = schema.row_to_record(rows[0], normalizer=_NORM)
        assert "iso3" not in record.codes

    def test_nan_value_dropped_from_codes(self):
        rows = [{"name": "France", "iso3": float("nan")}]
        schema = RecordSchema.resolve(rows, name="name", codes=["iso3"])
        record = schema.row_to_record(rows[0], normalizer=_NORM)
        assert "iso3" not in record.codes

    def test_empty_string_dropped_from_codes(self):
        rows = [{"name": "France", "iso3": "   "}]
        schema = RecordSchema.resolve(rows, name="name", codes=["iso3"])
        record = schema.row_to_record(rows[0], normalizer=_NORM)
        assert "iso3" not in record.codes

    def test_none_dropped_from_attrs(self):
        rows = [{"label": "Widget", "price": None}]
        schema = RecordSchema.resolve(rows, name="label", attrs="rest")
        record = schema.row_to_record(rows[0], normalizer=_NORM)
        assert "price" not in record.attrs

    def test_nan_dropped_from_attrs(self):
        rows = [{"label": "Widget", "price": float("nan")}]
        schema = RecordSchema.resolve(rows, name="label", attrs="rest")
        record = schema.row_to_record(rows[0], normalizer=_NORM)
        assert "price" not in record.attrs

    def test_entity_id_seed_from_id_col(self):
        rows = [{"id": "w1", "label": "Widget"}]
        schema = RecordSchema.resolve(rows, name="label", id="id")
        record = schema.row_to_record(rows[0], normalizer=_NORM)
        assert record.entity_id_seed == "w1"

    def test_entity_id_seed_from_injected_id(self):
        """dict-key __id__ promoted when no explicit id column."""
        rows = [{"__id__": "alpha", "label": "Widget"}]
        schema = RecordSchema.resolve(rows, name="label")
        record = schema.row_to_record(rows[0], normalizer=_NORM)
        assert record.entity_id_seed == "alpha"

    def test_entity_id_seed_none_when_absent(self):
        rows = [{"label": "Widget"}]
        schema = RecordSchema.resolve(rows, name="label")
        record = schema.row_to_record(rows[0], normalizer=_NORM)
        assert record.entity_id_seed is None

    def test_attrs_rest_keeps_unlisted(self):
        rows = [{"label": "Widget", "sku": "ABC", "price": 9.99}]
        schema = RecordSchema.resolve(rows, name="label", codes=["sku"], attrs="rest")
        record = schema.row_to_record(rows[0], normalizer=_NORM)
        assert "price" in record.attrs
        # sku is a code, not an attr
        assert "sku" not in record.attrs

    def test_attrs_none_drops_unlisted(self):
        rows = [{"label": "Widget", "sku": "ABC", "price": 9.99}]
        schema = RecordSchema.resolve(rows, name="label", codes=["sku"])
        record = schema.row_to_record(rows[0], normalizer=_NORM)
        assert record.attrs == {}

    def test_entity_type_from_column(self):
        rows = [{"name": "France", "type": "country"}]
        schema = RecordSchema.resolve(rows, name="name", entity_type="type")
        record = schema.row_to_record(rows[0], normalizer=_NORM)
        assert record.entity_type == "country"

    def test_entity_type_literal_stamped(self):
        rows = [{"name": "France"}]
        schema = RecordSchema.resolve(rows, name="name", entity_type="geo.country")
        record = schema.row_to_record(rows[0], normalizer=_NORM)
        assert record.entity_type == "geo.country"

    def test_aliases_collected(self):
        rows = [{"name": "France", "local": "République française"}]
        schema = RecordSchema.resolve(rows, name="name", aliases="local")
        record = schema.row_to_record(rows[0], normalizer=_NORM)
        assert record.aliases == ["République française"]


# ---------------------------------------------------------------------------
# Full round-trip — all formats produce equivalent records
# ---------------------------------------------------------------------------


class TestRoundTrip:
    """Verify that every intake format produces the same logical rows."""

    _EXPECTED: ClassVar[list[dict[str, str]]] = [
        {"name": "France", "iso3": "FRA"},
        {"name": "Germany", "iso3": "DEU"},
    ]

    def _assert_same(self, rows: list[dict]) -> None:
        assert len(rows) == 2
        assert rows[0]["name"] == "France"
        assert rows[0]["iso3"] == "FRA"
        assert rows[1]["name"] == "Germany"
        assert rows[1]["iso3"] == "DEU"

    def test_list_of_dicts(self):
        self._assert_same(read_records(self._EXPECTED))

    def test_csv(self, tmp_path: Path):
        f = tmp_path / "d.csv"
        f.write_text("name,iso3\nFrance,FRA\nGermany,DEU\n", encoding="utf-8")
        self._assert_same(read_records(f))

    def test_json_array(self, tmp_path: Path):
        f = tmp_path / "d.json"
        f.write_text(json.dumps(self._EXPECTED), encoding="utf-8")
        self._assert_same(read_records(f))

    def test_jsonl(self, tmp_path: Path):
        f = tmp_path / "d.jsonl"
        f.write_text("\n".join(json.dumps(r) for r in self._EXPECTED), encoding="utf-8")
        self._assert_same(read_records(f))

    def test_pandas_equivalent(self):
        pd = pytest.importorskip("pandas")
        df = pd.DataFrame(self._EXPECTED)
        self._assert_same(read_records(df))

    def test_polars_equivalent(self):
        pl = pytest.importorskip("polars")
        df = pl.DataFrame({"name": ["France", "Germany"], "iso3": ["FRA", "DEU"]})
        self._assert_same(read_records(df))
