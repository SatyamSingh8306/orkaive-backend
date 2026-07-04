"""Compliance Agent Tools - Audit, Regulatory, Policy."""

from typing import Dict, List, Optional, Any
from langchain_core.tools import tool
from datetime import datetime


@tool
def check_compliance_status(
    regulation: Optional[str] = None,
    department: Optional[str] = None
) -> Dict[str, Any]:
    """
    Check compliance status for regulations.
    
    Args:
        regulation: Specific regulation (GDPR, SOX, HIPAA, PCI-DSS, etc.)
        department: Department to check
        
    Returns:
        Compliance status and gaps
    """
    compliance_data = {
        "GDPR": {
            "status": "compliant",
            "score": 0.94,
            "last_audit": "2024-11-15",
            "next_audit": "2025-05-15",
            "gaps": ["data_retention_policy_update_needed"],
            "controls": 45,
            "controls_passing": 43
        },
        "SOX": {
            "status": "compliant",
            "score": 0.98,
            "last_audit": "2024-10-01",
            "next_audit": "2025-04-01",
            "gaps": [],
            "controls": 120,
            "controls_passing": 118
        },
        "PCI-DSS": {
            "status": "needs_attention",
            "score": 0.87,
            "last_audit": "2024-09-01",
            "next_audit": "2025-03-01",
            "gaps": ["encryption_update", "access_logging_enhancement"],
            "controls": 85,
            "controls_passing": 74
        }
    }
    
    if regulation and regulation in compliance_data:
        return {"success": True, "data": {regulation: compliance_data[regulation]}}
    
    return {"success": True, "data": compliance_data}


@tool
def get_audit_logs(
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    action_type: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Retrieve audit logs for compliance tracking.
    
    Args:
        entity_type: Type of entity (user, document, transaction, system)
        entity_id: Specific entity ID
        action_type: Type of action (create, read, update, delete, access)
        start_date: Start date for log retrieval
        end_date: End date for log retrieval
        
    Returns:
        Audit log entries
    """
    logs = [
        {
            "log_id": "LOG-001",
            "timestamp": "2024-12-18T09:15:00Z",
            "entity_type": "user",
            "entity_id": "USER-001",
            "action": "login",
            "actor": "john.doe@company.com",
            "ip_address": "192.168.1.100",
            "status": "success"
        },
        {
            "log_id": "LOG-002",
            "timestamp": "2024-12-18T09:20:00Z",
            "entity_type": "document",
            "entity_id": "DOC-500",
            "action": "access",
            "actor": "john.doe@company.com",
            "details": "Accessed financial report Q4",
            "status": "success"
        },
        {
            "log_id": "LOG-003",
            "timestamp": "2024-12-18T09:25:00Z",
            "entity_type": "transaction",
            "entity_id": "TXN-1234",
            "action": "create",
            "actor": "jane.smith@company.com",
            "amount": 50000,
            "status": "success"
        }
    ]
    
    filtered = logs
    if entity_type:
        filtered = [l for l in filtered if l["entity_type"] == entity_type]
    if action_type:
        filtered = [l for l in filtered if l["action"] == action_type]
    
    return {"success": True, "data": filtered, "count": len(filtered)}


@tool
def run_compliance_check(
    check_type: str,
    target: str,
    scope: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Run a compliance check/scan.
    
    Args:
        check_type: Type of check (security, data_privacy, financial, access_control)
        target: Target system or process
        scope: Specific areas to check
        
    Returns:
        Compliance check results
    """
    return {
        "success": True,
        "data": {
            "check_id": f"CHK-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "check_type": check_type,
            "target": target,
            "status": "completed",
            "results": {
                "total_checks": 50,
                "passed": 47,
                "failed": 2,
                "warnings": 1,
                "score": 0.94
            },
            "findings": [
                {
                    "severity": "medium",
                    "finding": "Password policy not enforced for service accounts",
                    "recommendation": "Implement password rotation for service accounts",
                    "affected_systems": ["API Gateway", "ETL Service"]
                },
                {
                    "severity": "low",
                    "finding": "Audit log retention below recommended period",
                    "recommendation": "Extend log retention to 90 days",
                    "affected_systems": ["Logging Service"]
                }
            ],
            "completed_at": datetime.now().isoformat()
        }
    }


@tool
def get_policy_document(
    policy_id: Optional[str] = None,
    policy_type: Optional[str] = None,
    keyword: Optional[str] = None
) -> Dict[str, Any]:
    """
    Retrieve policy documents.
    
    Args:
        policy_id: Specific policy ID
        policy_type: Type of policy (security, hr, financial, data)
        keyword: Search keyword
        
    Returns:
        Policy document details
    """
    policies = {
        "POL-001": {
            "title": "Data Protection Policy",
            "type": "data",
            "version": "3.2",
            "effective_date": "2024-01-01",
            "review_date": "2024-12-31",
            "owner": "Data Protection Officer",
            "summary": "Guidelines for handling personal and sensitive data",
            "key_points": [
                "All PII must be encrypted at rest and in transit",
                "Data retention limited to business need",
                "Annual privacy training required"
            ]
        },
        "POL-002": {
            "title": "Access Control Policy",
            "type": "security",
            "version": "2.5",
            "effective_date": "2024-03-01",
            "review_date": "2025-02-28",
            "owner": "CISO",
            "summary": "Defines access control requirements and procedures",
            "key_points": [
                "Least privilege principle",
                "MFA required for all systems",
                "Quarterly access reviews"
            ]
        }
    }
    
    if policy_id and policy_id in policies:
        return {"success": True, "data": policies[policy_id]}
    
    if policy_type:
        filtered = {
            pid: pdata for pid, pdata in policies.items()
            if pdata["type"] == policy_type
        }
        return {"success": True, "data": filtered}
    
    return {"success": True, "data": policies}


@tool
def report_compliance_incident(
    incident_type: str,
    description: str,
    severity: str,
    affected_systems: List[str],
    reporter: str
) -> Dict[str, Any]:
    """
    Report a compliance incident.
    
    Args:
        incident_type: Type of incident (data_breach, policy_violation, access_violation)
        description: Detailed description
        severity: Severity level (low, medium, high, critical)
        affected_systems: List of affected systems
        reporter: Reporter email
        
    Returns:
        Created incident details
    """
    incident_id = f"INC-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    
    return {
        "success": True,
        "data": {
            "incident_id": incident_id,
            "type": incident_type,
            "description": description,
            "severity": severity,
            "affected_systems": affected_systems,
            "reporter": reporter,
            "status": "open",
            "created_at": datetime.now().isoformat(),
            "sla": {
                "response_time": "4 hours" if severity in ["high", "critical"] else "24 hours",
                "resolution_time": "24 hours" if severity == "critical" else "72 hours"
            },
            "assigned_to": "security.team@company.com"
        }
    }


@tool
def get_regulatory_requirements(
    regulation: str,
    requirement_category: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get regulatory requirements and mapping.
    
    Args:
        regulation: Regulation name (GDPR, SOX, HIPAA, PCI-DSS)
        requirement_category: Specific category of requirements
        
    Returns:
        Regulatory requirements with control mappings
    """
    requirements = {
        "GDPR": {
            "data_protection": [
                {"id": "GDPR-1", "requirement": "Lawful basis for processing", "controls": ["CTL-001", "CTL-002"]},
                {"id": "GDPR-2", "requirement": "Data minimization", "controls": ["CTL-003"]},
                {"id": "GDPR-3", "requirement": "Right to erasure", "controls": ["CTL-004", "CTL-005"]}
            ],
            "security": [
                {"id": "GDPR-32", "requirement": "Security of processing", "controls": ["CTL-010", "CTL-011"]}
            ],
            "governance": [
                {"id": "GDPR-24", "requirement": "Accountability", "controls": ["CTL-020"]}
            ]
        }
    }
    
    reg_data = requirements.get(regulation, {})
    
    if requirement_category and requirement_category in reg_data:
        return {"success": True, "data": {requirement_category: reg_data[requirement_category]}}
    
    return {"success": True, "data": reg_data}


def get_compliance_tools():
    """Return all compliance tools."""
    return [
        check_compliance_status,
        get_audit_logs,
        run_compliance_check,
        get_policy_document,
        report_compliance_incident,
        get_regulatory_requirements,
    ]