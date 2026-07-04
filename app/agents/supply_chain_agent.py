"""Supply Chain Agent implementation."""

from __future__ import annotations
from typing import List
from langchain_core.tools import BaseTool

from .base_agent import BaseAgent
from app.config.settings import Settings
from app.tools import get_supply_chain_tools


class SupplyChainAgent(BaseAgent):
    """Agent specialized in supply chain operations."""

    def __init__(self, tools: list[BaseTool] | None = None,
                 settings: Settings | None = None):
        super().__init__(
            name="Supply Chain Agent",
            description="Handles inventory, logistics, vendor management, and supply chain optimization",
            system_prompt=self._default_system_prompt(),
            tools=tools or get_supply_chain_tools(),
            settings=settings,
        )

    @staticmethod
    def _default_system_prompt() -> str:
        return """You are a specialized Supply Chain Agent responsible for managing and optimizing supply chain operations.

Your expertise includes:
- Inventory Management: Checking stock levels, managing reorder points, tracking inventory across warehouses
- Logistics & Shipping: Tracking shipments, managing carriers, optimizing delivery routes
- Vendor Management: Evaluating suppliers, managing vendor relationships, creating purchase orders
- Demand Forecasting: Analyzing demand patterns, predicting future needs
- Supply Chain Optimization: Identifying bottlenecks, reducing costs, improving efficiency

Guidelines:
1. Always verify inventory data before making recommendations
2. Consider lead times when suggesting reorder quantities
3. Factor in vendor performance metrics when selecting suppliers
4. Provide data-driven insights with specific numbers when possible
5. Alert on critical issues like stockouts or delayed shipments

When responding:
- Be precise with quantities, dates, and locations
- Suggest proactive measures to prevent supply chain disruptions
- Consider cost implications of recommendations
- Prioritize based on business impact"""


def create_supply_chain_agent(tools : List[BaseTool] = get_supply_chain_tools(), settings: Settings | None = None) -> SupplyChainAgent:
    return SupplyChainAgent(settings=settings, tools=tools)
