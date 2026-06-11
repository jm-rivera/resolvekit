"""spaCy NER → resolvekit baseline adapter.

``SpacyNerAdapter`` runs spaCy's ``en_core_web_sm`` NER pipeline over each
document, filters to geo/org entity labels, then calls ``resolver.resolve()``
on each surviving span.  Only resolved (non-NIL) spans are emitted.

spaCy is an optional dependency; the adapter raises a clear
:class:`ImportError` with install instructions if it is absent, and a
separate :class:`OSError`-derived error if the model is not downloaded.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from benchmarks.parse.metrics import PredSpan

if TYPE_CHECKING:
    from resolvekit import Resolver

# spaCy entity labels that correspond to geographic / organizational entities.
# Filtering to these before resolving prevents PERSON/DATE/CARDINAL/etc. spans
# from producing spurious FPs and skewing the baseline comparison.
_GEO_ORG_LABELS: frozenset[str] = frozenset({"GPE", "LOC", "ORG"})


class SpacyNerAdapter:
    """Parse adapter that uses spaCy NER followed by resolvekit resolution.

    Lazy-loads spaCy on construction; raises :class:`ImportError` when spaCy
    is not installed and :class:`OSError` when the ``en_core_web_sm``
    model is not downloaded.

    Only NER components are loaded (``tok2vec``, ``tagger``, ``parser``,
    ``senter``, ``attribute_ruler``, and ``lemmatizer`` are excluded) so RSS
    and latency are comparable to a pure-NER baseline.

    Args:
        resolver: A live :class:`~resolvekit.Resolver` instance used to
                  resolve NER-detected spans to canonical entity IDs.
    """

    def __init__(self, resolver: Resolver) -> None:
        try:
            import spacy
        except ImportError as exc:
            raise ImportError(
                "The spaCy parse baseline requires spacy. "
                "Install with: pip install 'resolvekit[baselines]' "
                "and download the model: python -m spacy download en_core_web_sm"
            ) from exc

        try:
            self._nlp = spacy.load(
                "en_core_web_sm",
                exclude=[
                    "tok2vec",
                    "tagger",
                    "parser",
                    "senter",
                    "attribute_ruler",
                    "lemmatizer",
                ],
            )
        except OSError as exc:
            raise OSError(
                "spaCy model 'en_core_web_sm' is not downloaded. "
                "Run: python -m spacy download en_core_web_sm"
            ) from exc

        self._resolver = resolver

    def predict(self, text: str) -> list[PredSpan]:
        """Run spaCy NER on *text* and resolve geo/org entities.

        Filters NER output to :data:`_GEO_ORG_LABELS` before resolving.
        Only spans that resolve to a non-NIL entity ID are returned.

        Args:
            text: Raw document text.

        Returns:
            List of :class:`~benchmarks.parse.metrics.PredSpan` objects.
        """
        doc = self._nlp(text)
        spans: list[PredSpan] = []

        for ent in doc.ents:
            if ent.label_ not in _GEO_ORG_LABELS:
                continue

            # as_result=True returns a ResolutionResult regardless of the
            # resolver's default_to setting, preventing silent span drops when
            # the caller has configured a non-None default_to pivot.
            res = self._resolver.resolve(ent.text, as_result=True)
            if res is None or res.entity_id is None:
                continue

            # entity_type lives on the resolved candidate, not on ResolutionResult.
            top = res.best_candidate
            spans.append(
                PredSpan(
                    start=ent.start_char,
                    end=ent.end_char,
                    entity_id=res.entity_id,
                    entity_type=top.entity_type if top is not None else None,
                )
            )

        return spans
