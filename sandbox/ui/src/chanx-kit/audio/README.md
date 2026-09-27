# Audio helpers

The pure functions the voice UI kits share. Installed with them; useful on their own
when you handle PCM audio in the browser.

```bash
copit add @chanx-kit-ui/audio
```

| Export | |
|---|---|
| `Resampler` | linear-interpolation resampler that keeps its position across blocks |
| `toPcm16`, `fromPcm16` | float samples to little-endian PCM16 bytes and back (downmixing) |
| `Chunker` | collects bytes into chunks of a fixed duration |
| `level` | RMS of a block, for meters |
| `toBase64`, `fromBase64` | standard base64, using the native `Uint8Array` methods when present |
