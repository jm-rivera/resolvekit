"""Shared Wikidata SPARQL HTTP primitive — internal seam, not public API.

Consumed by:

- ``resolvekit.calibration.adapters.wikidata`` (entity-type label sweeps)
- ``benchmarks.build.sources.wikidata`` (same sweep, for benchmark data)
- ``resolvekit.builder.sources.wikidata.sitelinks`` (sitelink-count lookups
  for the geo prominence enrichment)
- ``scripts.data_maintenance.refresh_group_members`` (group membership refresh)

Each consumer owns its own cache policy, USER_AGENT, query template, and
row-shaping logic; this module owns only the HTTP + JSON-bindings unwrap.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"

SPARQL_TEMPLATE = """\
SELECT ?item ?itemLabel ?altLabel WHERE {{
  ?item wdt:P31/wdt:P279* wd:{entity_type} .
  OPTIONAL {{ ?item skos:altLabel ?altLabel . FILTER(LANG(?altLabel) = "{lang}") }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "{lang}" }}
}}
LIMIT {limit}
"""

GEO_ENTITY_TYPES: tuple[str, ...] = ("Q6256", "Q3624078", "Q10864048", "Q515")
ORG_ENTITY_TYPES: tuple[str, ...] = ("Q484652", "Q163740", "Q4830453", "Q7210356")


def sparql_request(
    *,
    query: str,
    user_agent: str,
    timeout: float = 30,
    max_retries: int = 3,
    initial_backoff: float = 2.0,
) -> list[dict]:
    """Execute one Wikidata SPARQL query; return result bindings (empty on failure).

    Submits via POST so the query body is not bounded by URL / header length
    limits (WDQS rejects long GET URLs with 414/431).

    Retries on transient failures (timeouts, 5xx, 429) with exponential
    backoff. A retried-but-still-failed query logs once and returns ``[]``;
    callers that need to distinguish empty-result from transport-failure
    must layer that on top.
    """
    body = urllib.parse.urlencode({"query": query, "format": "json"}).encode("utf-8")
    req = urllib.request.Request(
        WIKIDATA_SPARQL_URL,
        data=body,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/sparql-results+json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    last_exc: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("results", {}).get("bindings", [])
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code < 500 and exc.code != 429:
                logger.warning("Wikidata SPARQL query failed: %s", exc)
                return []
        except Exception as exc:
            last_exc = exc
        if attempt < max_retries:
            time.sleep(initial_backoff * (2**attempt))
    logger.warning(
        "Wikidata SPARQL query failed after %d retries: %s", max_retries, last_exc
    )
    return []


def sparql_query(
    *,
    entity_type: str,
    lang: str,
    limit: int,
    user_agent: str,
) -> list[dict]:
    """Execute the entity-type/language sweep query and return bindings."""
    query = SPARQL_TEMPLATE.format(entity_type=entity_type, lang=lang, limit=limit)
    return sparql_request(query=query, user_agent=user_agent)
