"""Supply Chain Agent Tools."""

from typing import Dict, List, Optional, Any
from langchain_core.tools import tool
from pydantic import BaseModel, Field


class InventoryQuery(BaseModel):
    """Schema for inventory queries."""
    product_id: Optional[str] = Field(None, description="Product ID to check")
    warehouse_id: Optional[str] = Field(None, description="Warehouse ID")
    category: Optional[str] = Field(None, description="Product category")


class ShipmentQuery(BaseModel):
    """Schema for shipment queries."""
    shipment_id: Optional[str] = Field(None, description="Shipment ID to track")
    order_id: Optional[str] = Field(None, description="Order ID")
    status: Optional[str] = Field(None, description="Filter by status")


class VendorQuery(BaseModel):
    """Schema for vendor queries."""
    vendor_id: Optional[str] = Field(None, description="Vendor ID")
    product_category: Optional[str] = Field(None, description="Product category")


# --- Tool Implementations ---

@tool
def check_inventory(
    product_id: Optional[str] = None,
    warehouse_id: Optional[str] = None,
    category: Optional[str] = None
) -> Dict[str, Any]:
    """
    Check inventory levels for products across warehouses.
    
    Args:
        product_id: Specific product ID to check
        warehouse_id: Specific warehouse to check
        category: Product category to filter
        
    Returns:
        Inventory data including quantities, locations, and status
    """
    # Simulated inventory data
    inventory_data = {
        "PROD-001": {
            "name": "Widget A",
            "warehouses": {
                "WH-EAST": {"quantity": 500, "reserved": 50},
                "WH-WEST": {"quantity": 300, "reserved": 25},
            },
            "reorder_point": 200,
            "status": "adequate"
        },
        "PROD-002": {
            "name": "Widget B", 
            "warehouses": {
                "WH-EAST": {"quantity": 50, "reserved": 30},
                "WH-WEST": {"quantity": 75, "reserved": 10},
            },
            "reorder_point": 100,
            "status": "low_stock"
        },
        "PROD-003": {
            "name": "Widget C",
            "warehouses": {
                "WH-CENTRAL": {"quantity": 1000, "reserved": 100},
            },
            "reorder_point": 300,
            "status": "adequate"
        }
    }
    
    if product_id and product_id in inventory_data:
        return {"success": True, "data": {product_id: inventory_data[product_id]}}
    elif product_id:
        return {"success": False, "error": f"Product {product_id} not found"}
    
    # Filter by warehouse if specified
    if warehouse_id:
        filtered = {}
        for pid, pdata in inventory_data.items():
            if warehouse_id in pdata["warehouses"]:
                filtered[pid] = {
                    **pdata,
                    "warehouses": {warehouse_id: pdata["warehouses"][warehouse_id]}
                }
        return {"success": True, "data": filtered}
    
    return {"success": True, "data": inventory_data}


@tool
def track_shipment(
    shipment_id: Optional[str] = None,
    order_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Track shipment status and location.
    
    Args:
        shipment_id: Shipment ID to track
        order_id: Order ID associated with shipment
        
    Returns:
        Shipment tracking information
    """
    # Simulated shipment data
    shipments = {
        "SHIP-001": {
            "order_id": "ORD-1001",
            "status": "in_transit",
            "carrier": "FedEx",
            "origin": "WH-EAST",
            "destination": "Customer Location, NY",
            "estimated_delivery": "2024-12-20",
            "current_location": "Memphis, TN",
            "tracking_events": [
                {"time": "2024-12-17 08:00", "event": "Picked up"},
                {"time": "2024-12-17 14:00", "event": "In transit"},
                {"time": "2024-12-18 06:00", "event": "Arrived at Memphis hub"},
            ]
        },
        "SHIP-002": {
            "order_id": "ORD-1002",
            "status": "delivered",
            "carrier": "UPS",
            "origin": "WH-WEST",
            "destination": "Customer Location, CA",
            "delivered_at": "2024-12-16 14:30",
        }
    }
    
    if shipment_id and shipment_id in shipments:
        return {"success": True, "data": shipments[shipment_id]}
    
    if order_id:
        for sid, sdata in shipments.items():
            if sdata.get("order_id") == order_id:
                return {"success": True, "data": {sid: sdata}}
        return {"success": False, "error": f"No shipment found for order {order_id}"}
    
    return {"success": True, "data": shipments}


@tool  
def get_vendor_info(
    vendor_id: Optional[str] = None,
    product_category: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get vendor information and performance metrics.
    
    Args:
        vendor_id: Specific vendor ID
        product_category: Filter vendors by product category
        
    Returns:
        Vendor details including performance metrics
    """
    vendors = {
        "VND-001": {
            "name": "Acme Supplies",
            "categories": ["electronics", "components"],
            "rating": 4.5,
            "on_time_delivery": 0.95,
            "quality_score": 0.92,
            "lead_time_days": 7,
            "contact": "supplier@acme.com",
            "status": "active"
        },
        "VND-002": {
            "name": "Global Parts Co",
            "categories": ["raw_materials", "components"],
            "rating": 4.2,
            "on_time_delivery": 0.88,
            "quality_score": 0.90,
            "lead_time_days": 14,
            "contact": "orders@globalparts.com",
            "status": "active"
        }
    }
    
    if vendor_id and vendor_id in vendors:
        return {"success": True, "data": vendors[vendor_id]}
    
    if product_category:
        filtered = {
            vid: vdata for vid, vdata in vendors.items()
            if product_category in vdata["categories"]
        }
        return {"success": True, "data": filtered}
    
    return {"success": True, "data": vendors}


@tool
def create_purchase_order(
    vendor_id: str,
    items: List[Dict[str, Any]],
    priority: str = "normal"
) -> Dict[str, Any]:
    """
    Create a purchase order for a vendor.
    
    Args:
        vendor_id: Vendor ID to order from
        items: List of items with product_id and quantity
        priority: Order priority (low, normal, high, urgent)
        
    Returns:
        Created purchase order details
    """
    # Simulated PO creation
    po_id = f"PO-{hash(vendor_id + str(items)) % 10000:04d}"
    
    return {
        "success": True,
        "data": {
            "po_id": po_id,
            "vendor_id": vendor_id,
            "items": items,
            "priority": priority,
            "status": "created",
            "created_at": "2024-12-18T10:00:00Z",
            "estimated_delivery": "2024-12-25"
        }
    }


@tool
def get_demand_forecast(
    product_id: Optional[str] = None,
    period_days: int = 30
) -> Dict[str, Any]:
    """
    Get demand forecast for products.
    
    Args:
        product_id: Specific product to forecast
        period_days: Forecast period in days
        
    Returns:
        Demand forecast data
    """
    forecasts = {
        "PROD-001": {
            "current_demand": 100,
            "forecasted_demand": 120,
            "trend": "increasing",
            "confidence": 0.85,
            "seasonality": "high_q4"
        },
        "PROD-002": {
            "current_demand": 50,
            "forecasted_demand": 45,
            "trend": "stable",
            "confidence": 0.90,
            "seasonality": "none"
        }
    }
    
    if product_id:
        if product_id in forecasts:
            return {
                "success": True,
                "data": forecasts[product_id],
                "period_days": period_days
            }
        return {"success": False, "error": f"No forecast for {product_id}"}
    
    return {"success": True, "data": forecasts, "period_days": period_days}


def get_supply_chain_tools():
    """Return all supply chain tools."""
    return [
        check_inventory,
        track_shipment,
        get_vendor_info,
        create_purchase_order,
        get_demand_forecast,
    ]