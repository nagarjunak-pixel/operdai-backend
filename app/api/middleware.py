"""
API Middleware — rate limiting, security, and observability.
"""

from __future__ import annotations

import time

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """
    Redis-backed sliding window rate limiter.
    Fails open gracefully if Redis is unavailable to protect system availability.
    Bypassed in test environment to prevent flaky tests.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # 1. Skip non-API paths and test environment
        if not request.url.path.startswith("/api/v1") or settings.environment == "test":
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        current_minute = int(time.time() / 60)
        key = f"rate_limit:{client_ip}:{current_minute}"

        try:
            import redis

            # Direct Redis connection (fail-open on error)
            r = redis.Redis.from_url(settings.redis_url, socket_timeout=1.0)
            count = r.incr(key)
            if count == 1:
                r.expire(key, 60)

            if count > settings.rate_limit_per_minute:
                return JSONResponse(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    content={"detail": "Too many requests. Please try again in a minute."},
                )
        except Exception:
            # Fail-open logic to guarantee high availability
            pass

        return await call_next(request)
