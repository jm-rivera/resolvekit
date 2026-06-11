"""Feature vectorization for ML scoring models.

Converts feature model instances into flat float vectors suitable for
logistic regression and other linear models.
"""

from __future__ import annotations

from typing import Any

from resolvekit.packs.geo.features import GeoFeaturesV1
from resolvekit.packs.org.features import OrgFeaturesV1

# Derived from GeoFeaturesV1 / OrgFeaturesV1 model field declaration order.
GEO_FEATURE_NAMES: list[str] = list(GeoFeaturesV1.model_fields)
ORG_FEATURE_NAMES: list[str] = list(OrgFeaturesV1.model_fields)

DOMAIN_FEATURE_NAMES: dict[str, list[str]] = {
    "geo": GEO_FEATURE_NAMES,
    "org": ORG_FEATURE_NAMES,
}


def feature_names_for_domain(domain: str) -> list[str]:
    """Return the canonical feature name list for a domain.

    Raises ``ValueError`` for unknown domains.
    """
    names = DOMAIN_FEATURE_NAMES.get(domain)
    if names is None:
        raise ValueError(
            f"No feature schema registered for domain {domain!r}. "
            f"Known domains: {sorted(DOMAIN_FEATURE_NAMES)}"
        )
    return names


QUERY_LEN_SCALE = 20.0


def vectorize_geo_features(features: GeoFeaturesV1) -> list[float]:
    """Convert a GeoFeaturesV1 instance to a flat float vector.

    Encoding rules by field type:
    - ``bool``       → 1.0 / 0.0
    - ``float | None`` → value or 0.0 when None
    - ``bool | None``  → 1.0 / 0.0 / 0.0 (None = no signal, treated as 0.0)
    - ``query_len``  → min(val, 20) / 20.0  (normalised to [0, 1])
    """
    d = features.to_dict()
    return features_dict_to_vector(GEO_FEATURE_NAMES, d)


def features_dict_to_vector(feature_names: list[str], d: dict[str, Any]) -> list[float]:
    """Generic version: convert a feature dict to a float vector.

    Uses ``feature_names`` to determine the ordering and applies the same
    encoding rules as ``vectorize_geo_features``:
    - bool  → 1.0 / 0.0
    - float → as-is (None → 0.0)
    - None  → 0.0
    - ``query_len`` → min(val, QUERY_LEN_SCALE) / QUERY_LEN_SCALE
    """
    vec: list[float] = []
    for name in feature_names:
        val = d.get(name)
        if name == "query_len":
            int_val = val if val is not None else 0
            vec.append(min(int_val, QUERY_LEN_SCALE) / QUERY_LEN_SCALE)
        elif isinstance(val, bool):
            vec.append(1.0 if val else 0.0)
        elif val is None:
            vec.append(0.0)
        else:
            # float or int (other than query_len)
            vec.append(float(val))
    return vec
