# Add voice

Speech in and speech out over your chanx websocket: microphone audio becomes live
captions, text becomes audio every listener hears, and optionally an agent answers out
loud. Provider API keys stay on your server, and switching provider is one base class.

The pieces:

| Kit | Side | What it does |
|---|---|---|
| [`fake-voice`](kits/fake-voice.md), [`deepgram`](kits/deepgram.md), [`elevenlabs`](kits/elevenlabs.md), [`openai`](kits/openai.md) | server | a provider, with a speech-to-text part (`stt`) and a text-to-speech part (`tts`) |
| [`audio-stream-in`](kits/audio-stream-in.md), [`audio-stream-out`](kits/audio-stream-out.md) | server | the contracts and plumbing; installed with a provider |
| [`transcriber`](ui/transcriber.md), [`player`](ui/player.md) | browser | microphone and captions, playback |
| [`voice-agent`](kits/voice-agent.md) (both sides) | both | an AG-UI agent you talk to |

This page assumes both registries are set up ([Getting started](getting-started.md),
[UI kits](ui-kits.md)). The [starter template](getting-started.md#start-a-new-project)
has them already.

## 1. Try it with no account

`fake-voice` transcribes any speech as a scripted sentence and speaks text as a tone
per word, so the whole path works before you sign up anywhere.

```bash
uvx copit add @chanx-kit/fake-voice
uvx copit add @chanx-kit-ui/transcriber @chanx-kit-ui/player
```

Mount the topics on a consumer:

```python
from chanx.core.decorators import channel
from chanx.fast_channels.websocket import AsyncJsonWebsocketConsumer

from .ws_kits.audio_stream_in import TranscriptTopic
from .ws_kits.fake_voice.synthesizer import FakeSynthesizerTopic
from .ws_kits.fake_voice.transcriber import FakeTranscriberTopic


class MicTopic(FakeTranscriberTopic):
    async def authorize(self, **params: str) -> bool:
        return user_owns_session(self.scope, params["session"])


class VoiceTopic(FakeSynthesizerTopic):
    pass


@channel(name="voice")
class VoiceConsumer(AsyncJsonWebsocketConsumer):
    channel_layer_alias = "default"
    topics = [MicTopic, TranscriptTopic, VoiceTopic]
```

Route it (`/ws/voice`), regenerate the client (`npm run --prefix web gen`), and use it:

```tsx
import { Recorder, TranscriptView, useTranscriber } from '@/chanx-kit/transcriber/react';
import { Player, usePlayer } from '@/chanx-kit/player/react';
import '@/chanx-kit/transcriber/transcriber.css';
import '@/chanx-kit/player/player.css';
import { voice } from '@/generated';

export function Voice({ session }: { session: string }) {
  const mic = useTranscriber(voice, voice.topics.micTopic.with({ session }));
  const speech = usePlayer(voice, voice.topics.voiceTopic.with({ session }));

  return (
    <>
      <Recorder
        recording={mic.recording}
        level={mic.level}
        error={mic.error}
        onStart={mic.start}
        onStop={mic.stop}
        disabled={mic.status !== 'open'}
      />
      <TranscriptView utterances={mic.utterances} speaking={mic.speaking} />
      <Player {...speech} onUnlock={speech.unlock} onStop={speech.stop} />
      <button onClick={() => { void speech.unlock(); speech.speak('Hello there.'); }}>
        Speak
      </button>
    </>
  );
}
```

Start recording from a click: browsers only open the microphone and play audio after a
user gesture.

## 2. Switch to a real provider

Install the provider and change the two base classes. The browser code does not change.

```bash
uvx copit add @chanx-kit/deepgram
```

```python
from .ws_kits.deepgram.synthesizer import DeepgramSynthesizerTopic
from .ws_kits.deepgram.transcriber import DeepgramTranscriberTopic


class MicTopic(DeepgramTranscriberTopic): ...
class VoiceTopic(DeepgramSynthesizerTopic): ...
```

Set the key in the server's environment. It is read when used, so a `.env` loaded at
startup works:

| Provider | Key | Speech to text | Text to speech |
|---|---|---|---|
| `deepgram` | `DEEPGRAM_API_KEY` | Nova, live | Aura |
| `elevenlabs` | `ELEVENLABS_API_KEY` | Scribe realtime | streaming voices (premade ones on the free tier) |
| `openai` | `OPENAI_API_KEY` | realtime transcription | `gpt-4o-mini-tts` |

### Only one side, or two providers

Each provider installs both parts by default. Keep one with `--only`, which also
leaves out the audio kit only the other part needs:

```bash
uvx copit add @chanx-kit/deepgram --only stt      # captions only
uvx copit add @chanx-kit/elevenlabs --only tts    # a second command: ElevenLabs speaks
```

`--only` applies to every kit in the command, so give each provider its own.

## 3. Talk to an agent

The voice-agent kit connects the transcriber to an [AG-UI](kits/ag-ui.md) agent and
the agent's reply to the synthesizer: each utterance starts a run once the speaker
pauses, the reply is spoken sentence by sentence while it streams, and speaking over
it interrupts.

```bash
uvx copit add @chanx-kit/voice-agent @chanx-kit-ui/voice-agent
```

```python
from .ws_kits.voice_agent import VoiceAgentTopic, VoiceTranscriberTopic


class Agent(VoiceAgentTopic):
    synthesizer = VoiceTopic

    async def run_agent(self, run_input):
        async for event in my_agent(run_input.messages):
            yield event


class Ears(VoiceTranscriberTopic, DeepgramTranscriberTopic):
    agent_topic = Agent


@channel(name="assistant")
class AssistantConsumer(AsyncJsonWebsocketConsumer):
    channel_layer_alias = "default"
    topics = [Ears, Agent, VoiceTopic]
```

```tsx
import { VoiceAgent, useVoiceAgent } from '@/chanx-kit/voice-agent/react';

const agent = useVoiceAgent(assistant, {
  transcriber: assistant.topics.earsTopic.with({ session }),
  synthesizer: assistant.topics.voiceTopic.with({ session }),
  thread: assistant.topics.agentTopic.with({ thread_id: session }),
});
return <VoiceAgent agent={agent} />;
```

Barge-in needs the transcriber to report speech starting: Deepgram and ElevenLabs do,
OpenAI does with `turn_detection = {"type": "server_vad"}` and `model =
"gpt-4o-transcribe"`. Without headphones, the browser's echo cancellation keeps the
agent from hearing itself.

## Good to know

- **Limits.** Providers bill per second of audio, so transcriber streams are bounded:
  `max_session_seconds`, `idle_timeout_seconds` and `max_sessions_per_user` on the
  topic, `None` to turn one off. Text to speak is capped by `max_text_chars`.
- **Several processes.** Replay for late joiners, playback marks, the agent's memory
  and interruption live in the process holding the socket. Implement the kits' store
  protocols against Redis before running more than one worker.
- **Other providers.** [`pipecat-bridge`](kits/pipecat-bridge.md) puts any
  [Pipecat](https://docs.pipecat.ai) speech-to-text service behind the same contract.
- **Your own provider.** Subclass `TranscriberTopic` or `SynthesizerTopic` and run the
  contract's shared test suite against it; see
  [`audio-stream-in`](kits/audio-stream-in.md#writing-a-provider).
