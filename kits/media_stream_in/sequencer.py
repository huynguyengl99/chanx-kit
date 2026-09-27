"""Chunks back in index order, with gaps reported rather than papered over."""

from dataclasses import dataclass, field


@dataclass
class Gap:
    """Chunks ``start`` up to ``end`` (exclusive) never arrived."""

    start: int
    end: int


@dataclass
class ChunkSequencer:
    """Release chunks in ``index`` order; report ones that never arrive as gaps."""

    window: int = 8
    expected: int = 0
    _pending: dict[int, bytes] = field(default_factory=dict[int, bytes])

    def reset(self) -> None:
        self.expected = 0
        self._pending.clear()

    def push(self, index: int, data: bytes) -> tuple[list[bytes], list[Gap]]:
        """Accept one chunk; return what can be released now, and any gaps."""
        if index < self.expected or index in self._pending:
            return [], []
        self._pending[index] = data
        return self._release(give_up=False)

    def flush(self) -> tuple[list[bytes], list[Gap]]:
        """Release everything held, at the end of a stream."""
        return self._release(give_up=True)

    def _release(self, *, give_up: bool) -> tuple[list[bytes], list[Gap]]:
        ready: list[bytes] = []
        gaps: list[Gap] = []
        while self._pending:
            if self.expected in self._pending:
                ready.append(self._pending.pop(self.expected))
                self.expected += 1
            elif give_up or len(self._pending) > self.window:
                following = min(self._pending)
                gaps.append(Gap(self.expected, following))
                self.expected = following
            else:
                break
        return ready, gaps
