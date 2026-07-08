"""Production Observability Tracing Service — telemetry exporter for Langfuse/Arize."""

from __future__ import annotations

import logging
import time
from uuid import UUID

logger = logging.getLogger("operdai.observability")


class ObservabilityTracer:
    def __init__(self, run_id: UUID, trace_name: str = "supervisor_pipeline"):
        self.run_id = run_id
        self.trace_name = trace_name
        self.spans: list[dict] = []
        self.start_time = time.monotonic()

    def log_span(
        self,
        span_name: str,
        input_data: dict | str,
        output_data: dict | str,
        latency_ms: float,
        tokens_in: int = 0,
        tokens_out: int = 0,
        cost_cents: float = 0.0,
    ):
        """Record a single step execution span inside the trace graph."""
        span = {
            "span_name": span_name,
            "input": input_data,
            "output": output_data,
            "latency_ms": round(latency_ms, 2),
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
            "cost_cents": round(cost_cents, 4),
        }
        self.spans.append(span)
        logger.info(
            f"[Observability Trace {self.run_id}] Step '{span_name}' completed. "
            f"Latency: {latency_ms:.2f}ms, Cost: {cost_cents:.4f} cents."
        )

    def export(self) -> dict:
        """Export accumulated spans payload in a format ready for Langfuse ingestion."""
        total_duration_ms = (time.monotonic() - self.start_time) * 1000
        payload = {
            "trace_id": str(self.run_id),
            "name": self.trace_name,
            "total_duration_ms": round(total_duration_ms, 2),
            "spans_count": len(self.spans),
            "spans": self.spans,
        }
        logger.info(f"Telemetries exported successfully for trace ID {self.run_id}.")
        return payload
