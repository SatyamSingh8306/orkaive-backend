# ADR 0002: SSE over WebSocket for chat streaming

- **Status:** Accepted
- **Date:** 2026-07-01
- **Deciders:** Engineering team

## Context

The chat surface (`/chats`) needs to stream a generated response from
the LangGraph orchestrator to the browser, token by token, so the user
sees a streaming completion effect.

Two realistic options:

- **WebSocket** (already used for the conflict-resolution WS and the
  per-user chat sidebar WS).
- **Server-Sent Events** (SSE) over plain HTTP.

## Decision

Use **SSE** for the chat-token stream (`/api/chats/{id}/stream`,
`/api/chats/stream`). Continue using WebSocket for the per-user
**sidebar** WS and the per-workflow **conflict** WS.

The split is intentional:

| Surface | Direction | Protocol | Why |
|---|---|---|---|
| Chat tokens (per conversation) | server → client, one burst per turn | **SSE** | one-shot, request-scoped, can be cancelled by closing the response |
| Sidebar updates (per user, all tabs) | server → client, push | **WebSocket** | persistent, multiplexes many event types |
| Conflict events (per workflow) | server → client + client → server (admin response) | **WebSocket** | bidirectional, low-latency admin response |

## Consequences

**Easier:**

- SSE is plain HTTP. Works through every proxy, every CDN, every
  browser. No need for `Sec-WebSocket-Protocol` token exchange.
- Token cancellation is just "close the response". No bespoke
  disconnect / cleanup protocol.
- The browser's native `EventSource` re-connects automatically; we
  don't have to retry on the client.
- Easier to test: `curl -N` against the stream endpoint shows the
  same frames the browser sees.
- The auth story is one header (`Authorization: Bearer`), not a
  subprotocol.

**Harder:**

- SSE is unidirectional. Anything that needs to push from the
  client must go through a separate channel. That's why the sidebar
  and conflict flows stay on WebSocket.
- Per-connection overhead is heavier than WS for very long-lived
  streams, but a single chat turn is seconds, not hours.

**Why not WS for the chat stream?** The chat stream is request-scoped
(open at "Send", close at "Done" or on Cancel). WebSocket's strengths
(long-lived, bidirectional, multiplexed events) aren't being used.
Adding a second WS for chat would also force us to encode the auth
handshake in `Sec-WebSocket-Protocol: bearer.<token>` on every
reconnect — more surface area for a feature that needs nothing
beyond "open, push, close".
