import assert from 'node:assert/strict';
import {
  PatternExplanationError,
  buildExplanationPattern,
  patternFingerprint,
  requestPatternExplanation,
  validateExplanation,
} from '../main/web/pattern-explanation.js';

const masks = [0x1111, 0x1010, 0x5555, 0, 0, 0];
const pattern = buildExplanationPattern(masks, 120, true);
const explanation = {
  schemaVersion: 'easyinput.pattern.explanation.v1',
  summary: '这个 Pattern 更接近基础 Rock。',
  styleCandidates: [{ style: 'Rock', confidence: 'high' }],
  evidence: [
    { track: 'snare', steps: [5, 13], reason: '军鼓形成第二、第四拍反拍。' },
  ],
  suggestion: '移动一个底鼓落点，比较切分感。',
  limitations: '只依据单小节鼓点，不能判断完整歌曲流派。',
};

assert.deepEqual(validateExplanation(explanation, pattern), []);
assert.equal(pattern.tracks.kick[0], 1);
assert.equal(pattern.tracks.snare[4], 1);
assert.equal(patternFingerprint(masks, 120), '120:4369,4112,21845,0,0,0');
assert.throws(
  () => buildExplanationPattern([0, 0, 0, 0, 0, 0], 120),
  (error) => error instanceof PatternExplanationError && error.type === 'validation_error',
);

const badEvidence = structuredClone(explanation);
badEvidence.evidence[0].steps = [2];
assert.match(validateExplanation(badEvidence, pattern).join(' '), /未触发/);

const payload = {
  ok: true,
  model: { requested: 'deepseek-v4-flash', thinkingMode: 'disabled' },
  latencyMs: { total: 300 },
  firstPass: { valid: true, errors: [] },
  repairAttempted: false,
  features: {},
  explanation,
};
const result = await requestPatternExplanation(
  async () => ({ ok: true, json: async () => payload }),
  masks,
  120,
  true,
);
assert.equal(result.explanation.styleCandidates[0].style, 'Rock');

await assert.rejects(
  requestPatternExplanation(
    async () => ({
      ok: false,
      json: async () => ({ ok: false, error: { type: 'model_error', message: '模型失败。' } }),
    }),
    masks,
    120,
    true,
  ),
  (error) => error.type === 'model_error' && error.message === '模型失败。',
);

console.log('pattern explanation schema and request tests passed');
