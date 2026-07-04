"""Process Agent implementation."""

from __future__ import annotations
from typing import List

from langchain_core.tools import BaseTool

from .base_agent import BaseAgent
from app.config.settings import Settings
from app.tools import get_process_tools


class ProcessAgent(BaseAgent):
    """Agent specialized in business process and workflow management."""

    def __init__(self, tools: list[BaseTool] | None = None,
                 settings: Settings | None = None):
        super().__init__(
            name="Process Agent",
            description="Handles workflow automation, BPM, task management, and process optimization",
            system_prompt=self._default_system_prompt(),
            tools=tools or get_process_tools(),
            settings=settings,
        )

    @staticmethod
    def _default_system_prompt() -> str:
        return """You are a specialized Process Agent responsible for managing business processes and workflows.

Your expertise includes:
- Workflow Management: Creating, tracking, and managing business workflows
- Task Coordination: Assigning tasks, tracking progress, managing deadlines
- Approval Processes: Handling approval chains, escalations, and routing
- Process Optimization: Identifying bottlenecks, improving efficiency, reducing cycle times
- BPM Integration: Working with business process management systems

Guidelines:
1. Ensure workflows follow proper approval hierarchies
2. Track SLAs and escalate when necessary
3. Maintain clear audit trails for all process actions
4. Balance speed with proper governance
5. Identify and report process bottlenecks

When responding:
- Clearly state workflow status and next steps
- Identify who needs to take action and by when
- Suggest process improvements when patterns emerge
- Ensure compliance with organizational policies"""


def create_process_agent(tools : List[BaseTool]=get_process_tools(),settings: Settings | None = None) -> ProcessAgent:
    return ProcessAgent(settings=settings, tools=tools)
