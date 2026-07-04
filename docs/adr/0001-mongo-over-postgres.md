# ADR 0001: MongoDB over PostgreSQL for the data layer

- **Status:** Accepted
- **Date:** 2026-07-01
- **Deciders:** Engineering team

## Context

The platform persists: workflows (graphs of agent nodes and edges),
tools (per-node HTTP tool configs with optional headers and secret
references), conflicts (human-in-the-loop pauses), users, conversations,
and messages. The shape of these documents is heterogeneous and
evolving — workflows in particular have a flexible `nodes` array where
each node carries its own `systemPrompt`, `goalsAndActions`, and
`capabilities` blob.

The two candidates were:

- **PostgreSQL** with a JSONB column for the workflow blob, separate
  tables for `tools`, `conflicts`, `users`, `conversations`, `messages`.
- **MongoDB** with one collection per resource type and a single
  Motor (async) client.

## Decision

Use **MongoDB** for all persistent state. One collection per resource
type; no JSONB escape hatch needed. Motor (async MongoDB driver) is
the only DB client.

## Consequences

**Easier:**

- One driver, one mental model. New resources are a new collection +
  new Pydantic schema, no migration files to coordinate.
- Schema flexibility: a workflow's `nodes` array can have arbitrary
  per-node fields without a migration. We rely on `extra="ignore"` in
  the Pydantic `ConfigDict` to keep the wire format forgiving.
- Native TTL indexes (for legacy Redis chat history we still keep).
- Easy to inspect during dev — `mongosh` is enough.

**Harder:**

- No transactions across collections. Multi-step operations
  (raise-conflict + publish to Redis + broadcast WS) need careful
  ordering. We treat Mongo as the source of truth, Redis as ephemeral.
- No relational integrity. We rely on application-level checks
  (`workflow_id` references, `userId` scoping on every query).
- Index management is manual. `ensure_indexes()` in
  `app/db/mongodb.py` is called from the FastAPI lifespan; new
  collections must add their indexes there.

**Migration path if we change later:** the service layer
(`app/services/`) is the only place that talks to Motor. A swap to
Postgres would touch the services, not the routes or agents.
