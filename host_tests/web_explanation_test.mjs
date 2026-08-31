import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  PatternExplanationError,
  buildExplanationPattern,
  patternFingerprint,
  requestPatternExplanation,
  validateExplanation,
} from '../main/web/pattern-explanation.js';

const indexHtml = readFileSync(new URL('../main/web/index.html', import.meta.url), 'utf8');
const appSource = readFileSync(new URL('../main/web/app.js', import.meta.url), 'utf8');
assert.match(indexHtml, /id="explanationStyle"/);
assert.match(indexHtml, /id="explanationOverview"/);
assert.match(indexHtml, /id="explanationReasons"/);
assert.match(indexHtml, /id="explanationLessonContent"/);
assert.match(indexHtml, /id="explanationSuggestions"/);
assert.doesNotMatch(indexHtml, /explanationLimitations|置信度/);
assert.match(appSource, /AI正在分析你的鼓点/);
assert.doesNotMatch(appSource, /AI 正在分析你的鼓点… 已等待/);
assert.match(appSource, /AI 解释完成，用时/);
assert.match(appSource, /Pattern 和硬件播放不受影响/);
assert.doesNotMatch(appSource, /AI 解释完成 · Pattern v/);
assert.doesNotMatch(indexHtml, /风格小课堂|让鼓点更好听，可以试试/);
assert.match(indexHtml, /id="explanationStyle">Boom Bap/);
assert.match(appSource, /function clearPatternExplanation\(\)/);
assert.match(
  appSource,
  /if \(snapshot\.phase === 'generating'\) \{\s*clearPatternExplanation\(\);/,
  'starting a valid AI generation must remove the previous or sample explanation',
);
assert.match(
  appSource,
  /function clearPatternExplanation\(\)[\s\S]*?explanationPayload = null;[\s\S]*?explanationResult\.hidden = true;/,
  'clearing the explanation must reset its state and hide the rendered result',
);

const masks = [0x1111, 0x1010, 0x5555, 0, 0, 0];
const pattern = buildExplanationPattern(masks, 120, true);
const explanation = {
  schemaVersion: 'easyinput.pattern.explanation.v3',
  closestStyle: 'Rock',
  styleOverview: 'Rock 起源于二十世纪中期的美国流行文化，常见于摇滚歌曲和现场乐队。',
  reasons: [
    { track: 'snare', steps: [5, 13], reason: '军鼓形成第二、第四拍反拍。' },
  ],
  styleLesson: {
    title: 'Rock 鼓点通常怎么编排？',
    content: 'Rock 常用底鼓支撑强拍，军鼓强调第二和第四拍，并用踩镲维持稳定细分。',
  },
  improvementSuggestions: [{
    suggestion: '移动一个底鼓落点，比较切分感。',
    expectedEffect: '节奏会产生更明显的推动感。',
    learningPoint: '练习比较强拍和非强拍底鼓的听感。',
  }],
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
badEvidence.reasons[0].steps = [2];
assert.match(validateExplanation(badEvidence, pattern).join(' '), /未触发/);

const oldExplanation = {
  ...structuredClone(explanation),
  schemaVersion: 'easyinput.pattern.explanation.v2',
};
delete oldExplanation.styleOverview;
assert.match(validateExplanation(oldExplanation, pattern).join(' '), /字段集合|版本/);

const englishLesson = structuredClone(explanation);
englishLesson.styleLesson.content = 'Kick and snare form the groove.';
assert.match(validateExplanation(englishLesson, pattern).join(' '), /小课堂/);

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
assert.equal(result.explanation.closestStyle, 'Rock');

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
