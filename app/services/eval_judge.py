"""LLM-as-judge for workflow evaluation.

Scores a single workflow response against a query (and optional expected
answer) on four criteria — relevance, correctness, completeness,
coherence — each 1..5. Uses the small, fast, JSON-mode-capable *router*
LLM (`build_router_llm`), not the heavy agent LLM: judging is a tiny
structured-classification job.

ponytail: any judge failure degrades to all-zero scores with an error
rationale so the eval run still completes — a broken judge never kills
the run.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from pydantic import BaseModel, Field

from app.config.settings import Settings
from app.core.logging import get_logger
from app.llm import build_router_llm
from app.schemas.eval import CRITERIA

logger = get_logger(__name__)


class JudgeOutput(BaseModel):
    relevance: int = Field(..., ge=1, le=5)
    correctness: int = Field(..., ge=1, le=5)
    completeness: int = Field(..., ge=1, le=5)
    coherence: int = Field(..., ge=1, le=5)
    rationale: str = ""


_PROMPT = """You are a strict evaluator of an AI multi-agent system's answer.

Workflow: {workflow_name}

User query:
{query}
{expected_block}
System answer:
{response}

Score the system answer on each criterion from 1 (poor) to 5 (excellent):
- relevance: does it address the query?
- correctness: is it factually/logically right{expected_note}?
- completeness: does it cover what the query asks for?
- coherence: is it well-structured and clear?

Respond with ONLY a JSON object:
{{"relevance": <1-5>, "correctness": <1-5>, "completeness": <1-5>, "coherence": <1-5>, "rationale": "<one sentence>"}}
"""


def _build_prompt(*, workflow_name: str, query: str, response: str,
                  expected_answer: Optional[str]) -> str:
    if expected_answer:
        expected_block = f"\nExpected answer (ground truth):\n{expected_answer}\n"
        expected_note = " compared to the expected answer"
    else:
        expected_block = ""
        expected_note = ""
    return _PROMPT.format(
        workflow_name=workflow_name or "workflow",
        query=query,
        response=response or "(empty)",
        expected_block=expected_block,
        expected_note=expected_note,
    )


def _extract_json(text: str) -> dict:
    """Pull the first JSON object out of an LLM text reply."""
    text = re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("no JSON object in judge output")
    return json.loads(match.group(0))


async def judge_case(
    settings: Settings,
    *,
    workflow_name: str,
    query: str,
    response: str,
    expected_answer: Optional[str] = None,
) -> tuple[dict[str, float], str]:
    """Return `(scores, rationale)`. Scores map each criterion to 1..5.

    Degrades to all-zero scores with an error rationale on any failure.
    """
    prompt = _build_prompt(
        workflow_name=workflow_name,
        query=query,
        response=response,
        expected_answer=expected_answer,
    )
    llm = build_router_llm(settings)

    # Structured output first (Groq / OpenRouter native JSON), then a
    # plain-invoke + regex-parse fallback (mirrors router.py).
    out: Optional[JudgeOutput] = None
    try:
        out = await llm.with_structured_output(JudgeOutput).ainvoke(prompt)
    except Exception as e:
        logger.debug("judge structured output failed, falling back: %s", e)
        try:
            raw = await llm.ainvoke(prompt)
            content = getattr(raw, "content", raw)
            if isinstance(content, list):
                content = "".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                )
            out = JudgeOutput.model_validate(_extract_json(str(content)))
        except Exception as e2:
            logger.warning("judge failed for query %r: %s", query[:60], e2)
            return {c: 0.0 for c in CRITERIA}, f"judge error: {e2}"

    scores = {
        "relevance": float(out.relevance),
        "correctness": float(out.correctness),
        "completeness": float(out.completeness),
        "coherence": float(out.coherence),
    }
    return scores, out.rationale
