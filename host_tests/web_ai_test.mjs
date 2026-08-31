import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  AiPatternController,
  AiPatternError,
  PatternAckGate,
  patternToMasks,
  requestGeneratedPattern,
  validatePattern,
} from '../main/web/ai-pattern.js';

const pattern = {
  schemaVersion: 'easyinput.pattern.v1',
  name: 'Test Groove',
  style: 'Rock',
  bpm: 120,
  tracks: {
    kick: [1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0],
    snare: [0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0],
    closed_hat: [1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0],
    open_hat: Array(16).fill(0),
    clap: Array(16).fill(0),
    rim: Array(16).fill(0),
  },
  designNote: 'Test-only response.',
};

const indexHtml = readFileSync(new URL('../main/web/index.html', import.meta.url), 'utf8');
const appSource = readFileSync(new URL('../main/web/app.js', import.meta.url), 'utf8');
assert.doesNotMatch(indexHtml, /id="aiPreviewGrid"/, 'AI must not render a second sequencer');
assert.doesNotMatch(indexHtml, /id="demoPattern"/, 'AI input replaces the fixed demo pattern');
assert.match(indexHtml, /id="applyAiPattern"[^>]*>应用到音序器<\/button>/);
assert.match(
  indexHtml,
  /id="aiResult"[^>]*hidden[\s\S]*id="applyAiPattern"/,
  'Apply must only appear inside the generated candidate module',
);
const aiActionsStart = indexHtml.indexOf('<div class="ai-actions">');
const aiActionsMarkup = indexHtml.slice(
  aiActionsStart,
  indexHtml.indexOf('</div>', aiActionsStart) + '</div>'.length,
);
assert.doesNotMatch(
  aiActionsMarkup,
  /id="applyAiPattern"/,
  'Apply must not remain beside the prompt controls',
);
assert.match(
  appSource,
  /if \(snapshot\.phase === 'generating'\) \{[\s\S]*?aiResult\.hidden = true;/,
  'A new generation must hide the previous candidate until the next candidate is ready',
);
const applyCandidateSource = appSource.slice(
  appSource.indexOf('async function applyCandidate('),
  appSource.indexOf('async function togglePlayback('),
);
assert.match(applyCandidateSource, /pattern = masks;/, 'Apply must fill the existing editor');
assert.doesNotMatch(applyCandidateSource, /TOGGLE/, 'Apply must not start playback');
const togglePlaybackSource = appSource.slice(
  appSource.indexOf('async function togglePlayback('),
  appSource.indexOf('function renderAiState('),
);
assert.match(togglePlaybackSource, /sendCommand\('TOGGLE'\)/, 'Start remains transport-owned');

const payload = {
  ok: true,
  model: { requested: 'deepseek-v4-flash', thinkingMode: 'disabled' },
  latencyMs: { total: 120 },
  firstPass: { valid: true, errors: [] },
  repairAttempted: false,
  pattern,
  masks: [0x1111, 0x1010, 0x5555, 0, 0, 0],
};

function response(body, ok = true) {
  return { ok, json: async () => body };
}

assert.deepEqual(validatePattern(pattern), []);
assert.deepEqual(patternToMasks(pattern), payload.masks);

const badPattern = structuredClone(pattern);
badPattern.tracks.kick = Array(15).fill(0);
assert.match(validatePattern(badPattern).join(' '), /16/);

let applied = false;
const states = [];
const controller = new AiPatternController({
  fetchImpl: async () => response(payload),
  onState: (state) => states.push(state.phase),
});
await controller.generate('生成一个摇滚鼓点');
assert.equal(controller.phase, 'ready');
assert.equal(applied, false, 'generation must never auto-apply to hardware');

let releaseApply;
const applyBarrier = new Promise((resolve) => { releaseApply = resolve; });
const applyPromise = controller.apply(async (candidate) => {
  assert.equal(candidate, pattern);
  applied = true;
  await applyBarrier;
});
await Promise.resolve();
assert.equal(controller.phase, 'applying');
releaseApply();
await applyPromise;
assert.equal(controller.phase, 'applied');
assert.equal(applied, true);
assert.ok(states.includes('ready'));
assert.ok(states.includes('applying'));
assert.ok(states.includes('applied'));

const mismatched = structuredClone(payload);
mismatched.masks[0] = 0;
await assert.rejects(
  requestGeneratedPattern(async () => response(mismatched), 'test'),
  (error) => error instanceof AiPatternError && error.type === 'validation_error',
);

await assert.rejects(
  requestGeneratedPattern(
    async () => response(
      { ok: false, error: { type: 'configuration_error', message: '未配置。' } },
      false,
    ),
    'test',
  ),
  (error) => error.type === 'configuration_error' && error.message === '未配置。',
);

const ackGate = new PatternAckGate();
let ackResolved = false;
const ackPromise = ackGate.wait(1000).then(() => { ackResolved = true; });
await Promise.resolve();
assert.equal(ackResolved, false, 'application success must wait for PATTERN ACK');
assert.equal(ackGate.acknowledge(), true);
await ackPromise;
assert.equal(ackResolved, true);

const rejectedGate = new PatternAckGate();
const rejectedAck = rejectedGate.wait(1000);
rejectedGate.reject(new AiPatternError('protocol_error', 'Unknown command'));
await assert.rejects(rejectedAck, (error) => error.type === 'protocol_error');

const timeoutGate = new PatternAckGate();
await assert.rejects(timeoutGate.wait(1), (error) => error.type === 'protocol_timeout');

console.log('web AI state, validation, and mask tests passed');
