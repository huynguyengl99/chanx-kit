"""A local stand-in for OpenAI's realtime transcription, per its documented protocol."""

import base64
import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from http import HTTPStatus
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.http11 import Request, Response

KEY = "test-key"


@dataclass
class Recording:
    sessions: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    audio_bytes: int = 0
    commits: int = 0


@asynccontextmanager
async def fake_realtime(
    heard_after_bytes: int = 24000 * 2 * 4 // 10,
) -> AsyncGenerator[tuple[str, Recording]]:
    recording = Recording()

    def check_key(connection: ServerConnection, request: Request) -> Response | None:
        if request.headers.get("Authorization") != f"Bearer {KEY}":
            return connection.respond(HTTPStatus.UNAUTHORIZED, "invalid api key\n")
        return None

    async def handler(socket: ServerConnection) -> None:
        received = 0
        spoke = False
        item = 0
        async for raw in socket:
            event = json.loads(raw)
            if event["type"] == "session.update":
                recording.sessions.append(event["session"])
            elif event["type"] == "input_audio_buffer.append":
                audio = base64.b64decode(event["audio"])
                received += len(audio)
                recording.audio_bytes += len(audio)
                if not spoke and received >= heard_after_bytes:
                    spoke = True
                    await socket.send(
                        json.dumps(
                            {
                                "type": "conversation.item.input_audio_transcription.delta",
                                "item_id": f"i{item}",
                                "delta": "hello",
                            }
                        )
                    )
            elif event["type"] == "input_audio_buffer.commit":
                recording.commits += 1
                if not spoke:
                    await socket.send(
                        json.dumps(
                            {
                                "type": "error",
                                "error": {
                                    "code": "input_audio_buffer_commit_empty",
                                    "message": "buffer too small",
                                },
                            }
                        )
                    )
                    continue
                await socket.send(
                    json.dumps(
                        {
                            "type": "conversation.item.input_audio_transcription.delta",
                            "item_id": f"i{item}",
                            "delta": " world",
                        }
                    )
                )
                await socket.send(
                    json.dumps(
                        {
                            "type": "conversation.item.input_audio_transcription.completed",
                            "item_id": f"i{item}",
                            "transcript": "hello world",
                        }
                    )
                )
                item += 1

    async with serve(handler, "127.0.0.1", 0, process_request=check_key) as server:
        port = server.sockets[0].getsockname()[1]  # type: ignore[index]
        yield f"ws://127.0.0.1:{port}/v1/realtime?intent=transcription", recording
