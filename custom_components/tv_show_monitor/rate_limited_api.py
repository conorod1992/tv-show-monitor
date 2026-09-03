"""Rate-limited TVmaze client for scheduled coordinator refreshes."""

from __future__ import annotations

import asyncio
import time

from aiohttp import ClientSession

from .api import TVMazeClient
from .const import ShowScheduleInfo

MIN_REQUEST_INTERVAL = 0.5


class RateLimitedTVMazeClient(TVMazeClient):
    """TVmaze client that spaces show refresh requests across concurrent workers."""

    def __init__(self, session: ClientSession) -> None:
        super().__init__(session)
        self._request_lock = asyncio.Lock()
        self._next_request_at = 0.0

    async def async_get_show_schedule(self, tvmaze_id: int) -> ShowScheduleInfo:
        """Wait for a request slot before fetching one show's schedule."""
        await self._async_wait_for_request_slot()
        return await super().async_get_show_schedule(tvmaze_id)

    async def _async_wait_for_request_slot(self) -> None:
        """Serialize request starts so TVmaze receives at most two per second."""
        async with self._request_lock:
            now = time.monotonic()
            delay = self._next_request_at - now
            if delay > 0:
                await asyncio.sleep(delay)
            self._next_request_at = time.monotonic() + MIN_REQUEST_INTERVAL
