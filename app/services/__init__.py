"""Service layer.

Top-level re-exports. Services are organized as module-level async
functions plus a small class for stateful services. The function surface
is what the routes use.
"""

from .chat_history_service import (
    ChatHistoryService,
    get_chat_history_service,
)
from .conflict_service import (
    ConflictService,
    get_conflict_service,
)
from .llm_registry import get_summarizer_llm
from .tool_service import (
    build_langchain_tool,
    whitelist_for_llm,
)
from .trace_service import TraceService, get_trace_service
from .workflow_service import find_agent_nodes

# Re-export the canonical function-shaped services so callers can do
# `from app.services import create_workflow, get_workflow, ...` without
# caring which module they live in.
from . import tool_service as _tools
from . import workflow_service as _workflows

create_tool = _tools.create
get_tool = _tools.get
list_for_node = _tools.list_for_node
list_for_workflow = _tools.list_for_workflow
update_tool = _tools.update
delete_tool = _tools.delete
delete_for_node = _tools.delete_for_node

create_workflow = _workflows.create
get_workflow = _workflows.get
list_workflows = _workflows.list_all
update_workflow = _workflows.update
delete_workflow = _workflows.delete


__all__ = [
    "ChatHistoryService",
    "get_chat_history_service",
    "ConflictService",
    "get_conflict_service",
    "TraceService",
    "get_trace_service",
    "get_summarizer_llm",
    # workflow service
    "create_workflow",
    "get_workflow",
    "list_workflows",
    "update_workflow",
    "delete_workflow",
    "find_agent_nodes",
    # tool service
    "create_tool",
    "get_tool",
    "list_for_node",
    "list_for_workflow",
    "update_tool",
    "delete_tool",
    "delete_for_node",
    "whitelist_for_llm",
    "build_langchain_tool",
]
