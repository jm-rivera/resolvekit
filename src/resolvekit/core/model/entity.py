"""Entity record models returned by stores."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class NameRecord(BaseModel):
    """A name/alias for an entity.

    Attributes:
        value: Original name text
        value_norm: Normalized form for matching
        kind: Name type (e.g., "canonical", "alias", "endonym", "exonym", "abbr", "acronym")
        lang: ISO 639-1 language code
        script: ISO 15924 script code
        is_preferred: Whether this is a preferred name for display
    """

    model_config = ConfigDict(frozen=True)

    value: str = Field(..., min_length=1)
    value_norm: str = Field(..., min_length=1)
    kind: str = Field(..., min_length=1)
    lang: str | None = Field(default=None, max_length=3)
    script: str | None = Field(default=None, max_length=4)
    is_preferred: bool = Field(default=False)


class CodeRecord(BaseModel):
    """A code identifier for an entity.

    Attributes:
        system: Code system (e.g., "iso3166-1", "wikidata", "dcid")
        value: Original code value
        value_norm: Normalized code value for matching
    """

    model_config = ConfigDict(frozen=True)

    system: str = Field(..., min_length=1)
    value: str = Field(..., min_length=1)
    value_norm: str = Field(..., min_length=1)


class RelationRecord(BaseModel):
    """A relation to another entity.

    Attributes:
        relation_type: Type of relation (e.g., "contained_in", "member_of", "subsidiary_of")
        target_id: Entity ID of the related entity
        valid_from: ISO-8601 date string when this relation became valid
            (None = always valid from the start). Compared lexicographically;
            ISO-8601 string ordering equals chronological ordering.
        valid_until: ISO-8601 date string when this relation expired
            (None = no expiry). Half-open right: a relation with
            ``valid_until="2020-02-01"`` is active for ``as_of <= "2020-01-31"``
            and inactive from ``as_of >= "2020-02-01"``.
    """

    model_config = ConfigDict(frozen=True)

    relation_type: str = Field(..., min_length=1)
    target_id: str = Field(..., min_length=1)
    valid_from: str | None = Field(default=None)
    valid_until: str | None = Field(default=None)


class EntityRecord(BaseModel):
    """Domain-neutral entity record returned by stores.

    This is the core entity representation used throughout the system.
    Domain packs may wrap this with additional domain-specific fields.

    Attributes:
        entity_id: Unique identifier (e.g., DCID)
        entity_type: Type string (e.g., "geo.country", "org.igo")
        canonical_name: Primary display name
        canonical_name_norm: Normalized canonical name for matching
        names: Alternative names/aliases
        codes: Code identifiers (ISO, Wikidata, etc.)
        relations: Relations to other entities
        valid_from: Start of validity period
        valid_until: End of validity period (None = still valid)
        attributes: Domain-specific lightweight attributes
    """

    model_config = ConfigDict(frozen=True)

    entity_id: str = Field(..., min_length=1)
    entity_type: str = Field(..., min_length=1)
    canonical_name: str = Field(..., min_length=1)
    canonical_name_norm: str = Field(..., min_length=1)
    names: list[NameRecord] = Field(default_factory=list)
    codes: list[CodeRecord] = Field(default_factory=list)
    relations: list[RelationRecord] = Field(default_factory=list)
    valid_from: date | None = Field(default=None)
    valid_until: date | None = Field(default=None)
    attributes: dict[str, str | int | float | bool] = Field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience properties (pycountry-compatible attribute access)
    # ------------------------------------------------------------------

    @property
    def codes_dict(self) -> dict[str, str]:
        """All code records as a ``{system: value}`` mapping.

        When a system appears more than once, the first occurrence wins.
        """
        result: dict[str, str] = {}
        for cr in self.codes:
            result.setdefault(cr.system, cr.value)
        return result

    @property
    def iso2(self) -> str | None:
        """ISO 3166-1 alpha-2 code, or ``None`` if not available."""
        return self.codes_dict.get("iso2")

    @property
    def iso3(self) -> str | None:
        """ISO 3166-1 alpha-3 code, or ``None`` if not available."""
        return self.codes_dict.get("iso3")

    @property
    def numeric(self) -> str | None:
        """ISO 3166-1 numeric code, or ``None`` if not available."""
        return self.codes_dict.get("numeric")

    @property
    def name(self) -> str:
        """Primary display name (always present — same as ``canonical_name``)."""
        return self.canonical_name

    @property
    def flag(self) -> str | None:
        """Flag emoji derived from the ISO 3166-1 alpha-2 code, or ``None``."""
        from resolvekit.core.model.entity_attributes import _flag_from_iso2

        iso2 = self.iso2
        if iso2 is None:
            return None
        try:
            return _flag_from_iso2(iso2)
        except ValueError:
            return None

    @property
    def continent(self) -> str | None:
        """Continent name from ``attributes``, or ``None`` if not set."""
        val = self.attributes.get("continent")
        return str(val) if val is not None else None

    @property
    def aliases(self) -> list[str]:
        """All non-canonical name values, in declaration order."""
        return [nr.value for nr in self.names if not nr.is_preferred]

    # ------------------------------------------------------------------
    # Helper methods
    # ------------------------------------------------------------------

    def code(self, system: str) -> str | None:
        """Return the code value for *system*, or ``None`` if absent.

        Args:
            system: Code system name, e.g. ``"iso3"`` or ``"wikidata"``.
        """
        return self.codes_dict.get(system)

    def attribute(self, key: str, default: object = None) -> object:
        """Return an entity attribute by key, with an optional default.

        Args:
            key: Attribute name.
            default: Value returned when the key is absent (default ``None``).
        """
        return self.attributes.get(key, default)

    def to(self, system: str) -> object:
        """Pivot this entity to a specific code system or computed property.

        Delegates to :func:`resolvekit.core.model.entity_attributes.dispatch_pivot`.

        Args:
            system: Target pivot — a known computed property (``"iso2"``,
                ``"iso3"``, ``"name"``, ``"flag"``, ``"continent"``,
                ``"numeric"``, ``"aliases"``), a loaded code-system name
                (e.g. ``"wikidata"``), or an attribute key.

        Raises:
            UnknownCodeSystemError: When *system* doesn't match any routing branch.
        """
        from resolvekit.core.model.entity_attributes import dispatch_pivot

        return dispatch_pivot(self, system)

    # ------------------------------------------------------------------
    # HTML representation (sklearn-scoped CSS — no style leakage)
    # ------------------------------------------------------------------

    def _repr_html_(self) -> str:
        """Jupyter-friendly HTML rendering with scoped CSS.

        Each call gets a unique container ID (``rk-entity-N``) so styles
        from one cell never bleed into another.  All user-supplied strings
        are HTML-escaped before interpolation.
        """
        # Inline import keeps top-level entity.py free of the model._repr
        # dependency for non-notebook callers (avoids loading html.escape
        # when only EntityRecord construction matters).
        from resolvekit.core.model._repr import escape, scoped_table

        iso2 = self.iso2 or ""
        flag = self.flag or ""
        iso3 = self.iso3 or ""
        numeric = self.numeric or ""
        continent = self.continent or ""
        aliases_str = ", ".join(self.aliases) if self.aliases else ""

        rows: list[tuple[str, str]] = [
            ("entity_id", self.entity_id),
            ("type", self.entity_type),
            ("name", self.canonical_name),
        ]
        if iso2:
            rows.append(("iso2", iso2))
        if iso3:
            rows.append(("iso3", iso3))
        if flag:
            rows.append(("flag", flag))
        if numeric:
            rows.append(("numeric", numeric))
        if continent:
            rows.append(("continent", continent))
        if aliases_str:
            rows.append(("aliases", aliases_str))
        for key, val in self.codes_dict.items():
            if key not in {"iso2", "iso3", "numeric"}:
                rows.append((key, val))

        table_rows = "".join(
            f"<tr><th>{escape(k)}</th><td>{escape(v)}</td></tr>" for k, v in rows
        )
        return scoped_table(
            prefix="rk-entity", rows_html=table_rows, css_class="rk-entity"
        )
