from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator


@dataclass
class EventStream:
    """A producer-subscriber buffer for SSE events."""

    events: list[str] = field(default_factory=list)
    condition: asyncio.Condition = field(default_factory=asyncio.Condition)
    done: bool = False

    async def append(self, event: str) -> None:
        async with self.condition:
            self.events.append(event)
            self.condition.notify_all()

    async def close(self) -> None:
        async with self.condition:
            self.done = True
            self.condition.notify_all()

    async def subscribe(self) -> AsyncIterator[str]:
        event_index = 0
        while True:
            async with self.condition:
                while event_index >= len(self.events) and not self.done:
                    await self.condition.wait()
                events = self.events[event_index:]
                event_index += len(events)
                is_done = self.done

            for event in events:
                yield event
            if is_done and event_index >= len(self.events):
                return


def encode_sse(event: dict[str, Any]) -> str:
    """Encode a dictionary as a Server-Sent Event message."""
    event_type = str(event.get("type", "message"))
    payload = json.dumps(event, default=str, ensure_ascii=False)
    return f"event: {event_type}\n" f"data: {payload}\n\n"


SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}
