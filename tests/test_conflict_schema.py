"""Unit tests for `app.schemas.conflict` (Pydantic v2).

Locks down validation of conflict docs + raise/respond request bodies.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.schemas.conflict import (
    ConflictContext,
    ConflictDoc,
    ConflictStatus,
    RaiseConflictRequest,
    RespondConflictRequest,
)


def _doc(**overrides) -> dict:
    base = dict(
        queryId="q-1",
        workflowId="wf-1",
        runId="r-1",
        nodeId="n-1",
        nodeLabel="Compliance",
        ownerEmail="admin@example.com",
        query="Should I do X?",
        timeoutAt=(datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
        timeoutSeconds=300,
    )
    base.update(overrides)
    return base


class TestConflictDoc:
    def test_round_trip(self):
        d = ConflictDoc.model_validate(_doc())
        assert d.query_id == "q-1"
        assert d.status == ConflictStatus.PENDING
        assert d.node_label == "Compliance"

    def test_invalid_email_rejected(self):
        with pytest.raises(ValidationError):
            ConflictDoc.model_validate(_doc(ownerEmail="not-an-email"))

    def test_status_answered(self):
        d = ConflictDoc.model_validate(_doc(status="answered", response="yes"))
        assert d.status == ConflictStatus.ANSWERED
        assert d.response == "yes"


class TestRaiseConflictRequest:
    def test_timeout_bounds(self):
        # below 5
        with pytest.raises(ValidationError):
            RaiseConflictRequest.model_validate({
                "workflowId": "wf", "runId": "r", "nodeId": "n",
                "nodeLabel": "lbl", "ownerEmail": "a@b.com",
                "query": "q", "timeoutSeconds": 1,
            })
        # above 3600
        with pytest.raises(ValidationError):
            RaiseConflictRequest.model_validate({
                "workflowId": "wf", "runId": "r", "nodeId": "n",
                "nodeLabel": "lbl", "ownerEmail": "a@b.com",
                "query": "q", "timeoutSeconds": 9999,
            })

    def test_minimum_valid(self):
        r = RaiseConflictRequest.model_validate({
            "workflowId": "wf", "runId": "r", "nodeId": "n",
            "nodeLabel": "lbl", "ownerEmail": "a@b.com",
            "query": "q",
        })
        assert r.timeout_seconds == 300
        assert r.context == {}


class TestRespondConflictRequest:
    def test_minimum(self):
        r = RespondConflictRequest.model_validate({"queryId": "q-1", "response": "yes"})
        assert r.query_id == "q-1"
        assert r.response == "yes"


class TestConflictContext:
    def test_defaults(self):
        c = ConflictContext.model_validate({})
        assert c.input == ""
        assert c.agent_output == ""
        assert c.conflict_reason == ""
