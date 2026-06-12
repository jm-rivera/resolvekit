"""Fetch Wikidata English alt-labels for country entities via VALUES queries.

Builds a batched VALUES-over-QIDs SPARQL query from the ``wikidataId`` codes
already present in the chunk, fetches English alt-labels directly (no
transitive entity-type walk), applies an English-precision heuristic filter,
and returns alias rows keyed by entity id with ``source='wikidata'``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from resolvekit.calibration.adapters._wikidata_client import sparql_request

logger = logging.getLogger(__name__)

USER_AGENT = "ResolveKit/1.0 (alias-enrich; https://github.com/jm-rivera/resolvekit)"

_QID_URI_PREFIX = "http://www.wikidata.org/entity/"
_QID_RE = re.compile(r"^Q[1-9][0-9]*$")

_ALIASES_TEMPLATE = """\
SELECT ?item ?altLabel WHERE {{
  VALUES ?item {{ {values} }}
  ?item skos:altLabel ?altLabel . FILTER(LANG(?altLabel) = "en")
}}
"""


def fetch_wikidata_en_aliases(
    *,
    codes_by_entity: dict[str, list[dict[str, Any]]],
    foreign_names_by_entity: dict[str, set[str]] | None = None,
    cache_dir: Path | None = None,
    user_agent: str = USER_AGENT,
    batch_size: int = 1000,
    request_delay: float = 0.5,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch English Wikidata alt-labels for the countries in this chunk.

    Builds a VALUES query from the ``wikidataId`` codes in
    ``codes_by_entity``, fetches English alt-labels in batches (mirroring
    :func:`~resolvekit.builder.sources.wikidata.sitelinks.fetch_sitelinks_by_qid`),
    applies the English-precision filter, and returns alias rows keyed by
    entity id with ``source='wikidata'``.

    Returns ``{}`` immediately when no ``wikidataId`` codes are found in the
    chunk (legitimate no-op — not a failure). Raises ``RuntimeError`` if the
    fetch returns empty bindings for a non-empty QID list (network failure).

    Cache: when ``cache_dir`` is given, results are staged to a JSON file
    keyed on the sorted QID set; subsequent calls with the same QIDs read
    from cache without hitting the network.
    """
    qid_to_dcid = _qid_to_dcid(codes_by_entity)
    if not qid_to_dcid:
        return {}

    foreign_names = foreign_names_by_entity or {}
    valid_qids = sorted(qid_to_dcid)

    bindings = _fetch_or_load(
        qids=valid_qids,
        cache_dir=cache_dir,
        user_agent=user_agent,
        batch_size=batch_size,
        request_delay=request_delay,
    )

    out: dict[str, list[dict[str, Any]]] = {}
    for binding in bindings:
        item_uri = binding.get("item", {}).get("value", "")
        alt_label = binding.get("altLabel", {}).get("value", "")

        if not item_uri or not alt_label:
            continue

        qid = _parse_qid(item_uri)
        if qid is None:
            continue

        dcid = qid_to_dcid.get(qid.lower())
        if dcid is None or not dcid.startswith("country/"):
            continue

        if not _is_precise_en_alias(alt_label, endonyms=foreign_names.get(dcid, set())):
            continue

        out.setdefault(dcid, []).append(_alias_entry(alt_label))

    return out


def _fetch_or_load(
    *,
    qids: list[str],
    cache_dir: Path | None,
    user_agent: str,
    batch_size: int,
    request_delay: float,
) -> list[dict[str, Any]]:
    """Return bindings from cache if available, else fetch and optionally cache."""
    if cache_dir is not None:
        cache_file = _cache_path(cache_dir, qids)
        if cache_file.exists():
            logger.info("Wikidata alias fetch: reading cache from %s", cache_file)
            return json.loads(cache_file.read_text(encoding="utf-8"))

    bindings = _fetch_batched(
        qids=qids,
        user_agent=user_agent,
        batch_size=batch_size,
        request_delay=request_delay,
    )

    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = _cache_path(cache_dir, qids)
        cache_file.write_text(
            json.dumps(bindings, ensure_ascii=True),
            encoding="utf-8",
        )
        logger.info(
            "Wikidata alias fetch: cached %d bindings to %s",
            len(bindings),
            cache_file,
        )

    return bindings


def _fetch_batched(
    *,
    qids: list[str],
    user_agent: str,
    batch_size: int,
    request_delay: float,
) -> list[dict[str, Any]]:
    """Fetch alt-label bindings in batches."""
    # QIDs stored lower-case; SPARQL VALUES needs canonical upper-case form.
    canonical = [q.upper() for q in qids]

    out: list[dict[str, Any]] = []
    n_batches = 0
    n_empty_batches = 0
    for i in range(0, len(canonical), batch_size):
        batch = canonical[i : i + batch_size]
        values = " ".join(f"wd:{q}" for q in batch)
        query = _ALIASES_TEMPLATE.format(values=values)

        bindings = sparql_request(query=query, user_agent=user_agent, timeout=60)
        n_batches += 1
        if not bindings:
            # Empty response after internal retries: either no English altLabels exist
            # or WDQS returned empty. Treat as "no aliases" for this batch.
            logger.warning(
                "Wikidata alias fetch: batch %d (%d QIDs) returned no bindings",
                i // batch_size + 1,
                len(batch),
            )
            n_empty_batches += 1
            continue
        out.extend(bindings)

        if request_delay > 0 and i + batch_size < len(canonical):
            time.sleep(request_delay)

    # Multi-batch fetch with all-empty response: raise loud so the chunk is retried.
    # A single empty batch plausibly means "no aliases"; every batch returning empty
    # is more consistent with a WDQS outage than with every entity being alias-less.
    if n_empty_batches == n_batches and n_batches > 1:
        raise RuntimeError(
            f"Wikidata alias fetch: all {n_batches} batches returned no bindings "
            "— likely a WDQS outage rather than genuinely alias-less entities."
        )

    logger.info("Wikidata alias fetch: %d bindings for %d QIDs", len(out), len(qids))
    return out


def _cache_path(cache_dir: Path, qids: list[str]) -> Path:
    """Return the cache file path keyed on the sorted QID set."""
    digest = hashlib.sha256("|".join(sorted(qids)).encode()).hexdigest()[:16]
    return cache_dir / f"wikidata_en_altlabels_{digest}.json"


def _qid_to_dcid(
    codes_by_entity: dict[str, list[dict[str, Any]]],
) -> dict[str, str]:
    """Build a lower-cased QID → dcid map from the chunk's code rows."""
    out: dict[str, str] = {}
    for dcid, code_rows in codes_by_entity.items():
        for row in code_rows:
            if row.get("code_system") == "wikidataId":
                qid_value = str(row.get("code_value", "")).lower()
                if qid_value:
                    out[qid_value] = dcid
    return out


def _is_precise_en_alias(text: str, *, endonyms: set[str]) -> bool:
    """Return False for forms likely to be noisy or non-English.

    Drops:
    (a) ≤3-char pure-alpha strings (ISO-2 codes, IOC codes: ``UK``, ``US``);
    (b) dotted or abbreviated forms — any ``.`` present (``S. Korea``, ``St.``);
    (c) text whose casefolded form equals an endonym in ``endonyms``
        (catches native-language names: ``Suomi`` for Finland, ``Misr``
        for Egypt).
    """
    if len(text) <= 3 and text.isalpha():
        return False
    if "." in text:
        return False
    return text.casefold() not in {e.casefold() for e in endonyms}


def _alias_entry(alt_label: str) -> dict[str, Any]:
    return {
        "alias_text": alt_label,
        "language": "en",
        "alias_type": "alias",
        "source": "wikidata",
    }


def _parse_qid(uri: str) -> str | None:
    if not uri.startswith(_QID_URI_PREFIX):
        return None
    qid = uri[len(_QID_URI_PREFIX) :]
    return qid if _QID_RE.match(qid) else None
