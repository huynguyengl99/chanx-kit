# voice-agent

Talk to any AG-UI agent over a chanx websocket. Speech is transcribed; each utterance
starts a run once the speaker pauses; the reply is spoken sentence by sentence while it
streams; speaking over the agent interrupts it, and the conversation keeps only what the
user actually heard.

```bash
copit add @chanx-kit/voice-agent
copit add @chanx-kit/deepgram --only stt      # hears with Deepgram
copit add @chanx-kit/elevenlabs --only tts    # speaks with ElevenLabs
```

It composes three kits, all on one session id, all in hooks:

```text
mic --audio--> VoiceTranscriberTopic  transcribe:<session>   (audio-stream-in + a provider)
                   | utterance_end: respond(text)
                   v
               VoiceAgentTopic        agui:thread:<session>  (ag-ui + your agent)
                   | each sentence as it completes: speak()
                   v
               SynthesizerTopic       speak:<session>        (audio-stream-out + a provider)
                   | audio_chunk ... playback_mark
                   v
               speaker
```

## Wire it up

```python
from .ws_kits.deepgram.transcriber import DeepgramTranscriberTopic
from .ws_kits.elevenlabs.synthesizer import ElevenLabsSynthesizerTopic
from .ws_kits.voice_agent import VoiceAgentTopic, VoiceTranscriberTopic


class Voice(ElevenLabsSynthesizerTopic):
    pass


class Agent(VoiceAgentTopic):
    synthesizer = Voice

    async def run_agent(self, run_input):
        async for event in my_agent(run_input.messages):
            yield event


class Ears(VoiceTranscriberTopic, DeepgramTranscriberTopic):
    agent_topic = Agent


class VoiceConsumer(AsyncJsonWebsocketConsumer):
    topics = [Ears, Agent, Voice]
```

The client subscribes to all three with the same session: the
[voice-agent UI kit](../../ui/voice-agent) does it in one hook. Swap Deepgram for the
fake transcriber, or ElevenLabs for the fake synthesizer, and nothing else changes.

With a provider kit that keeps its own conversation, combine the classes and send only
the new turn:

```python
class Agent(VoiceAgentTopic, PydanticAIAgUiTopic):
    synthesizer = Voice
    agent = my_pydantic_agent
    send_history = False
```

## What happens

- **Turns**: `VoiceTranscriberTopic` collects an utterance's finals and, on
  `utterance_end`, calls `on_turn(text)`, which calls `Agent.respond(session, text)`.
  Override `on_turn` to filter ("um"), route, or add context.
- **Runs** start from the server with `AgUiTopic.start_run`: every tab on the thread
  sees them, and a tab joining mid-reply is replayed the run. A typed message (a client
  `ag_ui_run`) is answered out loud the same way.
- **Speech starts early**: `run_events` cuts the reply's text deltas into sentences
  (`SentenceBuffer`) and queues each one on the synthesizer as soon as it is complete,
  so the first words play while the agent is still writing.
- **Barge-in**: `speech_started` while the agent is running or speaking calls
  `Agent.interrupt(session)`: the synthesizer clears every listener, the run is
  cancelled (`RUN_ERROR`), the reply in memory is cut to what `playback_mark` says was
  heard, and a `CUSTOM` event `voice_interrupted` carries that text to chat UIs. Set
  `interrupt_on_speech = False` to turn it off.
- **Memory**: `memory` (`InMemoryVoiceMemory` by default) keeps the conversation as
  AG-UI messages, since no client sends it. Implement `VoiceMemory` to persist it.

!!! note "One process per session"
    Runs, speech queues and barge-in bookkeeping live in the process holding the
    session's socket, as the audio does. The channel layer carries only events.
