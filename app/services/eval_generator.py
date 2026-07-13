"""AI test-case generator for workflow evaluation.

Given a workflow, synthesize realistic user queries a real operator would
send to that multi-agent system, plus an optional expected answer where the
generator is confident. Uses the small, fast, JSON-mode-capable *router*
LLM (`build_router_llm`) — case generation is a structured task, not
domain reasoning.

ponytail: generation failure raises so the caller can surface a 4xx/5xx
instead of persisting a run with zero cases.
"""

from __future__ import annotations

import json
import re
from typing import Optional

from pydantic import BaseModel, Field

from app.config.settings import Settings
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.llm import build_router_llm
from app.schemas.eval import EvalCase
from app.schemas.workflow import ProjectedAgent
from app.services import get_workflow
from app.services.workflow_service import find_agent_nodes

logger = get_logger(__name__)


class _CaseOut(BaseModel):
    query: str
    expected_answer: Optional[str] = None


class _CasesOut(BaseModel):
    cases: list[_CaseOut]


_PROMPT = """You are designing an evaluation suite for an enterprise multi-agent system.

Workflow: {workflow_name}
{workflow_description}

Agents in this workflow (each can be routed to):
{agents_block}

Produce {num_cases} realistic, distinct user queries that an operator or
customer might send to this system. Cover different agents and intents
(routing, lookups, analysis, disputes, planning). Prefer queries the
listed agents can actually handle. For each, include a concise
`expected_answer` ONLY when the correct answer is objectively knowable
from the workflow's purpose; otherwise omit it.

Respond with ONLY a JSON object:
{{"cases": [{{"query": "...", "expected_answer": "..."}}, ...]}}
"""


def _agents_block(agents: list[ProjectedAgent]) -> str:
    if not agents:
        return "(no agents defined — general-purpose queries)"
    lines = []
    for a in agents:
        caps = ", ".join(a.capabilities[:5]) if a.capabilities else "n/a"
        lines.append(f"- id={a.id} | role={a.role} | can: {caps}")
    return "\n".join(lines)


def _build_prompt(*, workflow_name: str, description: str,
                  agents: list[ProjectedAgent], num_cases: int) -> str:
    desc = f"Description: {description}" if description else ""
    return _PROMPT.format(
        workflow_name=workflow_name or "workflow",
        workflow_description=desc,
        agents_block=_agents_block(agents),
        num_cases=num_cases,
    )


def _extract_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", text or "", flags=re.DOTALL)
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("no JSON object in generator output")
    return json.loads(match.group(0))


async def generate_cases(
    workflow_id: str, *, num_cases: int = 5, settings: Optional[Settings] = None
) -> list[EvalCase]:
    """Generate `num_cases` test cases for a workflow. Raises on failure."""
    if settings is None:
        from app.config.settings import get_settings
        settings = get_settings()

    workflow = await get_workflow(workflow_id)  # NotFoundError -> 404
    agents = [ProjectedAgent.from_node(n) for n in find_agent_nodes(workflow)]
    prompt = _build_prompt(
        workflow_name=workflow.name,
        description=workflow.description,
        agents=agents,
        num_cases=num_cases,
    )

    llm = build_router_llm(settings)
    out: Optional[_CasesOut] = None
    try:
        out = await llm.with_structured_output(_CasesOut).ainvoke(prompt)
    except Exception as e:
        logger.debug("case-gen structured output failed, falling back: %s", e)
        try:
            raw = await llm.ainvoke(prompt)
            content = getattr(raw, "content", raw)
            if isinstance(content, list):
                content = "".join(
                    p.get("text", "") if isinstance(p, dict) else str(p)
                    for p in content
                )
            parsed = _extract_json(str(content))
            out = _CasesOut.model_validate(parsed)
        except Exception as e2:
            logger.warning("case generation failed for %s: %s", workflow_id, e2)
            raise RuntimeError(f"case generation failed: {e2}") from e2

    cases = [
        EvalCase(query=c.query, expected_answer=c.expected_answer)
        for c in out.cases
        if c.query and c.query.strip()
    ]
    if not cases:
        raise RuntimeError("case generation produced no usable cases")
    return cases
