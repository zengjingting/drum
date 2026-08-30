import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  PadRecordingError,
  RecordingBoundaryGate,
  masksToTracks,
  parseSavedPattern,
  quantizePadEvents,
  serializeSavedPattern,
  verifyRecording,
} from '../main/web/pad-recording.js';

const indexHtml = readFileSync(new URL('../main/web/index.html', import.meta.url), 'utf8');
const appSource = readFileSync(new URL('../main/web/app.js', import.meta.url), 'utf8');
assert.match(indexHtml, /id="recordPattern"[^>]*>开始录制<\/button>/);
assert.match(indexHtml, /id="savePattern"[^>]*>保存<\/button>/);
assert.match(indexHtml, /id="explainPattern"[^>]*>AI 解释<\/button>/);
assert.match(appSource, /capabilities\.has\('padEvents'\)/);
assert.match(appSource, /sendCommand\('RECORD START'/);
assert.match(appSource, /sendCommand\('RECORD STOP'/);
assert.match(appSource, /\/api\/debug\/recording-trace/);
for (const stage of [
  'record_start_requested',
  'pad_received',
  'pattern_quantized',
  'pattern_sync_sent',
  'pattern_ack_received',
  'playback_toggle_requested',
  'device_state',
]) {
  assert.match(appSource, new RegExp(stage), `recording trace must include ${stage}`);
}
assert.match(
  appSource,
  /quantizePadEvents\(\s*verified\.events,\s*desiredBpm,\s*\)/,
  'page quantization must use the current BPM instead of start/stop click duration',
);
const padHandler = appSource.slice(
  appSource.indexOf("if (message.type === 'pad')"),
  appSource.indexOf("if (message.type === 'record')"),
);
assert.doesNotMatch(padHandler, /setPattern|renderPattern/, 'recording must not update steps live');

const start = { phase: 'started', frame: 1000, lastEvent: 20, dropped: 0 };
const stop = { phase: 'stopped', frame: 169000, lastEvent: 24, dropped: 0 };
const events = [
  { type: 'pad', event: 21, track: 0, frame: 49000, source: 'hardware' },
  { type: 'pad', event: 22, track: 1, frame: 73000, source: 'hardware' },
  { type: 'pad', event: 23, track: 0, frame: 97000, source: 'hardware' },
  { type: 'pad', event: 24, track: 1, frame: 121000, source: 'hardware' },
];

const verified = verifyRecording(events, start, stop);
assert.equal(verified.events.length, 4);
const quantized = quantizePadEvents(verified.events, 120);
assert.deepEqual(quantized.masks, [0x0101, 0x1010, 0, 0, 0, 0]);
assert.equal(quantized.acceptedCount, 4);
assert.equal(quantized.anchorFrame, 49000, 'the first physical hit anchors step 1');
assert.equal(quantized.ignoredCount, 0);
assert.deepEqual(
  quantized.assignments.map(({ track, step, accepted }) => ({ track, step, accepted })),
  [
    { track: 0, step: 1, accepted: true },
    { track: 1, step: 5, accepted: true },
    { track: 0, step: 9, accepted: true },
    { track: 1, step: 13, accepted: true },
  ],
  'diagnostics must retain the exact event-to-step mapping',
);

const simultaneous = quantizePadEvents([
  { event: 1, track: 0, frame: 150, source: 'hardware' },
  { event: 2, track: 1, frame: 150, source: 'hardware' },
  { event: 3, track: 0, frame: 151, source: 'hardware' },
], 120);
assert.equal(simultaneous.masks[0], 1, 'same-track hits in one step merge');
assert.equal(simultaneous.masks[1], 1, 'different tracks may share a step');

const oneBarOnly = quantizePadEvents([
  { event: 1, track: 0, frame: 1000, source: 'hardware' },
  { event: 2, track: 0, frame: 97000, source: 'hardware' },
], 120);
assert.equal(oneBarOnly.masks[0], 1, 'an event at the next bar must not collapse into step 16');
assert.equal(oneBarOnly.acceptedCount, 1);
assert.equal(oneBarOnly.ignoredCount, 1);

const ninetyBpm = quantizePadEvents([
  { event: 1, track: 0, frame: 1000, source: 'hardware' },
  { event: 2, track: 0, frame: 33000, source: 'hardware' },
  { event: 3, track: 0, frame: 65000, source: 'hardware' },
  { event: 4, track: 0, frame: 97000, source: 'hardware' },
], 90);
assert.equal(ninetyBpm.masks[0], 0x1111, '90 BPM quarter notes map to steps 1, 5, 9, 13');

assert.throws(
  () => verifyRecording(events.slice(0, 3), start, stop),
  (error) => error instanceof PadRecordingError && error.type === 'event_loss',
);
assert.throws(
  () => verifyRecording(events, start, { ...stop, dropped: 1 }),
  (error) => error.type === 'event_loss',
);
assert.deepEqual(quantizePadEvents([], 120).masks, [0, 0, 0, 0, 0, 0]);
assert.throws(() => quantizePadEvents(events, 20), (error) => error.type === 'quantization_error');

const tracks = masksToTracks([0x8001, 0, 0, 0, 0, 0]);
assert.equal(tracks[0][0], 1);
assert.equal(tracks[0][15], 1);

const saved = serializeSavedPattern({
  name: '录制测试',
  bpm: 120,
  masks: quantized.masks,
  approximateQuantization: true,
  savedAt: '2026-08-30T00:00:00.000Z',
});
assert.deepEqual(parseSavedPattern(saved).masks, quantized.masks);
assert.equal(parseSavedPattern(saved).approximateQuantization, true);
assert.throws(() => parseSavedPattern('{bad'), (error) => error.type === 'storage_error');

const gate = new RecordingBoundaryGate();
const started = gate.wait('started', 1000);
assert.equal(gate.resolve({ type: 'record', ...start }), true);
assert.equal((await started).frame, 1000);
const stopped = gate.wait('stopped', 1000);
assert.equal(gate.resolve({ type: 'record', ...stop }), true);
assert.equal((await stopped).lastEvent, 24);
const invalidGate = new RecordingBoundaryGate();
const invalidBoundary = invalidGate.wait('started', 1000);
assert.equal(invalidGate.resolve({ type: 'record', phase: 'started', frame: -1 }), true);
await assert.rejects(invalidBoundary, (error) => error.type === 'protocol_error');

console.log('pad recording, quantization, and local save tests passed');
