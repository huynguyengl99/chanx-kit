"""A local stand-in for Deepgram's speak WebSocket, per its documented protocol."""

import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from http import HTTPStatus
from urllib.parse import parse_qs, urlparse

from websockets.asyncio.server import ServerConnection, serve
from websockets.http11 import Request, Response

KEY = "test-key"


@dataclass
class Recording:
    queries: list[dict[str, list[str]]] = field(
        default_factory=list[dict[str, list[str]]]
    )
    messages: list[dict[str, str]] = field(default_factory=list[dict[str, str]])


@asynccontextmanager
async def fake_speak() -> AsyncGenerator[tuple[str, Recording]]:
    recording = Recording()

    def check_key(connection: ServerConnection, request: Request) -> Response | None:
        if request.headers.get("Authorization") != f"Token {KEY}":
            return connection.respond(HTTPStatus.UNAUTHORIZED, "invalid credentials\n")
        recording.queries.append(parse_qs(urlparse(request.path).query))
        return None

    async def handler(socket: ServerConnection) -> None:
        await socket.send(json.dumps({"type": "Metadata", "request_id": "r1"}))
        text = ""
        async for raw in socket:
            message = json.loads(raw)
            recording.messages.append(message)
            if message["type"] == "Speak":
                text += message["text"]
            elif message["type"] == "Flush":
                audio = b"\x03\x04" * (len(text) * 24000 // 50)  # 20 ms per character
                for start in range(0, len(audio), 4001):
                    await socket.send(audio[start : start + 4001])
                await socket.send(json.dumps({"type": "Flushed", "sequence_id": 0}))
            elif message["type"] == "Close":
                return

    async with serve(handler, "127.0.0.1", 0, process_request=check_key) as server:
        port = server.sockets[0].getsockname()[1]  # type: ignore[index]
        yield f"ws://127.0.0.1:{port}/v1/speak", recording
