# Player

Play what a server speaks, for any server speaking **synthesizer@1**:
[`fake-voice`](../../kits/fake_voice) while you build,
[`elevenlabs`](../../kits/elevenlabs) (or any provider kit's `tts` part) in production.

```bash
copit add @chanx-kit-ui/player
```

## React

```tsx
import { Player, usePlayer } from '@/chanx-kit/player/react';
import '@/chanx-kit/player/player.css';
import { voice } from '@/generated';

export function Speech({ session }: { session: string }) {
  const player = usePlayer(voice, voice.topics.synthesizerTopic.with({ session }));
  return (
    <>
      <Player {...player} onUnlock={player.unlock} onStop={player.stop} />
      <button onClick={() => player.speak('Hello there.')}>Say hello</button>
    </>
  );
}
```

The server can speak on its own too (`SynthesizerTopic.speak(session, text)` from an
agent or a worker); every player on the session plays it.

## What the playback does

- **Jitter buffer**: an AudioWorklet waits for `prebufferMs` (150 ms) of audio before
  playing, and again whenever it runs dry mid-utterance; the end of an utterance plays
  out regardless.
- **Resampling** from the utterance's rate to the device's.
- **Replay-safe**: a tab joining mid-utterance is replayed it; chunks already played
  (by `index`) are skipped.
- **Interruption**: `clear` from the server empties the buffer at once. `stop()` asks the
  server for that, which clears every listener.
- **Playback marks**: `playback_mark` every `markEveryMs` (250 ms) and at the end or on
  a clear, so the server knows how much was actually heard.
- **Autoplay**: browsers hold audio until a user gesture. `needsUnlock` says so; call
  `unlock()` from a click (the `<Player>` shows an "Enable audio" button).

The worklet is inline JS loaded from a `Blob`; with a CSP that forbids `blob:`, serve
`PLAYBACK_WORKLET` as a file and pass `workletUrl`.

!!! warning "Test on real devices"
    Autoplay rules and audio output differ by browser and platform (iOS Safari first).

## Without a framework

```ts
import { connectPlayer } from '@/chanx-kit/player';

const speech = connectPlayer(client, voice, voice.topics.synthesizerTopic.with({ session }));
speech.start();
button.onclick = () => speech.unlock();
```
