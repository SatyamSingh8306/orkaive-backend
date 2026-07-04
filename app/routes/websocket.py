"""WebSocket routes — kept largely as-is. Conflict broadcast uses the
new conflict service via the same broadcast channel.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/ws", tags=["websocket"])


class ConnectionManager:
    def __init__(self) -> None:
        self.workflow_connections: dict[str, set[WebSocket]] = {}
        self.workflow_admins: dict[str, set[str]] = {}

    async def connect(self, websocket: WebSocket, workflow_id: str, admin_email: str) -> None:
        if workflow_id not in self.workflow_connections:
            self.workflow_connections[workflow_id] = set()
            self.workflow_admins[workflow_id] = set()
        self.workflow_connections[workflow_id].add(websocket)
        self.workflow_admins[workflow_id].add(admin_email)
        await self.broadcast_to_workflow(workflow_id, {
            "type": "admin:joined",
            "adminEmail": admin_email,
            "workflowId": workflow_id,
            "onlineCount": len(self.workflow_admins[workflow_id]),
        }, exclude=websocket)

    def disconnect(self, websocket: WebSocket, workflow_id: str, admin_email: str) -> None:
        conns = self.workflow_connections.get(workflow_id)
        if conns is not None:
            conns.discard(websocket)
            if not conns:
                self.workflow_connections.pop(workflow_id, None)
                self.workflow_admins.pop(workflow_id, None)

    async def broadcast_to_workflow(
        self, workflow_id: str, message: dict, exclude: Optional[WebSocket] = None
    ) -> None:
        conns = self.workflow_connections.get(workflow_id)
        if not conns:
            return
        disconnected: set[WebSocket] = set()
        for conn in conns:
            if conn is exclude:
                continue
            try:
                await conn.send_json(message)
            except Exception as e:
                logger.debug("ws send failed, marking disconnected: %s", e)
                disconnected.add(conn)
        for conn in disconnected:
            conns.discard(conn)


manager = ConnectionManager()


async def broadcast_conflict(workflow_id: str, conflict_data: dict) -> None:
    """Module-level helper used by the conflict service."""
    await manager.broadcast_to_workflow(workflow_id, {
        "type": "conflict:raised",
        **conflict_data,
    })


@router.websocket("/{workflow_id}")
async def workflow_socket(websocket: WebSocket, workflow_id: str) -> None:
    admin_email: Optional[str] = None
    try:
        await websocket.accept()
        data = await websocket.receive_json()
        if data.get("type") != "join:workflow":
            await websocket.close(code=1008, reason="Expected join:workflow")
            return
        admin_email = data.get("adminEmail", "unknown")
        await manager.connect(websocket, workflow_id, admin_email)
        await websocket.send_json({
            "type": "connected",
            "workflowId": workflow_id,
            "adminEmail": admin_email,
        })

        while True:
            try:
                msg = await websocket.receive_json()
                kind = msg.get("type")
                if kind == "conflict:response":
                    await manager.broadcast_to_workflow(workflow_id, {
                        "type": "conflict:resolved",
                        "queryId": msg.get("queryId"),
                        "workflowId": workflow_id,
                        "response": msg.get("response"),
                        "adminEmail": admin_email,
                        "respondedAt": datetime.now(timezone.utc).isoformat(),
                    })
                elif kind == "chat:send":
                    await manager.broadcast_to_workflow(workflow_id, {
                        "type": "chat:message",
                        "id": msg.get("id"),
                        "workflowId": workflow_id,
                        "senderEmail": admin_email,
                        "senderName": msg.get("senderName"),
                        "message": msg.get("message"),
                        "messageType": "text",
                        "createdAt": datetime.now(timezone.utc).isoformat(),
                    })
                elif kind == "typing":
                    await manager.broadcast_to_workflow(workflow_id, {
                        "type": "admin:typing",
                        "adminEmail": admin_email,
                        "isTyping": bool(msg.get("isTyping", False)),
                    }, exclude=websocket)
                elif kind == "leave:workflow":
                    break
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.debug("ws message handling error: %s", e)
                try:
                    await websocket.send_json({"type": "error", "message": str(e)})
                except Exception:
                    break
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.debug("ws error: %s", e)
    finally:
        if admin_email:
            manager.disconnect(websocket, workflow_id, admin_email)
            try:
                await manager.broadcast_to_workflow(workflow_id, {
                    "type": "admin:left",
                    "adminEmail": admin_email,
                    "workflowId": workflow_id,
                    "onlineCount": len(manager.workflow_admins.get(workflow_id, set())),
                })
            except Exception:
                pass
