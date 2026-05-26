"""Process-wide async event bus shared by SSE endpoint, schedulers, and runners.

Lightweight pub-sub: subscribers get an asyncio.Queue and read events as they arrive.
Publish is best-effort — slow/disconnected subscribers are dropped silently rather than
back-pressuring the publisher.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


class EventHub:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        async with self._lock:
            self._subscribers.add(queue)
        return queue

    async def unsubscribe(self, queue: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers.discard(queue)

    async def publish(self, event_type: str, payload: Any) -> None:
        message = {"type": event_type, "payload": payload, "ts": datetime.now().isoformat(timespec="seconds")}
        async with self._lock:
            queues = list(self._subscribers)
        for queue in queues:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                logger.debug("SSE queue full; dropping for slow subscriber")


hub = EventHub()
