"""
test_cache.py — verify that the second identical tool call returns cache_hit=True
and is recorded as such in the tool_calls table.

Strategy: run the same tool twice with the same inputs.
  - Call 1: redis_get returns None → cache miss → execute() runs → redis_set called
  - Call 2: redis_get returns a serialized result → cache hit → execute() not called

The conftest autouse mock_redis fixture patches redis_get to return None (always miss).
For cache tests we override redis_get per-test to simulate a hit on the second call.
"""

import json
import uuid
from unittest.mock import patch

import pytest

from app.tools.get_recent_deploys import GetRecentDeploysTool
from app.tools.get_service_logs import GetServiceLogsTool


def test_second_get_recent_deploys_call_is_cache_hit(db):
    """
    Two identical get_recent_deploys calls with the same service_name should
    result in the second call being a cache hit with latency_ms=0.
    """
    run_id = uuid.uuid4()
    tool = GetRecentDeploysTool()
    raw_input = {"service_name": "lat-cron-job"}

    # First call — cache miss (autouse mock returns None), tool executes
    result1 = tool.run(raw_input=raw_input, db=db, run_id=run_id, sequence_num=1)

    # Second call — simulate cache hit by returning the serialized first result
    cached_bytes = json.dumps(result1, default=str)
    with patch("app.tools.base.redis_get", return_value=cached_bytes):
        result2 = tool.run(raw_input=raw_input, db=db, run_id=run_id, sequence_num=2)

    # Same data returned on both calls
    assert result1["service_name"] == result2["service_name"]
    assert result1["deploys"] == result2["deploys"]

    # Verify tool_call rows in DB
    from app.db import repositories as repo
    calls = repo.get_tool_calls_for_run(db, run_id)
    assert len(calls) == 2
    assert calls[0].cache_hit is False   # first call: miss
    assert calls[1].cache_hit is True    # second call: hit
    assert calls[1].latency_ms < 5      # cached result has near-zero latency


def test_second_get_service_logs_call_is_cache_hit(db):
    """
    Two identical get_service_logs calls (same service + time_window + severity)
    should result in a cache hit on the second call.
    """
    run_id = uuid.uuid4()
    tool = GetServiceLogsTool()
    raw_input = {"service_name": "lat-cron-job", "time_window": "2h", "severity": "ERROR"}

    result1 = tool.run(raw_input=raw_input, db=db, run_id=run_id, sequence_num=1)

    cached_bytes = json.dumps(result1, default=str)
    with patch("app.tools.base.redis_get", return_value=cached_bytes):
        result2 = tool.run(raw_input=raw_input, db=db, run_id=run_id, sequence_num=2)

    assert result1["logs"] == result2["logs"]

    from app.db import repositories as repo
    calls = repo.get_tool_calls_for_run(db, run_id)
    assert calls[1].cache_hit is True
