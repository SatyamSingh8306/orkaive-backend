"""Compliance Agent implementation."""

from __future__ import annotations
from typing import List

from langchain_core.tools import BaseTool

from .base_agent import BaseAgent
from app.config.settings import Settings
from app.tools import get_compliance_tools


class ComplianceAgent(BaseAgent):
    """Agent specialized in audit, regulatory, and policy compliance."""

    def __init__(self, tools: list[BaseTool] | None = None,
                 settings: Settings | None = None):
        super().__init__(
            name="Compliance Agent",
            description="Handles regulatory compliance, audits, policy enforcement, and risk management",
            system_prompt=self._default_system_prompt(),
            tools=tools or get_compliance_tools(),
            settings=settings,
        )

    @staticmethod
    def _default_system_prompt() -> str:
        return """You are a specialized Compliance Agent responsible for audit, regulatory, and policy matters.

Your expertise includes:
- Regulatory Compliance: GDPR, SOX, HIPAA, PCI-DSS, and other regulations
- Audit Management: Running checks, tracking findings, ensuring remediation
- Policy Enforcement: Retrieving and applying policy documents
- Incident Reporting: Documenting breaches, escalations, and timelines
- Risk Management: Identifying exposure, recommending controls

Guidelines:
1. Always cite the regulation or policy when flagging an issue
2. Be conservative — when in doubt, escalate via conflict_resolution
3. Preserve audit trails and exact language where possible
4. Distinguish between confirmed violations and risk indicators

When responding:
- Reference the specific regulation/policy by name
- Provide severity and recommended remediation
- Suggest compliance owners and timelines where applicable"""


def create_compliance_agent(tools : List[BaseTool] = get_compliance_tools(), settings: Settings | None = None) -> ComplianceAgent:
    return ComplianceAgent(settings=settings, tools=tools)
