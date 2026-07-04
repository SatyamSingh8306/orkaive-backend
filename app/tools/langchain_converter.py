"""LangChain tool factory from a validated `ToolConfig`.

The previous version of this file dumped the full Mongo document
(`{tool_doc}`) into the LLM-facing description, which leaked headers, IDs,
and any other operational detail. Now the description is built from
`http_executor.project_for_llm` — only the sanitized projection.
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.schemas.tool import ToolConfig
from app.tools.http_executor import build_executor, project_for_llm


class HTTPToolInput(BaseModel):
    """Args schema shared by every HTTP-backed tool."""

    query: dict[str, Any] = Field(
        default_factory=dict,
        description="HTTP query parameters to send with the request.",
    )
    body: dict[str, Any] | None = Field(
        default=None,
        description="HTTP request body payload (for POST/PUT/PATCH).",
    )
    focus_query: str | None = Field(
        default=None,
        description=(
            "Optional semantic instruction for summarizing the response. "
            "NOT sent to the server."
        ),
    )


class LangChainToolFactory:
    """Convert a `ToolConfig` into a LangChain `StructuredTool`."""

    @staticmethod
    def from_tool_config(
        tool: ToolConfig,
        resolved_headers: dict[str, str] | None = None,
    ) -> StructuredTool:
        projection = project_for_llm(tool)
        executor = build_executor(tool, headers=resolved_headers)

        # Build a clean, single-paragraph description for the LLM.
        description = (
            f"{projection.summary}\n\n"
            f"HTTP {tool.method} tool. "
            "Use 'query' and 'body' for API parameters. "
            "Use 'focus_query' only if you need the response summarized or filtered; "
            "it is not sent to the server."
        )

        return StructuredTool.from_function(
            name=tool.name,
            description=description,
            coroutine=executor.__call__,
            args_schema=HTTPToolInput,
        )
