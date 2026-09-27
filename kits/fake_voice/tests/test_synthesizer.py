import pytest

from ...audio_stream_out import SpeechFormat, SynthesizerTopic
from ...audio_stream_out.tests.contract import SynthesizerContract
from ...media_stream_out import InMemoryReplayStore
from ..synthesizer import FakeSynthesizerTopic, word_tones


class Instant(FakeSynthesizerTopic):
    pace = 0
    replay_store = InMemoryReplayStore()


class TestFakeSynthesizerMeetsTheContract(SynthesizerContract):
    @pytest.fixture
    def synthesizer_topic(self) -> type[SynthesizerTopic]:
        return Instant


def test_one_tone_per_word_at_the_requested_rate() -> None:
    pieces = word_tones(
        "two words", SpeechFormat(sample_rate=16000), word_ms=100, gap_ms=50
    )
    assert len(pieces) == 2
    assert all(len(piece) == 16000 * 150 // 1000 * 2 for piece in pieces)


def test_stereo_doubles_the_frames() -> None:
    mono = word_tones("hi", SpeechFormat(), 100, 0)[0]
    stereo = word_tones("hi", SpeechFormat(channels=2), 100, 0)[0]
    assert len(stereo) == 2 * len(mono)
