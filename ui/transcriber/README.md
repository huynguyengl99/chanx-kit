# Transcriber

Record from the microphone and show live captions, for any server speaking
**transcriber@1**: [`fake-voice`](../../kits/fake_voice) while you build,
[`deepgram`](../../kits/deepgram) (or any provider kit's `stt` part) in production. Switching
provider changes one server class, not this UI.

```bash
copit add @chanx-kit-ui/transcriber
```

## React

```tsx
import { Recorder, TranscriptView, useTranscriber } from '@/chanx-kit/transcriber/react';
import '@/chanx-kit/transcriber/transcriber.css';
import { voice } from '@/generated';

export function Dictation({ session }: { session: string }) {
  const { utterances, speaking, recording, level, error, status, start, stop } = useTranscriber(
    voice,
    voice.topics.transcriberTopic.with({ session }),
  );
  return (
    <>
      <Recorder recording={recording} level={level} error={error}
                onStart={start} onStop={stop} disabled={status !== 'open'} />
      <TranscriptView utterances={utterances} speaking={speaking} />
    </>
  );
}
```

Another tab, or captions on a shared screen, watches the same session read-only:

```tsx
const { utterances } = useTranscript(voice, voice.topics.transcriptTopic.with({ session }));
```

## What the capture does

- `getUserMedia` (echo cancellation, noise suppression and auto gain on), an
  AudioWorklet that downmixes to mono, resampling from the device rate to the rate the
  server's `audio_config` asks for (24 kHz by default), PCM16, and fixed chunks
  (100 ms by default), numbered from 0 and sent as base64.
- The worklet is inline JS loaded from a `Blob` URL, so no bundler setup is needed. If
  your Content-Security-Policy forbids `blob:` workers, serve `CAPTURE_WORKLET` as a
  file and pass `workletUrl`.
- `start()` must run from a user gesture (a click): browsers keep audio contexts
  suspended until one. Stopping sends the last partial chunk, then `audio_end`, so the
  provider flushes its final words.
- A `transcriber_error` that ends the stream (`limit_reached`, `provider_unavailable`,
  `bad_format`) stops recording and shows in `error`; `audio_gap` does not.

!!! warning "Test on real devices"
    Microphone permissions, iOS Safari's audio sample rates and autoplay rules differ by
    platform. The capture is unit tested with a fake microphone, and each release
    should be tried on a real phone.

## Without a framework

```ts
import { connectTranscriber, utteranceText } from '@/chanx-kit/transcriber';

const dictation = connectTranscriber(client, voice, voice.topics.transcriberTopic.with({ session }));
dictation.transcript.subscribe(() =>
  render(dictation.transcript.getSnapshot().utterances.map(utteranceText)),
);
dictation.start();
button.onclick = () => dictation.record();
```

The pieces are exported separately too: `createTranscript` (the store),
`createRecorder` (microphone to messages), `openMicrophone`, and the pure helpers
`Resampler`, `toPcm16`, `Chunker` and `toBase64`.

## Styling

`transcriber.css` is the default look, driven by the shared `--chanx-*` variables. The
components render class names and `data-state`, `data-done` and `data-speaking`
attributes only.
