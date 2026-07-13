"""Evaluation service — single owner of the `eval_runs` collection.

An eval run executes a workflow against a batch of test cases, scores each
output with the LLM judge, aggregates the results, and persists everything
in one document.

`compute_metrics` is a **pure** function (no Mongo, no LLM) so the scoring
math is unit-testable without any infrastructure.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Optional

from bson import ObjectId
from bson.errors import InvalidId

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.config.settings import get_settings
from app.db.mongodb import get_database
from app.schemas.eval import (
    CRITERIA,
    EvalCase,
    EvalCriterionScore,
    EvalMetrics,
    EvalRun,
)

logger = get_logger(__name__)

UTC = timezone.utc
_COLL = "eval_runs"


def _to_oid(value: str) -> ObjectId:
    try:
        return ObjectId(value)
    except (InvalidId, TypeError) as e:
        raise NotFoundError(f"Invalid eval run id: {value!r}") from e


def _doc_to_model(doc: dict[str, Any]) -> EvalRun:
    doc = dict(doc)
    if "_id" in doc:
        doc["_id"] = str(doc.pop("_id"))
    return EvalRun.model_validate(doc)


def compute_metrics(results: list[EvalCriterionScore]) -> EvalMetrics:
    """Aggregate per-case results into a scorecard. Pure — no I/O.

    - `success_rate` = fraction of cases the workflow answered without error.
    - Quality averages (`criteria_averages`, `avg_overall_score`,
      `overall_score`) are computed over cases that were actually judged
      (non-empty `scores`), so judge failures / errored cases don't drag
      the quality score to zero — they show up in `errors` instead.
    """
    total = len(results)
    errors = sum(1 for r in results if not r.success)
    evaluated = sum(1 for r in results if r.scores)

    durations = [r.duration_ms for r in results if r.duration_ms]
    avg_duration = sum(durations) / len(durations) if durations else 0.0

    criteria_averages: dict[str, float] = {}
    for crit in CRITERIA:
        vals = [r.scores[crit] for r in results if crit in r.scores]
        if vals:
            criteria_averages[crit] = round(sum(vals) / len(vals), 3)

    overalls = [r.overall_score for r in results if r.scores]
    avg_overall = round(sum(overalls) / len(overalls), 3) if overalls else 0.0

    composite = (
        round(sum(criteria_averages.values()) / len(criteria_averages), 3)
        if criteria_averages
        else 0.0
    )

    return EvalMetrics(
        total_cases=total,
        evaluated=evaluated,
        errors=errors,
        success_rate=round((total - errors) / total, 3) if total else 0.0,
        avg_duration_ms=round(avg_duration, 1),
        avg_overall_score=avg_overall,
        criteria_averages=criteria_averages,
        overall_score=composite,
    )


class EvalService:
    """Mongo-backed eval run CRUD + the background evaluation worker."""

    def _coll(self):
        return get_database()[_COLL]

    # ---- CRUD ------------------------------------------------------------

    async def create_run(
        self, *, workflow_id: str, cases: list[EvalCase]
    ) -> EvalRun:
        from app.services import get_workflow

        workflow = await get_workflow(workflow_id)  # raises if missing
        run = EvalRun(
            workflow_id=workflow_id,
            workflow_name=workflow.name,
            status="running",
            started_at=datetime.now(UTC),
            cases=cases,
        )
        doc = run.model_dump(by_alias=True, exclude={"id"}, exclude_none=True)
        result = await self._coll().insert_one(doc)
        run.id = str(result.inserted_id)
        return run

    async def get_run(self, run_id: str) -> EvalRun:
        doc = await self._coll().find_one({"_id": _to_oid(run_id)})
        if not doc:
            raise NotFoundError(f"eval run {run_id} not found")
        return _doc_to_model(doc)

    async def list_runs(
        self, *, workflow_id: str, limit: int = 50
    ) -> list[EvalRun]:
        cursor = (
            self._coll()
            .find({"workflowId": workflow_id})
            .sort("createdAt", -1)
            .limit(limit)
        )
        return [_doc_to_model(d) async for d in cursor]

    async def latest_run(self, *, workflow_id: str) -> Optional[EvalRun]:
        doc = await self._coll().find_one(
            {"workflowId": workflow_id, "status": "completed"},
            sort=[("createdAt", -1)],
        )
        return _doc_to_model(doc) if doc else None

    async def delete_run(self, run_id: str) -> None:
        result = await self._coll().delete_one({"_id": _to_oid(run_id)})
        if result.deleted_count == 0:
            raise NotFoundError(f"eval run {run_id} not found")

    async def _append_result(
        self, run_id: str, result: EvalCriterionScore
    ) -> None:
        await self._coll().update_one(
            {"_id": _to_oid(run_id)},
            {"$push": {"results": result.model_dump(by_alias=True, exclude_none=True)}},
        )

    async def _finalize(
        self,
        run_id: str,
        *,
        metrics: Optional[EvalMetrics],
        status: str,
        error: Optional[str] = None,
    ) -> None:
        update: dict[str, Any] = {
            "status": status,
            "finishedAt": datetime.now(UTC),
        }
        if metrics is not None:
            update["metrics"] = metrics.model_dump(by_alias=True, exclude_none=True)
        if error is not None:
            update["error"] = error
        await self._coll().update_one(
            {"_id": _to_oid(run_id)}, {"$set": update}
        )

    # ---- background worker ----------------------------------------------

    async def run_eval(
        self, *, workflow_id: str, run_id: str, cases: list[EvalCase]
    ) -> None:
        """Execute every case through the orchestrator, judge it, persist.

        Runs as a FastAPI BackgroundTask. Sequential (one case at a time)
        to avoid hammering the LLM. Any fatal error marks the run `failed`
        so it never hangs at `running`.
        ponytail: sequential execution, parallelize if eval batches grow.
        """
        from app.orchestrator import get_orchestrator

        settings = get_settings()
        orch = get_orchestrator()
        results: list[EvalCriterionScore] = []

        try:
            for case in cases:
                started = time.time()
                response = ""
                agents_used: list[str] = []
                agent_outputs: dict[str, Any] = {}
                success = True
                error: Optional[str] = None
                try:
                    out = await orch.run(workflow_id, case.query)
                    response = out.get("response", "") or ""
                    agents_used = out.get("agents_used", []) or []
                    agent_outputs = out.get("results", {}) or {}
                except Exception as e:  # workflow failed for this case
                    logger.warning("eval case failed: %s", e)
                    success = False
                    error = str(e)

                duration_ms = (time.time() - started) * 1000

                scores: dict[str, float] = {}
                rationale = ""
                if success:
                    from app.services.eval_judge import judge_case

                    scores, rationale = await judge_case(
                        settings,
                        workflow_name=out.get("workflow_name", ""),
                        query=case.query,
                        response=response,
                        expected_answer=case.expected_answer,
                    )
                overall = (
                    round(sum(scores.values()) / len(scores), 3) if scores else 0.0
                )

                result = EvalCriterionScore(
                    query=case.query,
                    expected_answer=case.expected_answer,
                    response=response,
                    agent_outputs=agent_outputs,
                    agents_used=agents_used,
                    duration_ms=round(duration_ms, 1),
                    success=success,
                    error=error,
                    scores=scores,
                    overall_score=overall,
                    rationale=rationale,
                )
                results.append(result)
                await self._append_result(run_id, result)

            metrics = compute_metrics(results)
            await self._finalize(run_id, metrics=metrics, status="completed")
        except Exception as e:
            logger.exception("eval run %s failed", run_id)
            await self._finalize(
                run_id, metrics=compute_metrics(results), status="failed", error=str(e)
            )


_eval_service: Optional[EvalService] = None


def get_eval_service() -> EvalService:
    global _eval_service
    if _eval_service is None:
        _eval_service = EvalService()
    return _eval_service
