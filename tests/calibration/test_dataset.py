"""Tests for calibration dataset models and labeling."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from resolvekit.calibration.dataset import (
    CalibrationDataset,
    LabeledExample,
    label_examples,
    load_examples_jsonl,
    save_examples_jsonl,
)
from resolvekit.core.model import ResolutionStatus


@dataclass
class MockScores:
    raw_score: float


@dataclass
class MockCandidate:
    entity_id: str
    scores: MockScores


class MockResult:
    def __init__(
        self,
        entity_id: str | None,
        confidence: float | None,
        status: ResolutionStatus,
    ) -> None:
        self.entity_id = entity_id
        self.confidence = confidence
        self.status = status


class MockPipelineResult:
    def __init__(
        self, result: MockResult, candidates: list[MockCandidate] | None
    ) -> None:
        self.result = result
        self.candidates = candidates


class MockRunner:
    def __init__(self, results: dict[str, tuple[str | None, float | None]]) -> None:
        self._results = results

    def _build_pipeline_result(
        self, query: object, context: object
    ) -> MockPipelineResult:
        text = getattr(query, "raw_text", "")
        eid, conf = self._results.get(text, (None, None))
        status = (
            ResolutionStatus.RESOLVED if eid is not None else ResolutionStatus.NO_MATCH
        )
        result = MockResult(entity_id=eid, confidence=conf, status=status)
        candidates = None
        if eid is not None and conf is not None:
            candidates = [
                MockCandidate(entity_id=eid, scores=MockScores(raw_score=conf))
            ]
        return MockPipelineResult(result=result, candidates=candidates)

    def resolve(
        self,
        query: object,
        context: object,
        **kwargs: object,
    ) -> MockPipelineResult:
        return self._build_pipeline_result(query, context)

    def resolve_detailed(
        self,
        query: object,
        context: object,
        **kwargs: object,
    ) -> MockPipelineResult:
        return self._build_pipeline_result(query, context)


class MockQuery:
    def __init__(self, raw_text: str) -> None:
        self.raw_text = raw_text


class MockResolver:
    def __init__(self, results: dict[str, tuple[str | None, float | None]]) -> None:
        self._runner = MockRunner(results)

    def _prepare_query(
        self,
        text: str,
        context: object,
        domains: set[str] | None,
    ) -> tuple[MockQuery, None]:
        return MockQuery(raw_text=text), None


def test_labeled_example_roundtrip_jsonl(tmp_path):
    examples = [
        LabeledExample(
            query_text="United States",
            expected_entity_id="country/USA",
            source_adapter="cldr",
            domain="geo",
            top_entity_id="country/USA",
            raw_score=0.9,
            label=1,
        ),
        LabeledExample(
            query_text="France",
            expected_entity_id="country/FRA",
            source_adapter="cldr",
            domain="geo",
        ),
    ]
    path = tmp_path / "examples.jsonl"
    save_examples_jsonl(examples, path)
    loaded = load_examples_jsonl(path)

    assert len(loaded) == 2
    assert loaded[0].query_text == "United States"
    assert loaded[0].expected_entity_id == "country/USA"
    assert loaded[0].raw_score == pytest.approx(0.9)
    assert loaded[0].label == 1
    assert loaded[1].raw_score is None
    assert loaded[1].label is None


def test_calibration_dataset_filters_unlabeled():
    examples = [
        LabeledExample(
            query_text="France",
            expected_entity_id="country/FRA",
            source_adapter="cldr",
            domain="geo",
            raw_score=0.8,
            label=1,
        ),
        LabeledExample(
            query_text="Germany",
            expected_entity_id="country/DEU",
            source_adapter="cldr",
            domain="geo",
            # No raw_score or label — should be filtered out
        ),
        LabeledExample(
            query_text="Spain",
            expected_entity_id="country/ESP",
            source_adapter="cldr",
            domain="geo",
            raw_score=0.5,
            label=0,
        ),
    ]
    dataset = CalibrationDataset(domain="geo", examples=examples)
    labeled = dataset.labeled_examples

    assert len(labeled) == 2
    assert labeled[0].query_text == "France"
    assert labeled[1].query_text == "Spain"
    assert dataset.scores == pytest.approx([0.8, 0.5])
    assert dataset.labels == [1, 0]


def test_label_examples_correct_match():
    resolver = MockResolver({"United States": ("country/USA", 0.95)})
    example = LabeledExample(
        query_text="United States",
        expected_entity_id="country/USA",
        source_adapter="cldr",
        domain="geo",
    )
    labeled = label_examples([example], resolver)

    assert len(labeled) == 1
    ex = labeled[0]
    assert ex.top_entity_id == "country/USA"
    assert ex.raw_score == pytest.approx(0.95)
    assert ex.label == 1


def test_label_examples_wrong_match():
    resolver = MockResolver({"France": ("country/GBR", 0.6)})
    example = LabeledExample(
        query_text="France",
        expected_entity_id="country/FRA",
        source_adapter="cldr",
        domain="geo",
    )
    labeled = label_examples([example], resolver)

    assert len(labeled) == 1
    ex = labeled[0]
    assert ex.top_entity_id == "country/GBR"
    assert ex.raw_score == pytest.approx(0.6)
    assert ex.label == 0


def test_label_examples_no_result():
    resolver = MockResolver({})  # Returns NO_MATCH for everything
    example = LabeledExample(
        query_text="Atlantis",
        expected_entity_id="country/ATL",
        source_adapter="cldr",
        domain="geo",
    )
    labeled = label_examples([example], resolver)

    assert len(labeled) == 1
    ex = labeled[0]
    # When NO_MATCH: top_entity_id=None, raw_score=None, label=0
    assert ex.top_entity_id is None
    assert ex.label == 0  # None entity_id != expected → label=0
