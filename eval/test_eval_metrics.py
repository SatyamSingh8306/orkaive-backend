"""Unit tests for `compute_metrics` — pure scoring math, no LLM / Mongo.

Run:
    pytest eval/test_eval_metrics.py -v
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from app.schemas.eval import EvalCriterionScore
from app.services.eval_service import compute_metrics


def _ok(scores, duration=100.0):
    overall = sum(scores.values()) / len(scores) if scores else 0.0
    return EvalCriterionScore(
        query="q", response="r", duration_ms=duration,
        success=True, scores=scores, overall_score=overall,
    )


def test_empty_is_all_zero():
    m = compute_metrics([])
    assert m.total_cases == 0
    assert m.evaluated == 0
    assert m.errors == 0
    assert m.success_rate == 0.0
    assert m.overall_score == 0.0
    assert m.criteria_averages == {}


def test_all_good():
    scores = {"relevance": 5, "correctness": 4, "completeness": 5, "coherence": 4}
    m = compute_metrics([_ok(scores), _ok(scores)])
    assert m.total_cases == 2
    assert m.evaluated == 2
    assert m.errors == 0
    assert m.success_rate == 1.0
    assert m.criteria_averages["relevance"] == 5.0
    assert m.criteria_averages["correctness"] == 4.0
    # composite = mean of the four criteria averages = (5+4+5+4)/4 = 4.5
    assert m.overall_score == 4.5


def test_error_case_excluded_from_quality_but_counted():
    good = _ok({"relevance": 4, "correctness": 4, "completeness": 4, "coherence": 4})
    errored = EvalCriterionScore(
        query="q2", success=False, error="boom", duration_ms=50.0, scores={},
    )
    m = compute_metrics([good, errored])
    assert m.total_cases == 2
    assert m.errors == 1
    assert m.evaluated == 1  # only the judged one
    assert m.success_rate == 0.5
    # quality averages ignore the errored case → still 4.0
    assert m.criteria_averages["relevance"] == 4.0
    assert m.overall_score == 4.0
    # avg duration is over both cases (both have a duration)
    assert m.avg_duration_ms == 75.0


def test_judge_failure_zero_scores_excluded():
    # success=True but judge returned empty scores (degraded) → not evaluated.
    judge_failed = EvalCriterionScore(
        query="q", response="r", success=True, duration_ms=100.0, scores={},
    )
    good = _ok({"relevance": 3, "correctness": 3, "completeness": 3, "coherence": 3})
    m = compute_metrics([judge_failed, good])
    assert m.total_cases == 2
    assert m.errors == 0  # both "succeeded" at running
    assert m.evaluated == 1  # only one was actually judged
    assert m.overall_score == 3.0


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
