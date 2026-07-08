"""Tests for Milestone 11 — Enterprise Resilience (Observability & Distributed Locking)."""

import pytest
from unittest.mock import AsyncMock, MagicMock
import uuid

from app.services.observability import ObservabilityTracer
from app.services.locking import DistributedLock


class TestTelemetryObservability:
    """Test telemetry tracing data exports."""

    def test_observability_tracer_flow(self):
        run_id = uuid.uuid4()
        tracer = ObservabilityTracer(run_id=run_id, trace_name="test_pipeline")

        tracer.log_span(
            span_name="Classifier",
            input_data={"text": "hello"},
            output_data={"intent": "greeting"},
            latency_ms=120.5,
            tokens_in=10,
            tokens_out=15,
            cost_cents=0.005,
        )

        res = tracer.export()
        assert res["trace_id"] == str(run_id)
        assert res["name"] == "test_pipeline"
        assert res["spans_count"] == 1
        assert res["spans"][0]["span_name"] == "Classifier"
        assert res["spans"][0]["latency_ms"] == 120.5


class TestDistributedLocking:
    """Test distributed locks using mock Redis client."""

    @pytest.mark.asyncio
    async def test_distributed_lock_acquire_release(self):
        redis_mock = AsyncMock()
        redis_mock.set.return_value = True  # Lock successfully acquired

        lock_name = "test_resource"
        async with DistributedLock(lock_name, lease_seconds=10, redis_client=redis_mock) as acquired:
            assert acquired is True
            redis_mock.set.assert_called_once_with(
                f"lock:{lock_name}",
                "locked",
                ex=10,
                nx=True
            )

        # Releases on exit
        redis_mock.delete.assert_called_once_with(f"lock:{lock_name}")

    @pytest.mark.asyncio
    async def test_distributed_lock_failure(self):
        redis_mock = AsyncMock()
        redis_mock.set.return_value = False  # Lock already busy

        lock_name = "busy_resource"
        async with DistributedLock(lock_name, lease_seconds=5, redis_client=redis_mock) as acquired:
            assert acquired is False

        # Should NOT release since it was never acquired
        redis_mock.delete.assert_not_called()
