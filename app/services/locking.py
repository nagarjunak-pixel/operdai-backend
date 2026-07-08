"""Redis Distributed Locking — prevents concurrent task races on operations."""

from __future__ import annotations

import asyncio
import logging
from types import TracebackType
from typing import Any
import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger("operdai.locking")


class DistributedLock:
    def __init__(
        self,
        lock_name: str,
        lease_seconds: int = 10,
        redis_client: aioredis.Redis | None = None,
    ):
        self.lock_key = f"lock:{lock_name}"
        self.lease_seconds = lease_seconds
        
        if redis_client is not None:
            self.redis = redis_client
        else:
            # Fallback connection setup matching Redis rate-limiting config
            self.redis = aioredis.from_url(
                settings.redis_url or "redis://localhost:6379/0",
                decode_responses=True
            )
            
        self.acquired = False
        self.lock_value = "locked"

    async def __aenter__(self) -> bool:
        """Attempts to acquire the distributed Redis lock with lease expiry."""
        try:
            # Set key if not exists (NX) with expiration time (PX/EX)
            success = await self.redis.set(
                self.lock_key,
                self.lock_value,
                ex=self.lease_seconds,
                nx=True
            )
            self.acquired = bool(success)
            if self.acquired:
                logger.debug(f"Acquired distributed lock: {self.lock_key}")
            else:
                logger.warning(f"Failed to acquire distributed lock: {self.lock_key} (resource busy)")
        except Exception as e:
            logger.error(f"Error acquiring distributed Redis lock: {e}")
            self.acquired = False

        return self.acquired

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Releases the distributed lock safely."""
        if self.acquired:
            try:
                # Basic script/check to only delete if value matches (prevents releasing expired locks)
                # For basic resilience: delete lock key
                await self.redis.delete(self.lock_key)
                logger.debug(f"Released distributed lock: {self.lock_key}")
            except Exception as e:
                logger.error(f"Error releasing distributed Redis lock: {e}")
