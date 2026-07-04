"""User-scoped WebSocket bridge for chat live updates.

One WS connection per logged-in user. Subscribes to
`chat:user:{userId}:events` on Redis and forwards each event to the
client. Also accepts client→server ping/pong for keepalive.

Auth: the client passes the JWT in `Sec-WebSocket-Protocol` as
`bearer.<token>`; we echo the same subprotocol back so the upgrade
succeeds. This is the standard pattern (RFC 6455 subprotocols are
echoed by the server) and avoids putting the token in a query string.
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status
from jose import JWTError

from app.config.settings import get_settings
from app.core.logging import get_logger
from app.db.redis import get_async_redis_client

logger = get_logger(__name__)
router = APIRouter()


def _user_channel(user_id: str) -> str:
    return f"chat:user:{user_id}:events"


def _decode_jwt(token: str) -> Optional[str]:
    """Return the userId (email) from a JWT, or None if invalid."""
    settings = get_settings()
    try:
        from jose import jwt as _jwt

        payload = _jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        return payload.get("sub")
    except (JWTError, Exception) as e:
        logger.debug("ws auth failed: %s", e)
        return None


async def publish_to_user(user_id: str, payload: dict) -> None:
    """Publish a JSON event to a single user's WS channel.

    Called from anywhere in the backend (e.g. the chat routes) to notify
    that user's connected clients about a change. Silently swallows
    Redis errors so the HTTP request never fails because WS is down.
    """
    try:
        redis = get_async_redis_client()
        await redis.publish(_user_channel(user_id), json.dumps(payload))
    except Exception as e:
        logger.debug("ws publish failed (user=%s): %s", user_id, e)


@router.websocket("/ws/chats")
async def chat_socket(websocket: WebSocket) -> None:
    # Extract the bearer token from the subprotocol header. Browsers
    # set this via `new WebSocket(url, ["bearer." + token])`.
    subprotocols: list[str] = list(websocket.headers.get("sec-websocket-protocol", "").split(","))
    subprotocols = [s.strip() for s in subprotocols if s.strip()]
    bearer = next(
        (s.split(".", 1)[1] for s in subprotocols if s.startswith("bearer.")),
        None,
    )
    if not bearer:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="missing bearer token")
        return

    user_id = _decode_jwt(bearer)
    if not user_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="invalid token")
        return

    # Accept with the subprotocol echoed back (required by the client).
    await websocket.accept(subprotocol="bearer." + bearer)

    redis = get_async_redis_client()
    try:
        pubsub = redis.pubsub()
        channel = _user_channel(user_id)
        await pubsub.subscribe(channel)
    except Exception as e:
        # Redis is down (or briefly unreachable). Don't let this
        # kill the ASGI task — close the socket gracefully with a
        # retry code and let the client reconnect. Without this
        # guard an outage surfaces as a stack trace on every WS
        # connect attempt and (worse) on Windows the underlying
        # `ConnectionResetError` from a half-open connection tears
        # down the surrounding coroutine.
        logger.debug("ws subscribe failed (user=%s): %s", user_id, e)
        try:
            await websocket.close(
                code=status.WS_1011_SERVER_ERROR,
                reason="subscription failed",
            )
        except Exception:
            pass
        return

    # Send a hello frame so the client knows the link is up.
    try:
        await websocket.send_text(json.dumps({
            "type": "connected",
            "channel": channel,
        }))
    except Exception:
        try:
            await pubsub.aclose()
        except Exception:
            pass
        return

    async def pump_redis() -> None:
        """Forward Redis messages to the client until cancelled."""
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode("utf-8", errors="replace")
                if data is None:
                    continue
                try:
                    await websocket.send_text(data)
                except Exception:
                    return
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug("ws redis pump error: %s", e)
            return

    async def pump_client() -> None:
        """Read client messages (ping/pong) until the socket closes."""
        try:
            while True:
                raw = await websocket.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
        except WebSocketDisconnect:
            return
        except Exception as e:
            logger.debug("ws client pump error: %s", e)
            return

    redis_task = asyncio.create_task(pump_redis())
    client_task = asyncio.create_task(pump_client())
    try:
        done, pending = await asyncio.wait(
            {redis_task, client_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        # Drain the cancelled tasks so their exceptions (if any) are
        # observed here rather than surfaced as "Task was destroyed
        # but it is pending!" warnings. Each pump has its own internal
        # try/except so this is just a polite join.
        for t in pending:
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
    except Exception as e:
        logger.debug("ws pump coordinator error: %s", e)
    finally:
        try:
            await pubsub.unsubscribe(channel)
        except Exception:
            pass
        try:
            await pubsub.aclose()
        except Exception:
            pass


__all__ = ["router", "publish_to_user"]
