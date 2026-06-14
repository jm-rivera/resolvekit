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
import urllib.error
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
    chunk (legitimate no-op — not a failure). A genuine empty WDQS result (HTTP
    200, zero rows) is treated as "no aliases" and cached. Raises ``RuntimeError``
    only when a batch hits a transport/HTTP failure after retries, so the chunk
    is retried — successful batches are already cached and are not re-fetched.

    Cache: when ``cache_dir`` is given, results are staged at two levels — a
    chunk-level file keyed on the full sorted QID set (fast path) and a per-batch
    file keyed on each batch's QID subset. Per-batch caching means a transient
    failure on one batch never discards the batches that already succeeded.
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
    """Return bindings from cache if available, else fetch and optionally cache.

    Caches at two levels. The chunk-level file (keyed on the full QID set) is the
    fast path and stays compatible with previously-staged caches. Below it, each
    batch is cached on its own QID subset so a transient WDQS failure on one batch
    never discards the batches that already succeeded — a re-run resumes from the
    per-batch caches and re-fetches only the failed batches.
    """
    if cache_dir is not None:
        cache_file = _cache_path(cache_dir, qids)
        if cache_file.exists():
            logger.info("Wikidata alias fetch: reading cache from %s", cache_file)
            return json.loads(cache_file.read_text(encoding="utf-8"))

    bindings, all_ok = _fetch_batched(
        qids=qids,
        cache_dir=cache_dir,
        user_agent=user_agent,
        batch_size=batch_size,
        request_delay=request_delay,
    )

    # Promote to the chunk-level cache only when every batch succeeded. A
    # partially-failed chunk is left without a chunk file so the next run
    # re-enters here, loads the cached successful batches, and retries just the
    # failed ones — rather than freezing an incomplete result.
    if cache_dir is not None and all_ok:
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

    if not all_ok:
        raise RuntimeError(
            "Wikidata alias fetch: one or more batches failed transport after "
            "retries — successful batches are cached; re-run to resume the rest."
        )

    logger.info(
        "Wikidata alias fetch: %d bindings for %d QIDs", len(bindings), len(qids)
    )
    return bindings


def _fetch_batched(
    *,
    qids: list[str],
    cache_dir: Path | None,
    user_agent: str,
    batch_size: int,
    request_delay: float,
) -> tuple[list[dict[str, Any]], bool]:
    """Fetch alt-label bindings batch by batch.

    Returns ``(bindings, all_ok)``. ``all_ok`` is False when any batch hit a
    transport/HTTP failure (distinct from a genuine empty result); the caller
    raises in that case so the chunk is retried, with successful batches already
    cached per-batch.
    """
    # QIDs stored lower-case; SPARQL VALUES needs canonical upper-case form.
    canonical = [q.upper() for q in qids]

    out: list[dict[str, Any]] = []
    n_batches = 0
    n_failed = 0
    for i in range(0, len(canonical), batch_size):
        batch = canonical[i : i + batch_size]
        n_batches += 1

        bindings, ok = _load_or_fetch_batch(
            batch=batch, cache_dir=cache_dir, user_agent=user_agent
        )
        if not ok:
            # Transport failure (not a genuine empty): leave it uncached so the
            # next run retries this batch, and keep going to fetch what we can.
            logger.warning(
                "Wikidata alias fetch: batch %d (%d QIDs) failed transport — "
                "will retry on re-run",
                i // batch_size + 1,
                len(batch),
            )
            n_failed += 1
            continue
        out.extend(bindings)

        if request_delay > 0 and i + batch_size < len(canonical):
            time.sleep(request_delay)

    return out, n_failed == 0


def _load_or_fetch_batch(
    *,
    batch: list[str],
    cache_dir: Path | None,
    user_agent: str,
) -> tuple[list[dict[str, Any]], bool]:
    """Load one batch from its per-batch cache, else fetch and cache it.

    Returns ``(bindings, ok)``. A genuine empty result (HTTP 200, zero rows) is a
    success and is cached as ``[]`` so it is not re-fetched. A transport/HTTP
    failure returns ``ok=False`` and is NOT cached.
    """
    if cache_dir is not None:
        batch_file = _batch_cache_path(cache_dir, batch)
        if batch_file.exists():
            return json.loads(batch_file.read_text(encoding="utf-8")), True

    values = " ".join(f"wd:{q}" for q in batch)
    query = _ALIASES_TEMPLATE.format(values=values)
    try:
        bindings = sparql_request(
            query=query, user_agent=user_agent, timeout=60, raise_on_failure=True
        )
    except urllib.error.HTTPError as exc:
        if 400 <= exc.code < 500 and exc.code != 429:
            # Permanent client error (e.g. a VALUES token WDQS rejects): retrying
            # cannot fix it, so skip this batch loudly rather than failing the whole
            # chunk. Not cached, so a later data/code fix re-attempts it.
            logger.warning(
                "Wikidata alias fetch: skipping batch on permanent HTTP %d "
                "(%d QIDs) — %s",
                exc.code,
                len(batch),
                exc,
            )
            return [], True
        logger.warning("Wikidata alias fetch: batch transport failure: %s", exc)
        return [], False
    except Exception as exc:
        logger.warning("Wikidata alias fetch: batch transport failure: %s", exc)
        return [], False

    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        batch_file = _batch_cache_path(cache_dir, batch)
        batch_file.write_text(json.dumps(bindings, ensure_ascii=True), encoding="utf-8")

    return bindings, True


def _cache_path(cache_dir: Path, qids: list[str]) -> Path:
    """Return the chunk-level cache file path keyed on the sorted QID set."""
    digest = hashlib.sha256("|".join(sorted(qids)).encode()).hexdigest()[:16]
    return cache_dir / f"wikidata_en_altlabels_{digest}.json"


def _batch_cache_path(cache_dir: Path, batch: list[str]) -> Path:
    """Return the per-batch cache file path keyed on the sorted batch QID subset."""
    digest = hashlib.sha256("|".join(sorted(batch)).encode()).hexdigest()[:16]
    return cache_dir / f"wikidata_en_altlabels_batch_{digest}.json"


def _qid_to_dcid(
    codes_by_entity: dict[str, list[dict[str, Any]]],
) -> dict[str, str]:
    """Build a lower-cased QID → dcid map from the chunk's code rows.

    Drops values that are not clean ``Q``-form QIDs (e.g. bare numerics missing
    the ``Q`` prefix, or path-form codes mislabelled as ``wikidataId``). Such a
    value would render as ``wd:<garbage>`` in the VALUES clause and make WDQS
    reject the whole batch with HTTP 400 — and it could never match a Wikidata
    item anyway, so dropping it loses no real alias.
    """
    out: dict[str, str] = {}
    skipped = 0
    for dcid, code_rows in codes_by_entity.items():
        for row in code_rows:
            if row.get("code_system") == "wikidataId":
                qid_value = str(row.get("code_value", "")).lower()
                if not qid_value:
                    continue
                if not _QID_RE.match(qid_value.upper()):
                    skipped += 1
                    continue
                out[qid_value] = dcid
    if skipped:
        logger.warning(
            "Wikidata alias fetch: skipped %d malformed wikidataId value(s) "
            "(not Q-form) before query construction",
            skipped,
        )
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
