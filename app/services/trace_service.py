"""Trace service — Redis-backed, async, paginated.

Replaces the previous sync `trace_logger.py`. All reads return
Pydantic models; all writes take Pydantic models. The dashboard reads
through this service rather than poking the Redis hash directly.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, Optional
from uuid import uuid4

from app.core.logging import get_logger
from app.db.redis import get_async_redis_client
from app.schemas.trace import (
    DashboardRunSummary,
    DashboardStepDetail,
    StepStatus,
    StepType,
    TraceEvent,
    TraceFilter,
    WorkflowRun,
)

logger = get_logger(__name__)

_RUNS_KEY = "workflow_runs"
_EVENTS_KEY = "trace_events"
_RUN_EVENTS_KEY = "run_events"


def _ser(obj: Any) -> Any:
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _ser(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_ser(x) for x in obj]
    return obj


def _deser_run(raw: str) -> WorkflowRun:
    run = WorkflowRun.model_validate_json(raw)
    # ponytail: pre-fix rows have naive datetimes (datetime.utcnow was
    # used before). Coerce to UTC-aware so comparisons downstream
    # don't mix naive/aware and TypeError.
    if run.started_at.tzinfo is None:
        run.started_at = run.started_at.replace(tzinfo=timezone.utc)
    if run.completed_at is not None and run.completed_at.tzinfo is None:
        run.completed_at = run.completed_at.replace(tzinfo=timezone.utc)
    return run


def _deser_event(raw: str) -> TraceEvent:
    ev = TraceEvent.model_validate_json(raw)
    if ev.start_time.tzinfo is None:
        ev.start_time = ev.start_time.replace(tzinfo=timezone.utc)
    if ev.end_time is not None and ev.end_time.tzinfo is None:
        ev.end_time = ev.end_time.replace(tzinfo=timezone.utc)
    return ev


class TraceService:
    """Service for workflow trace data."""

    def __init__(self) -> None:
        self.redis = get_async_redis_client()

    # ---- runs -------------------------------------------------------------

    async def start_run(
        self,
        *,
        workflow_id: str,
        workflow_name: str,
        run_id: Optional[str] = None,
        user_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        input_data: Any = None,
        metadata: Optional[dict] = None,
    ) -> WorkflowRun:
        run = WorkflowRun(
            run_id=run_id or str(uuid4()),
            workflow_id=workflow_id,
            workflow_name=workflow_name,
            user_id=user_id,
            conversation_id=conversation_id,
            input=input_data,
            metadata=metadata or {},
        )
        await self.redis.hset(
            _RUNS_KEY, run.run_id,
            json.dumps(_ser(run.model_dump())),
        )
        # ponytail: the route may have already called end_run before
        # we got here. Honor the tombstone so the run doesn't get
        # stuck at `started`.
        tomb = await self.redis.get(f"run_close_intent:{run.run_id}")
        if tomb:
            try:
                payload = json.loads(tomb)
                run.status = StepStatus(payload.get("status") or StepStatus.COMPLETED)
                run.error = payload.get("error")
                run.completed_at = datetime.now(timezone.utc)
                run.duration_ms = (run.completed_at - run.started_at).total_seconds() * 1000
                await self.redis.hset(
                    _RUNS_KEY, run.run_id,
                    json.dumps(_ser(run.model_dump())),
                )
                await self.redis.delete(f"run_close_intent:{run.run_id}")
                await self._publish("run_completed", run.model_dump())
            except Exception:
                pass
        await self._publish("run_started", run.model_dump())
        return run

    async def end_run(
        self,
        *,
        run_id: str,
        output: Any = None,
        error: Optional[str] = None,
        status: Optional[StepStatus] = None,
    ) -> Optional[WorkflowRun]:
        # ponytail: start_run races with the route's end_run on cancel.
        # If the row isn't there yet, leave a 5-min tombstone that
        # start_run will honor when it eventually writes the row.
        raw: Optional[str] = None
        for _ in range(4):
            raw = await self.redis.hget(_RUNS_KEY, run_id)
            if raw:
                break
            await asyncio.sleep(0.25)
        if not raw:
            final = status or (StepStatus.COMPLETED if error is None else StepStatus.ERROR)
            await self.redis.set(
                f"run_close_intent:{run_id}",
                json.dumps({"status": final.value, "error": error}),
                ex=300,
            )
            return None
        run = _deser_run(raw)
        # Idempotent: if the run is already in a terminal state, don't
        # overwrite it. The finally clause in `Orchestrator.stream` may
        # call this twice (once from the inner try, once from finally)
        # on the happy path; without this guard, we'd re-publish a stale
        # "run_completed" event and clobber a more accurate final state.
        if run.status in (StepStatus.COMPLETED, StepStatus.ERROR, StepStatus.CANCELLED):
            return run
        run.completed_at = datetime.now(timezone.utc)
        run.duration_ms = (run.completed_at - run.started_at).total_seconds() * 1000
        run.output = output
        run.error = error
        run.status = status or (StepStatus.COMPLETED if error is None else StepStatus.ERROR)
        await self.redis.hset(_RUNS_KEY, run_id, json.dumps(_ser(run.model_dump())))
        await self._publish("run_completed", run.model_dump())
        return run

    # ---- steps ------------------------------------------------------------

    async def start_step(
        self,
        *,
        run_id: str,
        name: str,
        step_type: StepType,
        input_data: Any = None,
        parent_step_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> TraceEvent:
        # Look up the workflow_id from the run
        run_raw = await self.redis.hget(_RUNS_KEY, run_id)
        workflow_id = ""
        if run_raw:
            workflow_id = _deser_run(run_raw).workflow_id

        event = TraceEvent(
            run_id=run_id,
            workflow_id=workflow_id,
            step_type=step_type,
            name=name,
            status=StepStatus.STARTED,
            input=input_data,
            parent_step_id=parent_step_id,
            metadata=metadata or {},
        )
        await self._store_event(event)
        await self._increment_step_count(run_id, "total_steps")
        await self._publish("step_started", event.model_dump())
        return event

    async def end_step(
        self,
        *,
        run_id: str,
        step_id: str,
        output: Any = None,
        error: Optional[str] = None,
        token_usage: Optional[dict[str, int]] = None,
    ) -> Optional[TraceEvent]:
        raw = await self.redis.hget(f"{_RUN_EVENTS_KEY}:{run_id}", step_id)
        if not raw:
            return None
        event = _deser_event(raw)
        event.end_time = datetime.now(timezone.utc)
        event.duration_ms = (event.end_time - event.start_time).total_seconds() * 1000
        event.output = output
        event.error = error
        event.token_usage = token_usage
        event.status = StepStatus.COMPLETED if error is None else StepStatus.ERROR
        await self._store_event(event)
        if error:
            await self._increment_step_count(run_id, "error_steps")
        else:
            await self._increment_step_count(run_id, "completed_steps")
        await self._publish("step_completed", event.model_dump())
        return event

    # ---- reads ------------------------------------------------------------

    async def list_runs(self, filters: Optional[TraceFilter] = None) -> list[DashboardRunSummary]:
        all_runs = await self.redis.hgetall(_RUNS_KEY)
        runs: list[DashboardRunSummary] = []
        for raw in all_runs.values():
            run = _deser_run(raw)
            if filters:
                if filters.workflow_id and run.workflow_id != filters.workflow_id:
                    continue
                if filters.user_id and run.user_id != filters.user_id:
                    continue
                if filters.status and run.status != filters.status:
                    continue
                if filters.start_date and run.started_at < filters.start_date:
                    continue
                if filters.end_date and run.started_at > filters.end_date:
                    continue
            runs.append(DashboardRunSummary(
                run_id=run.run_id,
                workflow_id=run.workflow_id,
                workflow_name=run.workflow_name,
                status=run.status,
                started_at=run.started_at,
                duration_ms=run.duration_ms,
                total_steps=run.total_steps,
                completed_steps=run.completed_steps,
                error_steps=run.error_steps,
                has_error=run.error_steps > 0,
            ))

        runs.sort(key=lambda x: x.started_at, reverse=True)
        if filters:
            runs = runs[filters.offset : filters.offset + filters.limit]
        return runs

    async def get_run_details(self, run_id: str) -> Optional[dict[str, Any]]:
        run_raw = await self.redis.hget(_RUNS_KEY, run_id)
        if not run_raw:
            return None
        run = _deser_run(run_raw)
        events_raw = await self.redis.hgetall(f"{_RUN_EVENTS_KEY}:{run_id}")
        events = [_deser_event(r) for r in events_raw.values()]
        steps = self._build_hierarchy(events)
        return {
            "run": _ser(run.model_dump()),
            "steps": [_ser(s.model_dump()) for s in steps],
        }

    # ---- internals --------------------------------------------------------

    async def _store_event(self, event: TraceEvent) -> None:
        await self.redis.hset(
            f"{_RUN_EVENTS_KEY}:{event.run_id}",
            event.step_id,
            json.dumps(_ser(event.model_dump())),
        )
        await self.redis.hset(
            _EVENTS_KEY,
            f"{event.run_id}:{event.step_id}",
            json.dumps(_ser(event.model_dump())),
        )

    async def _increment_step_count(self, run_id: str, field: str) -> None:
        run_raw = await self.redis.hget(_RUNS_KEY, run_id)
        if not run_raw:
            return
        run = _deser_run(run_raw)
        current = getattr(run, field, 0)
        setattr(run, field, current + 1)
        await self.redis.hset(_RUNS_KEY, run_id, json.dumps(_ser(run.model_dump())))

    async def _publish(self, event_type: str, data: dict[str, Any]) -> None:
        try:
            message = {
                "type": event_type,
                "data": _ser(data),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            await self.redis.publish(_EVENTS_KEY, json.dumps(message))
        except Exception as e:
            logger.warning("trace: redis publish failed: %s", e)

    def _build_hierarchy(self, events: list[TraceEvent]) -> list[DashboardStepDetail]:
        steps_by_id: dict[str, DashboardStepDetail] = {}
        roots: list[DashboardStepDetail] = []
        for event in events:
            step = DashboardStepDetail(
                step_id=event.step_id,
                parent_step_id=event.parent_step_id,
                step_type=event.step_type,
                name=event.name,
                status=event.status,
                start_time=event.start_time,
                end_time=event.end_time,
                duration_ms=event.duration_ms,
                input_preview=self._truncate(event.input),
                output_preview=self._truncate(event.output),
                input=event.input,
                output=event.output,
                error=event.error,
                metadata=event.metadata,
            )
            steps_by_id[event.step_id] = step
        for step in steps_by_id.values():
            if step.parent_step_id and step.parent_step_id in steps_by_id:
                steps_by_id[step.parent_step_id].children.append(step)
            else:
                roots.append(step)
        for s in steps_by_id.values():
            s.children.sort(key=lambda x: x.start_time)
        roots.sort(key=lambda x: x.start_time)
        return roots

    def _truncate(self, data: Any, max_length: int = 200) -> Optional[str]:
        if data is None:
            return None
        s = str(data)
        return s if len(s) <= max_length else s[:max_length] + "..."


# Singleton
_trace: TraceService | None = None


def get_trace_service() -> TraceService:
    global _trace
    if _trace is None:
        _trace = TraceService()
    return _trace
