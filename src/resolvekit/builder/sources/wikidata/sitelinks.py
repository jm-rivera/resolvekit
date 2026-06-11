"""Fetch Wikidata sitelink counts via batched SPARQL VALUES queries.

The ONE-hosted Data Commons instance does not import ``wikidataSitelinkCount``,
so the prominence enricher pulls the signal straight from Wikidata. Coverage
on the geo packs is ~95% (entities with a ``codes.system='wikidata'`` row).

Batching keeps each query under WDQS's 60s timeout: ~1000 QIDs per VALUES
clause finishes in well under a second, and a small ``request_delay`` between
batches keeps us inside WDQS's polite-traffic envelope.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Iterable

from resolvekit.calibration.adapters._wikidata_client import sparql_request

logger = logging.getLogger(__name__)

USER_AGENT = (
    "ResolveKit/1.0 (prominence-enrich; https://github.com/jm-rivera/resolvekit)"
)

_QID_RE = re.compile(r"^Q[1-9][0-9]*$")
_QID_URI_PREFIX = "http://www.wikidata.org/entity/"

_SITELINKS_TEMPLATE = """\
SELECT ?item ?sitelinks WHERE {{
  VALUES ?item {{ {values} }}
  ?item wikibase:sitelinks ?sitelinks .
}}
"""


def fetch_sitelinks_by_qid(
    *,
    qids: Iterable[str],
    user_agent: str = USER_AGENT,
    batch_size: int = 1000,
    request_delay: float = 0.5,
) -> dict[str, int]:
    """Return ``{qid: sitelinks_count}`` for QIDs that have a sitelinks count.

    QIDs are case-normalized to upper-case (``q123`` → ``Q123``). Malformed
    entries are silently skipped. Batches that fail (network / parse error)
    log a warning and contribute no rows, mirroring the failure-tolerance of
    :func:`sparql_request`.
    """
    valid = sorted({q.upper() for q in qids if _QID_RE.match(q.upper())})
    if not valid:
        return {}

    out: dict[str, int] = {}
    for i in range(0, len(valid), batch_size):
        batch = valid[i : i + batch_size]
        values = " ".join(f"wd:{q}" for q in batch)
        query = _SITELINKS_TEMPLATE.format(values=values)

        bindings = sparql_request(query=query, user_agent=user_agent)
        for binding in bindings:
            qid = _parse_qid(binding.get("item", {}).get("value", ""))
            count = _parse_int(binding.get("sitelinks", {}).get("value"))
            if qid is not None and count is not None:
                out[qid] = count

        if request_delay > 0 and i + batch_size < len(valid):
            time.sleep(request_delay)

    logger.info(
        "Wikidata sitelinks fetch: %d/%d QIDs returned a count", len(out), len(valid)
    )
    return out


def _parse_qid(uri: str) -> str | None:
    if not uri.startswith(_QID_URI_PREFIX):
        return None
    qid = uri[len(_QID_URI_PREFIX) :]
    return qid if _QID_RE.match(qid) else None


def _parse_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
