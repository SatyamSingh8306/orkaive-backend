"""Optimization Agent implementation."""

from __future__ import annotations
from typing import List

from langchain_core.tools import BaseTool

from .base_agent import BaseAgent
from app.config.settings import Settings
from app.tools import get_optimization_tools


class OptimizationAgent(BaseAgent):
    """Agent specialized in analytics, simulation, and resource optimization."""

    def __init__(self, tools: list[BaseTool] | None = None,
                 settings: Settings | None = None):
        super().__init__(
            name="Optimization Agent",
            description="Handles predictive analytics, simulations, resource optimization, and KPI reporting",
            system_prompt=self._default_system_prompt(),
            tools=tools or get_optimization_tools(),
            settings=settings,
        )

    @staticmethod
    def _default_system_prompt() -> str:
        return """You are a specialized Optimization Agent responsible for analytics, simulation, and resource optimization.

Your expertise includes:
- Predictive Analytics: Demand, churn, revenue, capacity forecasting
- Resource Optimization: Allocations that respect constraints
- Simulations: Monte Carlo and scenario-based risk analysis
- KPI Reporting: Performance metrics, trends, benchmark deltas

Guidelines:
1. Always state confidence intervals, not just point estimates
2. Document assumptions used in any model
3. Cross-check predictions against recent ground truth when possible
4. Recommend the most impactful optimizations first

When responding:
- Quantify expected impact (% improvement, $ saved, risk reduced)
- Surface input data dependencies
- Flag low-confidence results"""


def create_optimization_agent(tools : List[BaseTool] = get_optimization_tools(), settings: Settings | None = None) -> OptimizationAgent:
    return OptimizationAgent(settings=settings, tools=tools)
