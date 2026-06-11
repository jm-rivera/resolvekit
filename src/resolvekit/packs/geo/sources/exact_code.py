"""Exact code source for geo entities."""

import re
from collections.abc import Callable, Sequence

from pydantic import BaseModel, ConfigDict

from resolvekit.core.engine import CandidateSource
from resolvekit.core.engine.tier_utils import REASON_TO_MATCH_TIER
from resolvekit.core.explain import emit_candidates_generated
from resolvekit.core.model import (
    CandidateEvidence,
    GenerationContext,
    ReasonCode,
)
from resolvekit.packs.geo.sources._short_input import short_input_blocked
from resolvekit.packs.geo.sources.query_shapes import wikidata_lookup_values
from resolvekit.shared.sources import evidence_from_code_hits


class CodeSystemSpec(BaseModel):
    """Specification for a code system lookup."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    name: str  # e.g., "iso2", "dcid"
    matches: Callable[[str, str], bool]  # (raw_text, normalized) -> bool
    lookup_values: Callable[
        [str, str], Sequence[str]
    ]  # (raw_text, normalized) -> store lookup values to try
    display_value: Callable[[str, str], str]  # (raw_text, normalized) -> matched_value


# Code system specifications (order matters - first match wins)
CODE_SYSTEMS: list[CodeSystemSpec] = [
    CodeSystemSpec(
        name="dcid",
        matches=lambda raw, norm: "/" in raw,
        lookup_values=lambda raw, norm: (raw, norm) if raw != norm else (raw,),
        display_value=lambda raw, norm: raw,  # display preserves user's input
    ),
    CodeSystemSpec(
        name="wikidata",
        matches=lambda raw, norm: bool(wikidata_lookup_values(raw, norm)),
        lookup_values=wikidata_lookup_values,
        display_value=lambda raw, norm: (
            values[0].upper() if (values := wikidata_lookup_values(raw, norm)) else raw
        ),
    ),
    CodeSystemSpec(
        name="iso2",
        matches=lambda raw, norm: bool(re.match(r"^[a-z]{2}$", norm)),
        lookup_values=lambda raw, norm: (norm,),  # lowercase for store
        display_value=lambda raw, norm: norm.upper(),
    ),
    CodeSystemSpec(
        name="iso3",
        matches=lambda raw, norm: bool(re.match(r"^[a-z]{3}$", norm)),
        lookup_values=lambda raw, norm: (norm,),
        display_value=lambda raw, norm: norm.upper(),
    ),
    CodeSystemSpec(
        name="iso_numeric",
        matches=lambda raw, norm: bool(re.match(r"^\d{3}$", norm)),
        # Stored values are unpadded ('4'), so zero-padded canonical input
        # ('004') must also try the stripped form.
        lookup_values=lambda raw, norm: (norm, norm.lstrip("0") or "0"),
        display_value=lambda raw, norm: norm,
    ),
    CodeSystemSpec(
        name="iso3166_2",
        matches=lambda raw, norm: bool(re.match(r"^[a-z]{2}-[a-z0-9]{1,3}$", norm)),
        lookup_values=lambda raw, norm: (norm, norm.upper()),
        display_value=lambda raw, norm: norm.upper(),
    ),
]


# Code systems the catch-all lookup is allowed to match. These hold structured
# identifiers (ISO / FIPS / IOC / ITU / UN M49 / GS1 / UIC / WIPO / dcid /
# wikidata) whose values never collide with ordinary name queries.
#
# The exclusion is the point: the geo store also carries dozens of catalog
# cross-reference identifiers (library, encyclopedia, and wiki authority IDs
# such as viafId, gndId, whosOnFirstId, quoraTopicId,
# swedishNationalEncyclopediaId). Those hold word-like slugs — e.g.
# swedishNationalEncyclopediaId "georgia" on the US state geoId/13 — that
# otherwise produce a spurious EXACT_CODE-tier hit, short-circuiting the
# pipeline before exact-name runs and shadowing the real match (country/GEO).
# Keep this set in sync with the resolution-worthy systems in
# builder/sources/datacommons/geo/mappings.py.
_MATCHABLE_CATCHALL_SYSTEMS: frozenset[str] = frozenset(
    {
        "dcid",
        "wikidata",
        "iso2",
        "iso3",
        "iso_numeric",
        "iso3166_2",
        "geonames",
        "undata",
        "fips104",
        "ioccountrycode",
        "itulettercode",
        "gs1countrycode",
        "uicnumericalcountrycode",
        "uicalphabeticalcountrycode",
        "wipost3id",
    }
)


class GeoExactCodeSource(CandidateSource):
    """Exact code lookup for geo entities."""

    @property
    def name(self) -> str:
        return "geo_exact_code"

    @property
    def reason_code(self) -> ReasonCode:
        return ReasonCode.EXACT_CODE_MATCH

    def supports(self, domain_pack_id: str) -> bool:
        return domain_pack_id == "geo"

    def generate(self, ctx: GenerationContext) -> list[CandidateEvidence]:
        """Generate evidence from code lookup."""
        raw_text = ctx.query.raw_text
        norm_text = ctx.text_norm
        evidence: list[CandidateEvidence] = []

        # See packs/geo/sources/_short_input.py — blocks single letters,
        # lowercase short alpha, and punctuation-noise tokens unless the
        # caller passed a geo entity_type hint.
        if short_input_blocked(raw_text, norm_text, ctx.context):
            emit_candidates_generated(
                ctx.trace,
                self.name,
                0,
                entity_ids=[],
                query=norm_text,
            )
            return evidence

        # Try each code system in priority order (first match wins)
        for spec in CODE_SYSTEMS:
            if not spec.matches(raw_text, norm_text):
                continue

            for lookup_val in spec.lookup_values(raw_text, norm_text):
                entity_ids = ctx.store.lookup_code(spec.name, lookup_val)
                if entity_ids:
                    _tier = REASON_TO_MATCH_TIER.get(self.reason_code)
                    evidence = [
                        CandidateEvidence(
                            entity_id=eid,
                            source_name=self.name,
                            raw_score=1.0,
                            rank=i + 1,
                            matched_field=f"code.{spec.name}",
                            matched_value=spec.display_value(raw_text, norm_text),
                            match_tier=_tier,
                        )
                        for i, eid in enumerate(entity_ids[: ctx.budget])
                    ]
                    break
            if evidence:
                break

        # Catch-all fallback when prioritized lookups miss. Restricted to
        # structured code systems — catalog cross-reference identifiers are
        # dropped so their word-like values can't shadow a real name match.
        if not evidence:
            hits = [
                (entity_id, system)
                for entity_id, system in ctx.store.lookup_code_any(norm_text)
                if system in _MATCHABLE_CATCHALL_SYSTEMS
            ]
            evidence = evidence_from_code_hits(
                hits,
                source_name=self.name,
                matched_value=raw_text,
                budget=ctx.budget,
                match_tier=REASON_TO_MATCH_TIER.get(self.reason_code),
            )

        emit_candidates_generated(
            ctx.trace,
            self.name,
            len(evidence),
            entity_ids=[e.entity_id for e in evidence],
            query=norm_text,
        )
        return evidence
