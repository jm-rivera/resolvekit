"""Base linker with common link resolution logic."""

from typing import TYPE_CHECKING

from resolvekit.core.linking.linker import LinkResult

if TYPE_CHECKING:
    from resolvekit.core.store import EntityStore


class BaseLinker:
    """Base class for domain-specific linkers.

    Implements the common link resolution algorithm:
    - Tries link keys in order until one succeeds
    - Returns linked on single match
    - Returns ambiguous on multiple matches
    - Returns not_found if no keys match

    Subclasses only need to define KNOWN_CODE_SYSTEMS.
    The KNOWN_CODE_SYSTEMS frozenset is a *priority hint* for ordering and
    auto-detect paths.
    """

    KNOWN_CODE_SYSTEMS: frozenset[str] = frozenset()

    def resolve_link(
        self,
        overlay_row: dict,
        link_keys: list[str],
        base_store: "EntityStore",
        *,
        valid_systems: frozenset[str] | None = None,
    ) -> LinkResult:
        """Attempt to link an overlay row to a base entity.

        Tries each key in link_keys order.  Returns as soon as one produces
        a definitive result (linked or ambiguous).

        The gate is OPEN: a key is accepted when it equals ``"name"`` (exact
        normalised-name match against the base store) or when it is present in
        ``valid_systems`` (the pre-computed open vocabulary from
        ``base_store.code_systems()``).  When ``valid_systems`` is ``None`` a
        live ``base_store.code_systems()`` call is made — prefer passing the
        pre-computed set to avoid repeated database queries.

        For the ``"name"`` strategy, the normalised name value must be injected
        into ``overlay_row`` under the key ``"__name__"`` by the caller (see
        ``BaseDataPackBuilder.link_and_add``).

        Args:
            overlay_row: Row data from overlay pack.  Code keys are looked up
                directly; for ``"name"``, the normalised value must be stored
                under ``overlay_row["__name__"]``.
            link_keys: Ordered list of keys to try.
            base_store: Store to search for matching entities.
            valid_systems: Pre-computed ``frozenset`` of accepted code systems
                (avoids a per-call ``SELECT DISTINCT``).  When ``None``,
                falls back to ``base_store.code_systems()``.

        Returns:
            LinkResult with status linked/not_found/ambiguous/invalid_key.
        """
        open_vocab: frozenset[str] = (
            valid_systems if valid_systems is not None else base_store.code_systems()
        )

        for key in link_keys:
            is_name_key = key == "name"

            # Resolve the value first: a key absent from this row is not an error —
            # it just means the key doesn't apply to this row, so skip silently.
            if is_name_key:
                lookup_value = overlay_row.get("__name__")
            else:
                lookup_value = overlay_row.get(key)

            if lookup_value is None:
                continue

            # Gate check only after confirming a value is present: a key with a
            # value that isn't in the open vocab is a real misconfiguration.
            if not is_name_key and key not in open_vocab:
                return LinkResult.invalid_key(f"Unknown code system: {key}")

            if is_name_key:
                matches = base_store.lookup_name_exact(lookup_value)
            else:
                # The overlay value was pre-normalized by the builder's normalizer
                # before resolve_link is called, so a direct lookup is correct.
                # Assert the type: overlay_row.get() is typed as object; a non-str
                # slipping through indicates a schema bug that should fail loud.
                assert isinstance(lookup_value, str)
                matches = base_store.lookup_code(key, lookup_value)

            if len(matches) == 1:
                return LinkResult.linked(matches[0])
            elif len(matches) > 1:
                return LinkResult.ambiguous(
                    tuple(matches),
                    f"Multiple entities match {key}={lookup_value}",
                )

        return LinkResult.not_found("No match for any link key")
