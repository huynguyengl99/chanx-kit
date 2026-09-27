import asyncio
from typing import Literal

import pytest
from chanx.messages.base import BaseMessage
from pydantic import BaseModel, ValidationError

from ..data import Base64Data
from ..intake import MediaIntake
from ..sequencer import ChunkSequencer, Gap

AUDIO = bytes(range(256))  # every byte value, most of them invalid as UTF-8 and base64


class Chunk(BaseModel):
    data: Base64Data


class ChunkMessage(BaseMessage):
    action: Literal["chunk"] = "chunk"
    payload: Chunk


def test_bytes_built_in_python_travel_as_standard_base64() -> None:
    message = ChunkMessage(payload=Chunk(data=AUDIO))
    wire = message.model_dump(mode="json")["payload"]["data"]

    assert Chunk.model_validate({"data": wire}).data == AUDIO
    assert "-" not in wire and "_" not in wire  # standard, not URL-safe


def test_base64_from_the_wire_arrives_as_bytes() -> None:
    assert Chunk.model_validate_json('{"data": "AAEC/w=="}').data == b"\x00\x01\x02\xff"


def test_invalid_base64_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Chunk.model_validate({"data": "not base64!"})


def test_the_schema_says_base64() -> None:
    schema = Chunk.model_json_schema()["properties"]["data"]
    assert schema["type"] == "string"
    assert schema["format"] == "base64"


def test_in_order_chunks_pass_straight_through() -> None:
    sequencer = ChunkSequencer()
    assert sequencer.push(0, b"a") == ([b"a"], [])
    assert sequencer.push(1, b"b") == ([b"b"], [])


def test_an_early_chunk_waits_for_the_one_before_it() -> None:
    sequencer = ChunkSequencer()
    assert sequencer.push(1, b"b") == ([], [])
    assert sequencer.push(0, b"a") == ([b"a", b"b"], [])


def test_duplicates_and_stale_chunks_are_dropped() -> None:
    sequencer = ChunkSequencer()
    sequencer.push(0, b"a")
    assert sequencer.push(0, b"a") == ([], [])
    sequencer.push(2, b"c")
    assert sequencer.push(2, b"c") == ([], [])


def test_a_missing_chunk_becomes_a_gap_once_the_window_fills() -> None:
    sequencer = ChunkSequencer(window=2)
    sequencer.push(0, b"a")
    assert sequencer.push(2, b"c") == ([], [])
    assert sequencer.push(3, b"d") == ([], [])
    assert sequencer.push(4, b"e") == ([b"c", b"d", b"e"], [Gap(1, 2)])


def test_flush_releases_what_is_held_and_names_the_gaps() -> None:
    sequencer = ChunkSequencer()
    sequencer.push(0, b"a")
    sequencer.push(3, b"d")
    assert sequencer.flush() == ([b"d"], [Gap(1, 3)])


async def test_the_intake_feeds_in_order_then_ends() -> None:
    seen: list[bytes] = []
    ended = asyncio.Event()

    async def sink(chunk: bytes) -> None:
        seen.append(chunk)

    async def on_end() -> None:
        ended.set()

    intake = MediaIntake(sink, on_end=on_end)
    intake.start()
    for chunk in (b"1", b"2", b"3"):
        intake.feed(chunk)
    intake.end()
    await asyncio.wait_for(ended.wait(), 1)

    assert seen == [b"1", b"2", b"3"]


async def test_a_full_intake_drops_the_oldest() -> None:
    seen: list[bytes] = []
    release = asyncio.Event()

    async def sink(chunk: bytes) -> None:
        await release.wait()
        seen.append(chunk)

    async def on_end() -> None:
        pass

    intake = MediaIntake(sink, on_end=on_end, max_chunks=2)
    intake.start()
    intake.feed(b"1")
    await asyncio.sleep(0)  # the sink now holds 1
    for chunk in (b"2", b"3", b"4"):
        intake.feed(chunk)
    intake.end()
    release.set()
    await intake.wait()

    assert intake.dropped == 2
    assert seen == [b"1", b"4"]


async def test_quiet_time_sends_keepalives_then_goes_idle() -> None:
    quiet: list[str] = []

    async def sink(chunk: bytes) -> None:
        pass

    async def on_end() -> None:
        pass

    async def on_quiet(kind: str) -> None:
        quiet.append(kind)

    intake = MediaIntake(
        sink,
        on_end=on_end,
        on_quiet=on_quiet,
        keepalive_seconds=0.02,
        idle_seconds=0.07,
    )
    intake.start()
    await asyncio.wait_for(intake.wait(), 1)

    assert quiet[-1] == "idle"
    assert quiet.count("keepalive") >= 2
