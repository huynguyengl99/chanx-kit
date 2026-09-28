"""Consumers composing every kit in the registry.

This is the reference for how kits are meant to be combined, and the backend the demo
UI and the TypeScript generator both read from.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any, ClassVar
from uuid import uuid4

from chanx.core.decorators import channel, ws_handler
from chanx.core.topic import Topic
from chanx.fast_channels.websocket import AsyncJsonWebsocketConsumer
from chanx.messages.incoming import PingMessage
from chanx.messages.outgoing import PongMessage
from chanx.utils.scope import query_params
from kits.ag_ui import AgUiEventMessage, AgUiRunTopic, AgUiTopic
from kits.audio_stream_in import (
    TranscriptFinalMessage,
    TranscriptTopic,
)
from kits.fake_voice.synthesizer import FakeSynthesizerTopic
from kits.fake_voice.transcriber import FakeTranscriberTopic
from kits.notification import (
    BroadcastNotificationTopic,
    NotificationMessage,
    SubjectNotificationTopic,
    UserNotificationTopic,
)
from kits.presence import (
    PresenceJoinMessage,
    PresenceLeaveMessage,
    PresenceMember,
    PresenceTopic,
)
from kits.room_chat import ChatAuthor, ChatMessage, RoomChatTopic
from kits.voice_agent import VoiceAgentTopic, VoiceTranscriberTopic

from ag_ui.core import (
    Event,
    EventType,
    RunAgentInput,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
)

LAYER = "default"


def _who(scope: Any) -> str:
    """The demo has no auth, so identity comes from the query string."""
    return query_params(scope).get("as", ["anonymous"])[0]


# Each subclass answers one identity hook from the query string, standing in for the
# auth a real project would have. Group names carry the class name, so outside code
# broadcasts through these, not the kit classes.
class DemoUserNotificationTopic(UserNotificationTopic):
    def current_user_id(self) -> str | None:
        return _who(self.scope)


class DemoPresenceTopic(PresenceTopic):
    def presence_member(self) -> PresenceMember:
        who = _who(self.scope)
        return PresenceMember(id=who, name=who.title())


class DemoChatTopic(RoomChatTopic):
    def chat_author(self) -> ChatAuthor:
        who = _who(self.scope)
        return ChatAuthor(id=who, name=who.title())


@channel(
    name="notifications",
    description="Fan-out notifications for the connected user.",
    tags=["notification"],
)
class NotificationConsumer(AsyncJsonWebsocketConsumer[NotificationMessage]):
    channel_layer_alias = LAYER
    topics: ClassVar[list[type[Topic[Any]]]] = [
        DemoUserNotificationTopic,
        SubjectNotificationTopic,
        BroadcastNotificationTopic,
    ]

    @ws_handler(summary="Ping", description="Connection health check.")
    async def handle_ping(self, _message: PingMessage) -> PongMessage:
        return PongMessage()


@channel(
    name="room",
    description="Room chat with history and a live roster.",
    tags=["chat", "presence"],
)
class RoomConsumer(
    AsyncJsonWebsocketConsumer[
        ChatMessage | PresenceJoinMessage | PresenceLeaveMessage
    ],
):
    """Two independent kits listed side by side: chat and the roster."""

    channel_layer_alias = LAYER
    topics: ClassVar[list[type[Topic[Any]]]] = [DemoChatTopic, DemoPresenceTopic]

    @ws_handler(summary="Ping", description="Connection health check.")
    async def handle_ping(self, _message: PingMessage) -> PongMessage:
        return PongMessage()


class DemoAgUiTopic(AgUiTopic):
    """Scripts the events a provider would produce; the demo has no model
    credentials, so the protocol is identical but the content is local."""

    channel_layer_alias = LAYER

    async def run_agent(self, run_input: RunAgentInput) -> AsyncIterator[Event]:
        message_id = uuid4().hex
        yield TextMessageStartEvent(
            type=EventType.TEXT_MESSAGE_START, message_id=message_id
        )
        for word in _canned_reply(run_input).split():
            yield TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT,
                message_id=message_id,
                delta=word + " ",
            )
            await asyncio.sleep(0.04)
        yield TextMessageEndEvent(
            type=EventType.TEXT_MESSAGE_END, message_id=message_id
        )


@channel(
    name="agent",
    description="AG-UI protocol over a websocket.",
    tags=["agent", "ag-ui"],
)
class AgentConsumer(AsyncJsonWebsocketConsumer[AgUiEventMessage]):
    """Speaks AG-UI, so an AG-UI frontend works against this unchanged. A run is its
    own topic, so another process can emit into it. See sandbox/worker.py."""

    channel_layer_alias = LAYER
    topics: ClassVar[list[type[Topic[Any]]]] = [DemoAgUiTopic, AgUiRunTopic]

    @ws_handler(summary="Ping", description="Connection health check.")
    async def handle_ping(self, _message: PingMessage) -> PongMessage:
        return PongMessage()


# A real provider when its key is set, the fake otherwise; the client cannot tell.
PROVIDERS = {
    "stt": "deepgram" if os.environ.get("DEEPGRAM_API_KEY") else "fake-voice",
    "tts": "elevenlabs" if os.environ.get("ELEVENLABS_API_KEY") else "fake-voice",
}
if TYPE_CHECKING:
    TranscriberBase = FakeTranscriberTopic
    SynthesizerBase = FakeSynthesizerTopic
else:
    from kits.deepgram.transcriber import DeepgramTranscriberTopic
    from kits.elevenlabs.synthesizer import ElevenLabsSynthesizerTopic

    TranscriberBase = (
        DeepgramTranscriberTopic
        if PROVIDERS["stt"] == "deepgram"
        else FakeTranscriberTopic
    )
    SynthesizerBase = (
        ElevenLabsSynthesizerTopic
        if PROVIDERS["tts"] == "elevenlabs"
        else FakeSynthesizerTopic
    )


class DemoTranscriberTopic(TranscriberBase):
    """Microphone audio in, transcripts out: ``transcribe:<session>``."""

    channel_layer_alias = LAYER


class DemoSynthesizerTopic(SynthesizerBase):
    """Text in, speech out to every listener: ``speak:<session>``."""

    channel_layer_alias = LAYER


@channel(
    name="voice",
    description="Speech in and out: transcripts from audio, audio from text.",
    tags=["audio", "transcription", "speech"],
)
class VoiceConsumer(AsyncJsonWebsocketConsumer[TranscriptFinalMessage]):
    """A session's audio on one topic, its transcript for watchers on another."""

    channel_layer_alias = LAYER
    topics: ClassVar[list[type[Topic[Any]]]] = [
        DemoTranscriberTopic,
        TranscriptTopic,
        DemoSynthesizerTopic,
    ]

    @ws_handler(summary="Ping", description="Connection health check.")
    async def handle_ping(self, _message: PingMessage) -> PongMessage:
        return PongMessage()


class AssistantVoiceTopic(SynthesizerBase):
    """The assistant's voice: ``speak:<session>``."""

    channel_layer_alias = LAYER


class AssistantTopic(VoiceAgentTopic):
    """The assistant: ``agui:thread:<session>``. Replies are spoken as they stream."""

    channel_layer_alias = LAYER
    synthesizer = AssistantVoiceTopic

    async def run_agent(self, run_input: RunAgentInput) -> AsyncIterator[Event]:
        message_id = uuid4().hex
        yield TextMessageStartEvent(
            type=EventType.TEXT_MESSAGE_START, message_id=message_id
        )
        for word in _canned_reply(run_input).split():
            yield TextMessageContentEvent(
                type=EventType.TEXT_MESSAGE_CONTENT,
                message_id=message_id,
                delta=word + " ",
            )
            await asyncio.sleep(0.04)
        yield TextMessageEndEvent(
            type=EventType.TEXT_MESSAGE_END, message_id=message_id
        )


class AssistantEarsTopic(VoiceTranscriberTopic, TranscriberBase):
    """What the user says to the assistant: ``transcribe:<session>``."""

    channel_layer_alias = LAYER
    agent_topic = AssistantTopic


@channel(
    name="assistant",
    description="A voice agent: speak, hear the reply, interrupt by speaking.",
    tags=["audio", "agent", "ag-ui"],
)
class AssistantConsumer(AsyncJsonWebsocketConsumer[AgUiEventMessage]):
    """Three kits on one session: transcriber, AG-UI agent, synthesizer."""

    channel_layer_alias = LAYER
    topics: ClassVar[list[type[Topic[Any]]]] = [
        AssistantEarsTopic,
        AssistantTopic,
        AssistantVoiceTopic,
    ]

    @ws_handler(summary="Ping", description="Connection health check.")
    async def handle_ping(self, _message: PingMessage) -> PongMessage:
        return PongMessage()


def _canned_reply(run_input: RunAgentInput) -> str:
    last = run_input.messages[-1].content if run_input.messages else ""
    return (
        f"You said: {last!r}. This sandbox has no model credentials, so these AG-UI "
        "events are produced locally to show the protocol travelling over a chanx "
        "websocket."
    )
