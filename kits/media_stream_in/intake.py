"""A bounded, real-time intake between a socket and whatever consumes the media."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Literal

logger = logging.getLogger(__name__)

Idle = Literal["keepalive", "idle"]


class MediaIntake:
    """Feed chunks to ``sink`` in order from one task; drop the oldest when full."""

    def __init__(
        self,
        sink: Callable[[bytes], Awaitable[None]],
        *,
        on_end: Callable[[], Awaitable[None]],
        on_quiet: Callable[[Idle], Awaitable[None]] | None = None,
        max_chunks: int = 50,
        keepalive_seconds: float | None = None,
        idle_seconds: float | None = None,
    ) -> None:
        self._sink = sink
        self._on_end = on_end
        self._on_quiet = on_quiet
        self._queue: asyncio.Queue[bytes | None] = asyncio.Queue(max_chunks)
        self._keepalive = keepalive_seconds
        self._idle = idle_seconds
        self.dropped = 0
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        self._task = asyncio.ensure_future(self._run())

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def feed(self, chunk: bytes) -> None:
        if self._queue.full():
            self._queue.get_nowait()
            self.dropped += 1
            logger.warning(
                "media intake full; dropped the oldest chunk (%d so far)", self.dropped
            )
        self._queue.put_nowait(chunk)

    def end(self) -> None:
        """Finish after the chunks already queued."""
        if self._queue.full():
            self._queue.get_nowait()
            self.dropped += 1
        self._queue.put_nowait(None)

    async def stop(self) -> None:
        """Stop now, dropping whatever is queued. Safe from inside ``on_quiet``."""
        if self._task is asyncio.current_task():
            return
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def wait(self) -> None:
        if self._task is not None:
            await asyncio.shield(self._task)

    async def _run(self) -> None:
        loop = asyncio.get_running_loop()
        last_chunk = loop.time()
        while True:
            timeout = self._keepalive
            if self._idle is not None:
                remaining = self._idle - (loop.time() - last_chunk)
                timeout = remaining if timeout is None else min(timeout, remaining)
            try:
                if timeout is None:
                    chunk = await self._queue.get()
                else:
                    chunk = await asyncio.wait_for(self._queue.get(), max(timeout, 0))
            except TimeoutError:
                if self._idle is not None and loop.time() - last_chunk >= self._idle:
                    if self._on_quiet is not None:
                        await self._on_quiet("idle")
                    return
                if self._on_quiet is not None:
                    await self._on_quiet("keepalive")
                continue

            if chunk is None:
                await self._on_end()
                return
            last_chunk = loop.time()
            await self._sink(chunk)
