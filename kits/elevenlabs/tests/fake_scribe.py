"""A local stand-in for ElevenLabs' realtime speech-to-text, per its documented protocol."""

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
    queries: list[dict[str, list[str]]] = field(
        default_factory=list[dict[str, list[str]]]
    )
    audio_bytes: int = 0
    commits: int = 0


@asynccontextmanager
async def fake_scribe(
    heard_after_bytes: int = 24000 * 2 * 4 // 10,
) -> AsyncGenerator[tuple[str, Recording]]:
    recording = Recording()

    def check_key(connection: ServerConnection, request: Request) -> Response | None:
        if request.headers.get("xi-api-key") != KEY:
            return connection.respond(HTTPStatus.UNAUTHORIZED, "invalid api key\n")
        recording.queries.append(parse_qs(urlparse(request.path).query))
        return None

    async def handler(socket: ServerConnection) -> None:
        await socket.send(
            json.dumps({"message_type": "session_started", "session_id": "s"})
        )
        received = 0
        spoke = False
        async for raw in socket:
            message = json.loads(raw)
            assert message["message_type"] == "input_audio_chunk"
            audio = base64.b64decode(message["audio_base_64"])
            received += len(audio)
            recording.audio_bytes += len(audio)
            if not spoke and received >= heard_after_bytes:
                spoke = True
                await socket.send(
                    json.dumps({"message_type": "partial_transcript", "text": "hello"})
                )
            if message["commit"]:
                recording.commits += 1
                if spoke:
                    await socket.send(
                        json.dumps(
                            {
                                "message_type": "committed_transcript",
                                "text": "hello world",
                            }
                        )
                    )

    async with serve(handler, "127.0.0.1", 0, process_request=check_key) as server:
        port = server.sockets[0].getsockname()[1]  # type: ignore[index]
        yield f"ws://127.0.0.1:{port}/v1/speech-to-text/realtime", recording
