"""What a thread knows about the run it is currently running: which run holds it, and
the run's events so far, kept so a connection joining mid-run can be replayed. The
in-memory defaults are process-local; implement these protocols against a shared
backend when a run and a connection can land on different processes."""

from typing import Protocol, runtime_checkable

from ag_ui.core import Event


@runtime_checkable
class RunEventStore(Protocol):
    """One buffered run per thread. Sequence numbers restart with each run."""

    async def append(self, thread_id: str, event: Event) -> int:
        """Buffer an event and return its sequence number, counting from 1."""
        ...

    async def replay(self, thread_id: str) -> list[tuple[int, Event]]:
        """The run's events so far, oldest first, each with its sequence number."""
        ...

    async def clear(self, thread_id: str) -> None: ...


@runtime_checkable
class ActiveRunStore(Protocol):
    """Which run, if any, a thread is currently running."""

    async def begin(self, thread_id: str, run_id: str) -> str | None:
        """Claim the thread for ``run_id``, returning the run already holding it.

        ``None`` means the claim succeeded. An implementation must decide the
        outcome without awaiting between reading and writing, or two runs racing
        can both be told the thread was free.
        """
        ...

    async def end(self, thread_id: str, run_id: str) -> None:
        """Release the thread, if ``run_id`` still holds it."""
        ...


class InMemoryActiveRunStore(ActiveRunStore):
    """Process-local. Not shared across workers."""

    def __init__(self) -> None:
        self._active: dict[str, str] = {}

    async def begin(self, thread_id: str, run_id: str) -> str | None:
        active = self._active.get(thread_id)
        if active is not None:
            return active
        self._active[thread_id] = run_id
        return None

    async def end(self, thread_id: str, run_id: str) -> None:
        # Only the holder releases it, so a refused run cannot free the thread out
        # from under the run that is actually in flight.
        if self._active.get(thread_id) == run_id:
            del self._active[thread_id]

    def reset(self) -> None:
        """Drop every claim. Useful between tests."""
        self._active.clear()


class InMemoryRunEventStore(RunEventStore):
    """Process-local and bounded. Not shared across workers."""

    def __init__(self, max_events_per_run: int = 2000) -> None:
        self._max_events_per_run = max_events_per_run
        self._runs: dict[str, list[tuple[int, Event]]] = {}

    async def append(self, thread_id: str, event: Event) -> int:
        buffered = self._runs.setdefault(thread_id, [])
        seq = buffered[-1][0] + 1 if buffered else 1
        # Dropping the oldest events costs a late joiner the start of the stream,
        # which it sees as a gap in the sequence rather than as missing content.
        if len(buffered) >= self._max_events_per_run:
            del buffered[0]
        buffered.append((seq, event))
        return seq

    async def replay(self, thread_id: str) -> list[tuple[int, Event]]:
        return list(self._runs.get(thread_id, ()))

    async def clear(self, thread_id: str) -> None:
        self._runs.pop(thread_id, None)

    def reset(self) -> None:
        """Drop every buffered run. Useful between tests."""
        self._runs.clear()
