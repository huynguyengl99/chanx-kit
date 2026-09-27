#!/usr/bin/env node
// Drive the sandbox's voice panels in a real browser with Chrome's fake microphone.
//
//   npm run --prefix sandbox/ui build && uv run python -m sandbox --port 8000 &
//   PLAYWRIGHT=/path/to/node_modules/playwright/index.mjs node scripts/sandbox_voice_e2e.mjs http://127.0.0.1:8000
//
// The fake microphone plays a generated WAV (see speechWav). Needs full Chromium (not the headless shell, whose fake device takes seconds to open)
// and the microphone permission granted on the context; the fake-UI flag alone is
// ignored headless.

import { writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const base = process.argv[2] ?? 'http://127.0.0.1:8000';
const { chromium } = await import(process.env.PLAYWRIGHT ?? 'playwright');

// Never hang: a stuck page fails the run instead.
setTimeout(() => {
  console.error('timed out');
  process.exit(2);
}, 120_000).unref();

/** The fake microphone: 1.5 s of tone, then 1.5 s of silence, looped by Chrome on its
 * own clock. Each 5 s recording window below therefore holds a whole utterance and the
 * pause that ends it, wherever the loop happens to be. Chrome's default beep would start
 * and end an utterance every second. */
function speechWav(path) {
  const rate = 48000;
  const samples = rate * 3;
  const data = Buffer.alloc(samples * 2);
  for (let i = 0; i < rate * 1.5; i++) {
    data.writeInt16LE(Math.round(6000 * Math.sin((2 * Math.PI * 220 * i) / rate)), i * 2);
  }
  const header = Buffer.alloc(44);
  header.write('RIFF', 0);
  header.writeUInt32LE(36 + data.length, 4);
  header.write('WAVEfmt ', 8);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20); // PCM
  header.writeUInt16LE(1, 22); // mono
  header.writeUInt32LE(rate, 24);
  header.writeUInt32LE(rate * 2, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write('data', 36);
  header.writeUInt32LE(data.length, 40);
  writeFileSync(path, Buffer.concat([header, data]));
  return path;
}

// With real providers, pass recorded speech followed by about 1.5 s of silence, and a word
// it contains:
//   MIC_WAV=speech.wav EXPECT=weather node scripts/sandbox_voice_e2e.mjs ...
const wav = process.env.MIC_WAV ?? speechWav(join(tmpdir(), 'chanx-kit-speech.wav'));
const expected = process.env.EXPECT ?? 'hello world';
const browser = await chromium.launch({
  channel: 'chromium',
  args: [
    '--use-fake-device-for-media-stream',
    '--use-fake-ui-for-media-stream',
    `--use-file-for-fake-audio-capture=${wav}`,
  ],
});
const context = await browser.newContext({ permissions: ['microphone'] });
const page = await context.newPage();
const errors = [];
page.on('pageerror', (error) => errors.push(String(error)));
const frames = [];
page.on('websocket', (socket) => {
  socket.on('framesent', (frame) => {
    try {
      frames.push({ dir: 'out', ...JSON.parse(frame.payload) });
    } catch {}
  });
  socket.on('framereceived', (frame) => {
    try {
      frames.push({ dir: 'in', ...JSON.parse(frame.payload) });
    } catch {}
  });
});

const results = {};
const check = (name, ok, detail) => {
  results[name] = ok ? 'ok' : `FAILED ${JSON.stringify(detail)}`;
};

await page.goto(base);

// 1. Speech to text: audio goes up in order and a transcript comes back.
{
  const panel = page.locator('section.panel', { hasText: 'speech to text' });
  await panel.locator('.status', { hasText: 'open' }).waitFor({ timeout: 10000 });
  await panel.getByRole('button', { name: 'Start recording' }).click();
  await page.waitForTimeout(5000);
  await panel.getByRole('button', { name: 'Stop recording' }).click();
  // A real provider finalizes after audio_end, and may split the speech into several
  // turns: wait for the expected word, not the first line.
  for (let waited = 0; waited < 8000; waited += 250) {
    const shown = await panel.locator('.chanx-transcript__utterance').allInnerTexts();
    if (shown.join(' ').toLowerCase().includes(expected)) break;
    await page.waitForTimeout(250);
  }
  const chunks = frames.filter((f) => f.dir === 'out' && f.action === 'audio_chunk' && f.topic?.startsWith('transcribe:'));
  const text = await panel.locator('.chanx-transcript__utterance').allInnerTexts();
  check('transcriber: chunks numbered in order', chunks.length > 10 && chunks.every((c, i) => c.payload.index === i), chunks.length);
  const heard = frames
    .filter((f) => f.dir === 'in' && f.topic?.startsWith('transcribe:'))
    .map((f) => f.action + (f.payload?.text ? `:${f.payload.text}` : f.payload?.code ? `:${f.payload.code}:${f.payload.message}` : ''));
  check('transcriber: transcript shown', text.join(' ').toLowerCase().includes(expected), { text, heard });
}

// 2. Text to speech: audio arrives and playback marks go back.
{
  const panel = page.locator('section.panel', { hasText: 'text to speech' });
  await panel.getByRole('button', { name: 'Speak' }).click();
  await page.waitForTimeout(4000);
  const audio = frames.filter((f) => f.dir === 'in' && f.action === 'audio_chunk' && f.topic?.startsWith('speak:'));
  const marks = frames.filter((f) => f.dir === 'out' && f.action === 'playback_mark');
  check('player: audio received', audio.length > 0, audio.length);
  check('player: playback marks sent', marks.length > 0 && marks.at(-1).payload.played_ms > 0, marks.at(-1));
}

// 3. Voice agent: a spoken turn is answered out loud.
{
  const agent = page.locator('.chanx-voice-agent');
  await agent.getByRole('button', { name: 'Start talking' }).click();
  await page.waitForTimeout(5000);
  await agent.getByRole('button', { name: 'Mute' }).click();
  await page.waitForTimeout(5000);
  const runs = frames.filter((f) => f.dir === 'in' && f.action === 'ag_ui_event' && f.payload.type === 'RUN_STARTED');
  const spoken = frames.filter((f) => f.dir === 'in' && f.action === 'audio_start' && f.payload.text);
  check('voice agent: a run started from speech', runs.length > 0, runs.length);
  check('voice agent: the reply was spoken', spoken.length > 0, spoken.length);
}

check('no page errors', errors.length === 0, errors);
console.log(JSON.stringify(results, null, 2));
await browser.close();
process.exit(Object.values(results).every((value) => value === 'ok') ? 0 : 1);
