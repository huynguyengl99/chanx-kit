"""A local stand-in for ElevenLabs' stream-input endpoint, per its documented protocol."""

import base64
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
    paths: list[str] = field(default_factory=list[str])
    queries: list[dict[str, list[str]]] = field(
        default_factory=list[dict[str, list[str]]]
    )
    messages: list[dict[str, object]] = field(default_factory=list[dict[str, object]])


@asynccontextmanager
async def fake_elevenlabs() -> AsyncGenerator[tuple[str, Recording]]:
    recording = Recording()

    def check_key(connection: ServerConnection, request: Request) -> Response | None:
        if request.headers.get("xi-api-key") != KEY:
            return connection.respond(HTTPStatus.UNAUTHORIZED, "invalid api key\n")
        parsed = urlparse(request.path)
        recording.paths.append(parsed.path)
        recording.queries.append(parse_qs(parsed.query))
        return None

    async def handler(socket: ServerConnection) -> None:
        spoken = ""
        async for raw in socket:
            message = json.loads(raw)
            recording.messages.append(message)
            if message["text"] == "":
                # Audio for what was sent: 20 ms per character, in odd-sized pieces.
                audio = b"\x01\x02" * (len(spoken.strip()) * 24000 // 50)
                for start in range(0, len(audio), 3001):
                    piece = base64.b64encode(audio[start : start + 3001]).decode()
                    await socket.send(json.dumps({"audio": piece, "isFinal": None}))
                await socket.send(json.dumps({"audio": None, "isFinal": True}))
                return
            spoken += str(message["text"])

    async with serve(handler, "127.0.0.1", 0, process_request=check_key) as server:
        port = server.sockets[0].getsockname()[1]  # type: ignore[index]
        yield (
            f"ws://127.0.0.1:{port}/v1/text-to-speech/{{voice_id}}/stream-input",
            recording,
        )
