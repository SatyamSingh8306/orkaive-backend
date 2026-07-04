"""README for the eval/ directory.

These are *golden cases* — hermetic pytest tests that pin down the
orchestrator's structural behavior. They do NOT hit an LLM, do NOT
need Mongo or Redis, and run in <1s. They live outside `tests/` so
they're easy to find and easy to extend without disturbing the
unit-test contract under `tests/`.

When to add a case:
  * The user-facing behavior changes (routing, classification,
    multi-agent expansion, fallback, validation).
  * A new agent type is added — add a skip-path and a multi-agent
    case so future refactors can't silently break the contract.
  * A regression is reported — add a case that fails on the bug,
    then fix the bug.

How to run:
  cd orchive_agent_backend
  pytest eval/ -v

How to keep fast:
  * Use a stub LLM (`MagicMock`). Never call into a real provider.
  * Use the deterministic skip / fallback paths when possible.
  * For multi-agent cases, stub the structured-output chain and
    drive the router via `_validate` directly.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)
