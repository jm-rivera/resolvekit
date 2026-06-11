"""rapidfuzz + curated-dict baseline adapter.

Rapidfuzz fuzzy matching over a small curated dictionary of countries + aliases.

Supports: entity_type={"country"}, language={"en"}.
"""

from __future__ import annotations

from typing import Any, ClassVar

from benchmarks.core.kernel import Query, Response
from benchmarks.core.toolspec import ToolSpec
from benchmarks.tools._util import _pkg_version


class RapidfuzzDictAdapter:
    spec: ClassVar[ToolSpec] = ToolSpec(
        name="rapidfuzz_dict",
        distribution="rapidfuzz",
        offline=True,
        entity_types=frozenset({"country"}),
    )

    _CURATED: ClassVar[dict[str, tuple[str, tuple[str, ...]]]] = {
        "USA": (
            "United States",
            (
                "US",
                "USA",
                "U.S.",
                "U.S.A.",
                "America",
                "United States of America",
                "The States",
            ),
        ),
        "GBR": ("United Kingdom", ("UK", "GBR", "Britain", "Great Britain", "England")),
        "FRA": ("France", ("FRA", "French Republic")),
        "DEU": (
            "Germany",
            ("DEU", "GER", "Deutschland", "Federal Republic of Germany"),
        ),
        "ITA": ("Italy", ("ITA", "Italian Republic")),
        "ESP": ("Spain", ("ESP", "Kingdom of Spain", "España")),
        "PRT": ("Portugal", ("PRT", "POR")),
        "NLD": ("Netherlands", ("NLD", "NED", "Holland")),
        "BEL": ("Belgium", ("BEL",)),
        "CHE": ("Switzerland", ("CHE", "SUI", "Swiss Confederation")),
        "AUT": ("Austria", ("AUT",)),
        "SWE": ("Sweden", ("SWE",)),
        "NOR": ("Norway", ("NOR",)),
        "DNK": ("Denmark", ("DNK", "DEN")),
        "FIN": ("Finland", ("FIN",)),
        "ISL": ("Iceland", ("ISL",)),
        "IRL": ("Ireland", ("IRL",)),
        "POL": ("Poland", ("POL",)),
        "CZE": ("Czechia", ("CZE", "Czech Republic")),
        "SVK": ("Slovakia", ("SVK",)),
        "HUN": ("Hungary", ("HUN",)),
        "ROU": ("Romania", ("ROU", "ROM")),
        "BGR": ("Bulgaria", ("BGR", "BUL")),
        "GRC": ("Greece", ("GRC", "GRE", "Hellenic Republic")),
        "TUR": ("Türkiye", ("TUR", "Turkey")),
        "RUS": ("Russia", ("RUS", "Russian Federation")),
        "UKR": ("Ukraine", ("UKR",)),
        "BLR": ("Belarus", ("BLR",)),
        "CHN": ("China", ("CHN", "People's Republic of China", "PRC")),
        "JPN": ("Japan", ("JPN",)),
        "KOR": ("South Korea", ("KOR", "Republic of Korea")),
        "PRK": (
            "North Korea",
            ("PRK", "DPRK", "Democratic People's Republic of Korea"),
        ),
        "IND": ("India", ("IND",)),
        "PAK": ("Pakistan", ("PAK",)),
        "BGD": ("Bangladesh", ("BGD",)),
        "IDN": ("Indonesia", ("IDN",)),
        "VNM": ("Vietnam", ("VNM", "Viet Nam")),
        "THA": ("Thailand", ("THA",)),
        "PHL": ("Philippines", ("PHL",)),
        "MYS": ("Malaysia", ("MYS",)),
        "SGP": ("Singapore", ("SGP",)),
        "AUS": ("Australia", ("AUS",)),
        "NZL": ("New Zealand", ("NZL",)),
        "CAN": ("Canada", ("CAN",)),
        "MEX": ("Mexico", ("MEX",)),
        "BRA": ("Brazil", ("BRA",)),
        "ARG": ("Argentina", ("ARG",)),
        "CHL": ("Chile", ("CHL",)),
        "COL": ("Colombia", ("COL",)),
        "PER": ("Peru", ("PER",)),
        "VEN": ("Venezuela", ("VEN",)),
        "ZAF": ("South Africa", ("ZAF",)),
        "EGY": ("Egypt", ("EGY",)),
        "NGA": ("Nigeria", ("NGA",)),
        "KEN": ("Kenya", ("KEN",)),
        "ETH": ("Ethiopia", ("ETH",)),
        "MAR": ("Morocco", ("MAR",)),
        "DZA": ("Algeria", ("DZA",)),
        "ISR": ("Israel", ("ISR",)),
        "SAU": ("Saudi Arabia", ("SAU", "KSA")),
        "ARE": ("United Arab Emirates", ("ARE", "UAE")),
    }

    def __init__(self, *, threshold: float = 80.0) -> None:
        try:
            from rapidfuzz import fuzz, process
        except ImportError as exc:
            raise ImportError(
                "rapidfuzz is required for RapidfuzzDictAdapter. "
                "Install with: uv add rapidfuzz"
            ) from exc
        self._fuzz: Any = fuzz
        self._process: Any = process
        self._threshold = float(threshold)
        self._terms: list[str] = []
        self._term_iso3: list[str] = []
        self._iso3_canonical: dict[str, str] = {}

    def warmup(self) -> None:
        terms: list[str] = []
        iso3s: list[str] = []
        # Build the full ISO3 term index from pycountry.countries (covers all ~250
        # countries); _CURATED aliases are added as supplemental entries afterwards.
        iso3_canonical: dict[str, str] = {}
        try:
            import pycountry

            for country in pycountry.countries:
                iso3 = country.alpha_3
                # name is always present; common_name and official_name are optional.
                for attr in ("name", "common_name", "official_name"):
                    value = getattr(country, attr, None)
                    if value:
                        terms.append(value.casefold())
                        iso3s.append(iso3)
                terms.append(iso3.casefold())
                iso3s.append(iso3)
                alpha2 = getattr(country, "alpha_2", None)
                if alpha2:
                    terms.append(alpha2.casefold())
                    iso3s.append(iso3)
                # preferred display name: common_name > name > iso3.
                iso3_canonical[iso3] = (
                    getattr(country, "common_name", None)
                    or getattr(country, "name", None)
                    or iso3
                )
        except ImportError:
            pass

        # Supplemental curated aliases (informal names, abbreviations not in pycountry).
        for iso3, (canonical, aliases) in self._CURATED.items():
            terms.append(canonical.casefold())
            iso3s.append(iso3)
            terms.append(iso3.casefold())
            iso3s.append(iso3)
            for alias in aliases:
                terms.append(alias.casefold())
                iso3s.append(iso3)
        self._terms = terms
        self._term_iso3 = iso3s
        self._iso3_canonical = iso3_canonical

    def resolve(self, query: Query) -> Response:
        text = query.text.strip()
        if not text:
            return Response(status="no_match")
        assert self._terms, "warmup() not called"
        try:
            match = self._process.extractOne(
                text.casefold(),
                self._terms,
                scorer=self._fuzz.WRatio,
            )
        except Exception as exc:
            return Response(status="error", error=repr(exc))
        if match is None:
            return Response(status="no_match")
        _, score, index = match
        if score < self._threshold:
            return Response(status="no_match", confidence=score / 100.0)
        iso3 = self._term_iso3[index]
        curated_entry = self._CURATED.get(iso3)
        if curated_entry is not None:
            canonical = curated_entry[0]
        else:
            # pycountry-sourced entry: O(1) lookup into the map built during warmup.
            canonical = self._iso3_canonical.get(iso3, iso3)
        return Response(
            status="match",
            match_ids=(f"country/{iso3}",),
            canonical_name=canonical,
            confidence=score / 100.0,
        )

    def version(self) -> str | None:
        return _pkg_version(self.spec.distribution)
