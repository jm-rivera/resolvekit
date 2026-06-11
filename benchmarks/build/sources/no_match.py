"""Curated queries that intentionally match nothing — tests abstention."""

from __future__ import annotations

from typing import TYPE_CHECKING

from benchmarks.core.kernel import Query

if TYPE_CHECKING:
    from resolvekit.core.store import EntityStore


_QUERIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "fictional",
        (
            "Zorbistan",
            "Fictionlandia",
            "Atlantica",
            "Wakanda",
            "Genovia",
            "Latveria",
            "Ruritania",
            "San Theodoros",
            "Freedonia",
            "Elbonia",
            "Kraplakistan",
            "Molvania",
        ),
    ),
    (
        "generic",
        (
            "the weather",
            "blue sky",
            "n/a",
            "null",
            "unknown",
            "not applicable",
            "none",
            "undefined",
            "TBD",
            "pending",
            "various",
            "others",
            "worldwide",
            "international",
        ),
    ),
    (
        "code_junk",
        ("XX", "000", "????", "---", "###", "ZZ9", "999", "00"),
    ),
    (
        "keyboard",
        (
            "qwerty",
            "asdfghjkl",
            "zxcvbnm",
            "lkjhgfdsa",
            "mnbvcxz",
            "xkcd",
            "lorem ipsum",
            "foo bar",
            "test string",
        ),
    ),
)


def build(
    *,
    store: EntityStore,
    limit: int | None = None,
    seed: int = 42,
) -> list[Query]:
    del store, seed
    rows: list[Query] = []
    for note, queries in _QUERIES:
        for query in queries:
            rows.append(
                Query(
                    query_id="",
                    text=query,
                    expected_ids=(),
                    language="en",
                    entity_type="country",
                    category="no_match",
                    difficulty="easy",
                    capabilities=("abstention",),
                    source="curated",
                    notes=note,
                )
            )
            if limit is not None and len(rows) >= limit:
                return rows
    return rows
