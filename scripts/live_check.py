#!/usr/bin/env python
"""Round-trip a provider live: synthesize a sentence, then transcribe it (a few cents).

uv run python scripts/live_check.py deepgram|elevenlabs|openai    # keys from env or .env
"""

import argparse
import asyncio
import importlib
import os
import sys
import time
import wave
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

SENTENCE = "Hello from chanx kit. The weather is lovely today."
# Share of the sentence's words the transcript must contain; "chanx" is rarely heard.
MIN_OVERLAP = 0.6

PROVIDERS = {
    "openai": (
        "OPENAI_API_KEY",
        "openai.synthesizer",
        "OpenAISynthesizerTopic",
        "openai.transcriber",
        "OpenAITranscriberTopic",
    ),
    "deepgram": (
        "DEEPGRAM_API_KEY",
        "deepgram.synthesizer",
        "DeepgramSynthesizerTopic",
        "deepgram.transcriber",
        "DeepgramTranscriberTopic",
    ),
    "elevenlabs": (
        "ELEVENLABS_API_KEY",
        "elevenlabs.synthesizer",
        "ElevenLabsSynthesizerTopic",
        "elevenlabs.transcriber",
        "ElevenLabsTranscriberTopic",
    ),
}


def words(text: str) -> set[str]:
    return {
        "".join(c for c in word.lower() if c.isalnum()) for word in text.split()
    } - {""}


async def check(provider: str, out: Path) -> bool:
    _, synth_module, synth_name, stt_module, stt_name = PROVIDERS[provider]
    audio_start: Any = importlib.import_module("kits.audio_stream_in").AudioStart
    speech_format: Any = importlib.import_module("kits.audio_stream_out").SpeechFormat

    synthesizer: Any = getattr(
        importlib.import_module(f"kits.{synth_module}"), synth_name
    )
    transcriber: Any = getattr(importlib.import_module(f"kits.{stt_module}"), stt_name)

    started = time.perf_counter()
    first_audio = None
    audio = b""
    async for piece in synthesizer.synthesize(SENTENCE, None, speech_format()):
        first_audio = first_audio or time.perf_counter() - started
        audio += piece
    seconds = len(audio) / (24000 * 2)
    print(
        f"synthesizer: {len(audio)} bytes, {seconds:.2f} s of audio, "
        f"first audio after {first_audio or 0:.2f} s"
    )
    with wave.open(str(out), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(audio)
    print(f"  saved {out}")
    if seconds < 1:
        print("FAILED: too little audio")
        return False

    # Back to text in 100 ms chunks, like a microphone.
    topic = transcriber.__new__(transcriber)
    stream = await topic.open_stream(audio_start())
    frames: list[Any] = []

    async def listen() -> None:
        async for frame in stream.frames():
            frames.append(frame)
            print(f"  {type(frame).__name__}: {getattr(frame, 'text', '')}")

    listener = asyncio.ensure_future(listen())
    chunk = 4800
    silence = bytes(24000 * 2)  # a second of quiet, so voice activity detection commits
    for start in range(0, len(audio) + len(silence), chunk):
        await stream.send((audio + silence)[start : start + chunk])
        await asyncio.sleep(0.02)
    await stream.finish()
    await asyncio.wait_for(listener, 20)

    finals = " ".join(
        frame.text for frame in frames if type(frame).__name__ == "FinalFrame"
    )
    overlap = len(words(finals) & words(SENTENCE)) / len(words(SENTENCE))
    print(f"transcriber: final text {finals!r}, {overlap:.0%} of the words")
    kinds = {type(frame).__name__ for frame in frames}
    print(f"  frame kinds: {sorted(kinds)}")
    ok = overlap >= MIN_OVERLAP and "UtteranceEndFrame" in kinds
    print("OK" if ok else "FAILED")
    return ok


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("provider", choices=sorted(PROVIDERS))
    parser.add_argument("--out", type=Path, default=Path("live-check.wav"))
    args = parser.parse_args()
    variable = PROVIDERS[args.provider][0]
    if not os.environ.get(variable):
        print(f"{variable} is not set.", file=sys.stderr)
        return 2
    return 0 if asyncio.run(asyncio.wait_for(check(args.provider, args.out), 60)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
