"""A local Deepgram live endpoint: hears "hello", then "hello world" once finalized."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any
from urllib.parse import parse_qs, urlparse

from websockets.asyncio.server import ServerConnection, serve
from websockets.http11 import Request, Response

KEY = "test-key"


@dataclass
class Recording:
    queries: list[dict[str, list[str]]] = field(
        default_factory=list[dict[str, list[str]]]
    )
    audio_bytes: int = 0
    controls: list[str] = field(default_factory=list[str])


def results(
    text: str, *, final: bool, start: float, duration: float, **extra: Any
) -> str:
    return json.dumps(
        {
            "type": "Results",
            "is_final": final,
            "speech_final": extra.pop("speech_final", False),
            "from_finalize": extra.pop("from_finalize", False),
            "start": start,
            "duration": duration,
            "channel": {
                "alternatives": [{"transcript": text, "confidence": 0.93, "words": []}]
            },
        }
    )


@asynccontextmanager
async def fake_deepgram(
    heard_after_bytes: int = 24000 * 2 * 4 // 10,
) -> AsyncGenerator[tuple[str, Recording]]:
    recording = Recording()

    def check_key(connection: ServerConnection, request: Request) -> Response | None:
        if request.headers.get("Authorization") != f"Token {KEY}":
            return connection.respond(HTTPStatus.UNAUTHORIZED, "invalid credentials\n")
        recording.queries.append(parse_qs(urlparse(request.path).query))
        return None

    async def handler(socket: ServerConnection) -> None:
        received = 0
        spoke = False
        async for message in socket:
            if isinstance(message, bytes):
                received += len(message)
                recording.audio_bytes += len(message)
                if not spoke and received >= heard_after_bytes:
                    spoke = True
                    await socket.send(
                        json.dumps(
                            {"type": "SpeechStarted", "timestamp": 0.1, "channel": [0]}
                        )
                    )
                    await socket.send(
                        results("hello", final=False, start=0.1, duration=0.3)
                    )
                continue
            control = json.loads(message)["type"]
            recording.controls.append(control)
            if control == "Finalize" and spoke:
                await socket.send(
                    results(
                        "hello world",
                        final=True,
                        start=0.1,
                        duration=0.8,
                        from_finalize=True,
                    )
                )
                await socket.send(
                    json.dumps(
                        {"type": "UtteranceEnd", "last_word_end": 0.9, "channel": [0]}
                    )
                )
            elif control == "CloseStream":
                await socket.send(
                    json.dumps(
                        {"type": "Metadata", "request_id": "r1", "duration": 1.0}
                    )
                )
                await socket.close()
                return

    async with serve(handler, "127.0.0.1", 0, process_request=check_key) as server:
        port = server.sockets[0].getsockname()[1]  # type: ignore[index]
        yield f"ws://127.0.0.1:{port}/v1/listen", recording
