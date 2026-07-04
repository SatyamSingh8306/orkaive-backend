"""Dashboard WebSocket — forwards Redis pubsub events to clients."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.db.redis import get_async_redis_client

logger = logging.getLogger(__name__)
router = APIRouter()


class _Manager:
    def __init__(self) -> None:
        self.run_connections: dict[str, set[WebSocket]] = {}
        self.global_connections: set[WebSocket] = set()
        self.listener_task: Optional[asyncio.Task] = None
        self.redis = None

    async def _ensure_redis(self) -> None:
        if self.redis is None:
            self.redis = get_async_redis_client()

    async def connect(self, websocket: WebSocket, run_id: Optional[str] = None) -> None:
        await websocket.accept()
        if run_id:
            self.run_connections.setdefault(run_id, set()).add(websocket)
        else:
            self.global_connections.add(websocket)

    def disconnect(self, websocket: WebSocket, run_id: Optional[str] = None) -> None:
        if run_id and run_id in self.run_connections:
            self.run_connections[run_id].discard(websocket)
            if not self.run_connections[run_id]:
                self.run_connections.pop(run_id, None)
        else:
            self.global_connections.discard(websocket)

    async def _send(self, websocket: WebSocket, message: str) -> bool:
        try:
            await websocket.send_text(message)
            return True
        except Exception:
            return False

    async def broadcast(self, message: str, run_id: Optional[str] = None) -> None:
        targets: list[WebSocket] = []
        if run_id and run_id in self.run_connections:
            targets.extend(self.run_connections[run_id])
        targets.extend(self.global_connections)
        dead: list[WebSocket] = []
        for ws in targets:
            if not await self._send(ws, message):
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, run_id)

    async def listen(self) -> None:
        await self._ensure_redis()
        if not self.redis:
            return
        pubsub = self.redis.pubsub()
        await pubsub.subscribe("trace_events")
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                # Try to extract run_id from the payload
                try:
                    parsed = json.loads(data)
                    run_id = parsed.get("data", {}).get("run_id") or parsed.get("run_id")
                except Exception:
                    run_id = None
                await self.broadcast(data, run_id=run_id)
        except Exception as e:
            logger.warning("redis listener error: %s", e)
            await asyncio.sleep(2)
            await self.listen()


manager = _Manager()


async def start_listener() -> None:
    if manager.listener_task is None or manager.listener_task.done():
        manager.listener_task = asyncio.create_task(manager.listen())


@router.websocket("/ws/dashboard")
async def dashboard_socket(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    await start_listener()
    try:
        while True:
            text = await websocket.receive_text()
            try:
                msg = json.loads(text)
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)


@router.websocket("/ws/run/{run_id}")
async def run_socket(websocket: WebSocket, run_id: str) -> None:
    await manager.connect(websocket, run_id=run_id)
    await start_listener()
    try:
        # Send initial run details
        try:
            from app.services.trace_service import get_trace_service
            details = await get_trace_service().get_run_details(run_id)
            if details:
                await websocket.send_text(json.dumps({"type": "run_data", "data": details}))
        except Exception:
            pass

        while True:
            text = await websocket.receive_text()
            try:
                msg = json.loads(text)
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket, run_id=run_id)
