"""Client Agent Tools - CRM, Sales, Customer Support."""

from typing import Dict, List, Optional, Any
from langchain_core.tools import tool
from datetime import datetime


@tool
def get_customer_info(
    customer_id: Optional[str] = None,
    email: Optional[str] = None,
    phone: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get customer information from CRM.
    
    Args:
        customer_id: Customer ID
        email: Customer email
        phone: Customer phone number
        
    Returns:
        Customer profile and history
    """
    customers = {
        "CUST-001": {
            "name": "John Smith",
            "email": "john.smith@email.com",
            "phone": "+1-555-0101",
            "company": "Tech Corp",
            "segment": "enterprise",
            "lifetime_value": 150000,
            "account_manager": "alice@company.com",
            "status": "active",
            "since": "2020-03-15",
            "recent_orders": ["ORD-1001", "ORD-0998", "ORD-0950"],
            "satisfaction_score": 4.5
        },
        "CUST-002": {
            "name": "Sarah Johnson",
            "email": "sarah.j@startup.io",
            "phone": "+1-555-0102",
            "company": "StartupIO",
            "segment": "smb",
            "lifetime_value": 25000,
            "account_manager": "bob@company.com",
            "status": "active",
            "since": "2022-08-20",
            "recent_orders": ["ORD-1002"],
            "satisfaction_score": 4.8
        }
    }
    
    if customer_id and customer_id in customers:
        return {"success": True, "data": customers[customer_id]}
    
    if email:
        for cid, cdata in customers.items():
            if cdata["email"] == email:
                return {"success": True, "data": {**cdata, "customer_id": cid}}
    
    if phone:
        for cid, cdata in customers.items():
            if cdata["phone"] == phone:
                return {"success": True, "data": {**cdata, "customer_id": cid}}
    
    return {"success": True, "data": customers}


@tool
def get_support_tickets(
    customer_id: Optional[str] = None,
    status: Optional[str] = None,
    priority: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get support tickets.
    
    Args:
        customer_id: Filter by customer
        status: Filter by status (open, in_progress, resolved, closed)
        priority: Filter by priority (low, medium, high, critical)
        
    Returns:
        List of support tickets
    """
    tickets = [
        {
            "ticket_id": "TKT-001",
            "customer_id": "CUST-001",
            "subject": "Integration Issue",
            "description": "API returning 500 errors",
            "status": "in_progress",
            "priority": "high",
            "created_at": "2024-12-17T10:00:00Z",
            "assigned_to": "support.team@company.com",
            "category": "technical"
        },
        {
            "ticket_id": "TKT-002",
            "customer_id": "CUST-002",
            "subject": "Billing Question",
            "description": "Need invoice for last month",
            "status": "open",
            "priority": "low",
            "created_at": "2024-12-18T09:00:00Z",
            "assigned_to": None,
            "category": "billing"
        },
        {
            "ticket_id": "TKT-003",
            "customer_id": "CUST-001",
            "subject": "Feature Request",
            "description": "Need bulk export functionality",
            "status": "open",
            "priority": "medium",
            "created_at": "2024-12-16T14:00:00Z",
            "assigned_to": "product@company.com",
            "category": "feature_request"
        }
    ]
    
    filtered = tickets
    if customer_id:
        filtered = [t for t in filtered if t["customer_id"] == customer_id]
    if status:
        filtered = [t for t in filtered if t["status"] == status]
    if priority:
        filtered = [t for t in filtered if t["priority"] == priority]
    
    return {"success": True, "data": filtered, "count": len(filtered)}


@tool
def create_support_ticket(
    customer_id: str,
    subject: str,
    description: str,
    priority: str = "medium",
    category: str = "general"
) -> Dict[str, Any]:
    """
    Create a new support ticket.
    
    Args:
        customer_id: Customer ID
        subject: Ticket subject
        description: Detailed description
        priority: Priority level
        category: Ticket category
        
    Returns:
        Created ticket details
    """
    ticket_id = f"TKT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    return {
        "success": True,
        "data": {
            "ticket_id": ticket_id,
            "customer_id": customer_id,
            "subject": subject,
            "description": description,
            "priority": priority,
            "category": category,
            "status": "open",
            "created_at": datetime.now().isoformat(),
            "sla_response_by": "2024-12-19T10:00:00Z"
        }
    }


@tool
def get_sales_pipeline(
    stage: Optional[str] = None,
    owner: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get sales pipeline opportunities.
    
    Args:
        stage: Filter by stage (lead, qualified, proposal, negotiation, closed_won, closed_lost)
        owner: Filter by sales owner email
        
    Returns:
        Sales pipeline data
    """
    opportunities = [
        {
            "opportunity_id": "OPP-001",
            "name": "Enterprise License - Tech Corp",
            "customer_id": "CUST-001",
            "stage": "negotiation",
            "value": 500000,
            "probability": 0.75,
            "owner": "alice@company.com",
            "expected_close": "2024-12-30",
            "next_action": "Contract review meeting"
        },
        {
            "opportunity_id": "OPP-002",
            "name": "SMB Package - StartupIO",
            "customer_id": "CUST-002",
            "stage": "proposal",
            "value": 50000,
            "probability": 0.50,
            "owner": "bob@company.com",
            "expected_close": "2025-01-15",
            "next_action": "Send revised proposal"
        },
        {
            "opportunity_id": "OPP-003",
            "name": "New Lead - BigCo",
            "customer_id": "CUST-003",
            "stage": "qualified",
            "value": 250000,
            "probability": 0.30,
            "owner": "alice@company.com",
            "expected_close": "2025-02-28",
            "next_action": "Discovery call scheduled"
        }
    ]
    
    filtered = opportunities
    if stage:
        filtered = [o for o in filtered if o["stage"] == stage]
    if owner:
        filtered = [o for o in filtered if o["owner"] == owner]
    
    pipeline_value = sum(o["value"] * o["probability"] for o in filtered)
    
    return {
        "success": True,
        "data": {
            "opportunities": filtered,
            "count": len(filtered),
            "weighted_pipeline_value": pipeline_value
        }
    }


@tool
def send_customer_email(
    customer_id: str,
    subject: str,
    body: str,
    template: Optional[str] = None
) -> Dict[str, Any]:
    """
    Send email to customer.
    
    Args:
        customer_id: Customer ID
        subject: Email subject
        body: Email body content
        template: Optional template name
        
    Returns:
        Email send status
    """
    return {
        "success": True,
        "data": {
            "email_id": f"EMAIL-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "customer_id": customer_id,
            "subject": subject,
            "status": "sent",
            "sent_at": datetime.now().isoformat()
        }
    }


@tool
def get_customer_sentiment(
    customer_id: str
) -> Dict[str, Any]:
    """
    Get customer sentiment analysis.
    
    Args:
        customer_id: Customer ID to analyze
        
    Returns:
        Sentiment analysis results
    """
    return {
        "success": True,
        "data": {
            "customer_id": customer_id,
            "overall_sentiment": "positive",
            "sentiment_score": 0.78,
            "recent_interactions": [
                {"date": "2024-12-17", "channel": "email", "sentiment": "positive"},
                {"date": "2024-12-15", "channel": "call", "sentiment": "neutral"},
                {"date": "2024-12-10", "channel": "ticket", "sentiment": "negative"},
            ],
            "trending": "improving",
            "risk_of_churn": "low"
        }
    }


def get_client_tools():
    """Return all client tools."""
    return [
        get_customer_info,
        get_support_tickets,
        create_support_ticket,
        get_sales_pipeline,
        send_customer_email,
        get_customer_sentiment,
    ]