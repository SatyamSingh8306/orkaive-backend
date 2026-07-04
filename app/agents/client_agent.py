"""Client Agent implementation."""

from __future__ import annotations
from ast import List

from langchain_core.tools import BaseTool

from .base_agent import BaseAgent
from app.config.settings import Settings
from app.tools import get_client_tools


class ClientAgent(BaseAgent):
    """Agent specialized in customer care and sales operations."""

    def __init__(self, tools: list[BaseTool] | None = None,
                 settings: Settings | None = None,
                 temperature: float | None = 0.3):
        super().__init__(
            name="Client Agent",
            description="Handles customer support, CRM operations, sales pipeline, and customer communications",
            system_prompt=self._default_system_prompt(),
            tools=tools or get_client_tools(),
            settings=settings,
            temperature=temperature,
        )

    @staticmethod
    def _default_system_prompt() -> str:
        return """You are a specialized Client Agent responsible for customer care and sales operations.

Your expertise includes:
- Customer Support: Managing tickets, resolving issues, ensuring customer satisfaction
- CRM Management: Maintaining customer records, tracking interactions, managing relationships
- Sales Operations: Managing pipeline, tracking opportunities, supporting sales team
- Customer Communications: Drafting emails, managing outreach, maintaining engagement
- Sentiment Analysis: Understanding customer mood, identifying at-risk customers

Guidelines:
1. Always prioritize customer satisfaction
2. Personalize interactions based on customer history
3. Escalate critical issues promptly
4. Maintain professional and empathetic communication
5. Look for upsell/cross-sell opportunities appropriately

When responding:
- Use customer's name and reference their history
- Provide specific solutions, not generic responses
- Set clear expectations on resolution timelines
- Document all interactions properly
- Consider the full customer lifecycle"""


def create_client_agent(tools : List[BaseTool] = get_client_tools(), settings: Settings | None = None) -> ClientAgent:
    return ClientAgent(settings=settings, tools=tools)
