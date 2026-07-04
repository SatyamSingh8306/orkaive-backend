"""Process Agent Tools - Workflow and BPM."""

from typing import Dict, List, Optional, Any
from langchain_core.tools import tool
from datetime import datetime


@tool
def get_workflow_status(
    workflow_id: Optional[str] = None,
    workflow_type: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get status of business workflows.
    
    Args:
        workflow_id: Specific workflow ID to check
        workflow_type: Type of workflow (approval, onboarding, procurement, etc.)
        
    Returns:
        Workflow status and details
    """
    workflows = {
        "WF-001": {
            "type": "approval",
            "name": "Budget Approval - Q1 Marketing",
            "status": "pending_approval",
            "current_step": "manager_review",
            "steps_completed": 2,
            "total_steps": 4,
            "created_by": "john.doe@company.com",
            "assignee": "jane.smith@company.com",
            "priority": "high",
            "due_date": "2024-12-20"
        },
        "WF-002": {
            "type": "onboarding",
            "name": "Employee Onboarding - New Hire",
            "status": "in_progress",
            "current_step": "it_setup",
            "steps_completed": 3,
            "total_steps": 6,
            "created_by": "hr@company.com",
            "assignee": "it.support@company.com",
            "priority": "normal",
            "due_date": "2024-12-22"
        },
        "WF-003": {
            "type": "procurement",
            "name": "Equipment Purchase Request",
            "status": "approved",
            "current_step": "completed",
            "steps_completed": 5,
            "total_steps": 5,
            "created_by": "ops@company.com",
            "completed_at": "2024-12-15"
        }
    }
    
    if workflow_id:
        if workflow_id in workflows:
            return {"success": True, "data": workflows[workflow_id]}
        return {"success": False, "error": f"Workflow {workflow_id} not found"}
    
    if workflow_type:
        filtered = {
            wid: wdata for wid, wdata in workflows.items()
            if wdata["type"] == workflow_type
        }
        return {"success": True, "data": filtered}
    
    return {"success": True, "data": workflows}


@tool
def create_workflow(
    workflow_type: str,
    name: str,
    description: str,
    assignee: str,
    priority: str = "normal"
) -> Dict[str, Any]:
    """
    Create a new workflow.
    
    Args:
        workflow_type: Type of workflow (approval, onboarding, procurement, etc.)
        name: Workflow name/title
        description: Detailed description
        assignee: Email of the assignee
        priority: Priority level (low, normal, high, urgent)
        
    Returns:
        Created workflow details
    """
    workflow_id = f"WF-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    workflow_templates = {
        "approval": ["submit", "manager_review", "director_review", "finance_review", "complete"],
        "onboarding": ["paperwork", "hr_setup", "it_setup", "training", "team_intro", "complete"],
        "procurement": ["request", "budget_check", "vendor_select", "approval", "order", "complete"],
    }
    
    steps = workflow_templates.get(workflow_type, ["start", "process", "complete"])
    
    return {
        "success": True,
        "data": {
            "workflow_id": workflow_id,
            "type": workflow_type,
            "name": name,
            "description": description,
            "status": "created",
            "current_step": steps[0],
            "steps": steps,
            "assignee": assignee,
            "priority": priority,
            "created_at": datetime.now().isoformat()
        }
    }


@tool
def approve_workflow_step(
    workflow_id: str,
    approver: str,
    decision: str,
    comments: Optional[str] = None
) -> Dict[str, Any]:
    """
    Approve or reject a workflow step.
    
    Args:
        workflow_id: Workflow ID to act on
        approver: Email of the approver
        decision: 'approve' or 'reject'
        comments: Optional comments
        
    Returns:
        Updated workflow status
    """
    return {
        "success": True,
        "data": {
            "workflow_id": workflow_id,
            "action": decision,
            "actioned_by": approver,
            "comments": comments,
            "actioned_at": datetime.now().isoformat(),
            "new_status": "approved" if decision == "approve" else "rejected"
        }
    }


@tool
def get_pending_tasks(
    assignee: Optional[str] = None,
    priority: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get pending tasks for workflows.
    
    Args:
        assignee: Filter by assignee email
        priority: Filter by priority
        
    Returns:
        List of pending tasks
    """
    tasks = [
        {
            "task_id": "TASK-001",
            "workflow_id": "WF-001",
            "title": "Review Budget Proposal",
            "assignee": "jane.smith@company.com",
            "priority": "high",
            "due_date": "2024-12-20",
            "status": "pending"
        },
        {
            "task_id": "TASK-002", 
            "workflow_id": "WF-002",
            "title": "Setup Workstation",
            "assignee": "it.support@company.com",
            "priority": "normal",
            "due_date": "2024-12-19",
            "status": "in_progress"
        },
        {
            "task_id": "TASK-003",
            "workflow_id": "WF-001",
            "title": "Final Approval",
            "assignee": "director@company.com",
            "priority": "high",
            "due_date": "2024-12-21",
            "status": "pending"
        }
    ]
    
    filtered = tasks
    if assignee:
        filtered = [t for t in filtered if t["assignee"] == assignee]
    if priority:
        filtered = [t for t in filtered if t["priority"] == priority]
    
    return {"success": True, "data": filtered, "count": len(filtered)}


@tool
def get_process_metrics(
    process_type: Optional[str] = None,
    time_period: str = "last_30_days"
) -> Dict[str, Any]:
    """
    Get process performance metrics.
    
    Args:
        process_type: Type of process to analyze
        time_period: Time period for metrics
        
    Returns:
        Process metrics and KPIs
    """
    return {
        "success": True,
        "data": {
            "period": time_period,
            "workflows_created": 45,
            "workflows_completed": 38,
            "workflows_pending": 7,
            "average_completion_time_days": 3.5,
            "on_time_completion_rate": 0.89,
            "bottlenecks": [
                {"step": "director_review", "avg_delay_hours": 24},
                {"step": "finance_review", "avg_delay_hours": 12}
            ],
            "by_type": {
                "approval": {"count": 20, "avg_time": 2.5},
                "onboarding": {"count": 15, "avg_time": 5.0},
                "procurement": {"count": 10, "avg_time": 4.0}
            }
        }
    }


def get_process_tools():
    """Return all process tools."""
    return [
        get_workflow_status,
        create_workflow,
        approve_workflow_step,
        get_pending_tasks,
        get_process_metrics,
    ]