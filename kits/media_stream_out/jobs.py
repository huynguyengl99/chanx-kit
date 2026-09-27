"""Server-side producers, one at a time per key, cancellable as a whole."""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

Job = Callable[[], Awaitable[None]]


class SerialJobs:
    """Run jobs one at a time per key, in order; ``cancel`` drops the key's current and queued jobs."""

    def __init__(self) -> None:
        self._queues: dict[str, asyncio.Queue[Job]] = {}
        self._workers: dict[str, asyncio.Task[None]] = {}
        self._current: dict[str, asyncio.Task[None]] = {}

    def submit(self, key: str, job: Job) -> None:
        queue = self._queues.setdefault(key, asyncio.Queue())
        queue.put_nowait(job)
        worker = self._workers.get(key)
        if worker is None or worker.done():
            self._workers[key] = asyncio.ensure_future(self._work(key, queue))

    def busy(self, key: str) -> bool:
        worker = self._workers.get(key)
        return worker is not None and not worker.done()

    async def cancel(self, key: str) -> bool:
        """Stop the running job and drop the queued ones. True if anything stopped."""
        queue = self._queues.pop(key, None)
        dropped = 0
        while queue is not None and not queue.empty():
            queue.get_nowait()
            dropped += 1
        worker = self._workers.pop(key, None)
        current = self._current.pop(key, None)
        stopped = False
        for task in (current, worker):
            if (
                task is not None
                and not task.done()
                and task is not asyncio.current_task()
            ):
                task.cancel()
                stopped = True
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await task
        return stopped or dropped > 0

    async def wait(self, key: str) -> None:
        """Until every job for ``key`` has run. Mostly for tests."""
        worker = self._workers.get(key)
        if worker is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(worker)

    async def _work(self, key: str, queue: asyncio.Queue[Job]) -> None:
        while not queue.empty():
            job = queue.get_nowait()
            task = asyncio.ensure_future(job())
            self._current[key] = task
            try:
                await task
            except asyncio.CancelledError:
                if not task.cancelled():
                    raise
                return
            except Exception:
                logger.exception("media job for %s failed", key)
            finally:
                if self._current.get(key) is task:
                    del self._current[key]
        if self._workers.get(key) is asyncio.current_task():
            del self._workers[key]
            self._queues.pop(key, None)
