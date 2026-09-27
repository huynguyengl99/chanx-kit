"""Cut a stream of text deltas into sentences, so speech starts before the reply ends."""

import re

# A sentence ends at . ! ? or an ellipsis followed by space, or at a line break.
_BOUNDARY = re.compile(r"(?<=[.!?…])[\"')\]]*\s+|\n+")


class SentenceBuffer:
    """Cut streamed text into sentences; tiny ones wait for the next."""

    def __init__(self, min_chars: int = 12) -> None:
        self._min = min_chars
        self._text = ""

    def feed(self, delta: str) -> list[str]:
        self._text += delta
        sentences: list[str] = []
        start = 0
        for match in _BOUNDARY.finditer(self._text):
            candidate = self._text[start : match.end()].strip()
            if len(candidate) >= self._min:
                sentences.append(candidate)
                start = match.end()
        self._text = self._text[start:]
        return sentences

    def flush(self) -> str | None:
        """Whatever is left, at the end of the reply."""
        rest, self._text = self._text.strip(), ""
        return rest or None
