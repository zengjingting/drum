import { TRACK_IDS } from './ai-pattern.js';
import { masksToTracks } from './pad-recording.js';

export class PatternExplanationError extends Error {
  constructor(type, message) {
    super(message);
    this.name = 'PatternExplanationError';
    this.type = type;
  }
}

export function buildExplanationPattern(masks, bpm, approximateQuantization = false) {
  if (!Number.isInteger(bpm) || bpm < 40 || bpm > 240) {
    throw new PatternExplanationError('validation_error', 'BPM 必须是 40–240 的整数。');
  }
  const trackArrays = masksToTracks(masks);
  const tracks = Object.fromEntries(
    TRACK_IDS.map((trackId, index) => [trackId, trackArrays[index]]),
  );
  if (trackArrays.every((track) => track.every((value) => value === 0))) {
    throw new PatternExplanationError('validation_error', '空 Pattern 无法进行 AI 解释。');
  }
  if (typeof approximateQuantization !== 'boolean') {
    throw new PatternExplanationError('validation_error', '量化来源标记必须是布尔值。');
  }
  return { bpm, tracks, approximateQuantization };
}

export function patternFingerprint(masks, bpm) {
  return `${bpm}:${masks.map((mask) => Number(mask) & 0xffff).join(',')}`;
}

export function validateExplanation(explanation, pattern) {
  const errors = [];
  if (!explanation || typeof explanation !== 'object' || Array.isArray(explanation)) {
    return ['解释必须是对象。'];
  }
  const required = [
    'schemaVersion',
    'summary',
    'styleCandidates',
    'evidence',
    'suggestion',
    'limitations',
  ];
  if (Object.keys(explanation).sort().join('|') !== [...required].sort().join('|')) {
    errors.push('解释字段集合不匹配。');
  }
  if (explanation.schemaVersion !== 'easyinput.pattern.explanation.v1') {
    errors.push('解释 Schema 版本不匹配。');
  }
  for (const [field, limit] of [['summary', 300], ['suggestion', 300], ['limitations', 300]]) {
    const value = explanation[field];
    if (typeof value !== 'string' || !value.trim() || value.length > limit) {
      errors.push(`${field} 文本不合法。`);
    }
  }
  if (!Array.isArray(explanation.styleCandidates) || explanation.styleCandidates.length < 1 || explanation.styleCandidates.length > 3) {
    errors.push('风格候选必须为 1–3 个。');
  } else {
    explanation.styleCandidates.forEach((candidate, index) => {
      if (
        !candidate
        || Object.keys(candidate).sort().join('|') !== 'confidence|style'
        || typeof candidate.style !== 'string'
        || !candidate.style.trim()
        || candidate.style.length > 40
        || !['high', 'medium', 'low'].includes(candidate.confidence)
      ) {
        errors.push(`第 ${index + 1} 个风格候选不合法。`);
      }
    });
  }
  if (!Array.isArray(explanation.evidence) || explanation.evidence.length < 1 || explanation.evidence.length > 6) {
    errors.push('判断依据必须为 1–6 条。');
  } else {
    explanation.evidence.forEach((item, index) => {
      if (!item || Object.keys(item).sort().join('|') !== 'reason|steps|track') {
        errors.push(`第 ${index + 1} 条依据字段不合法。`);
        return;
      }
      if (!TRACK_IDS.includes(item.track)) {
        errors.push(`第 ${index + 1} 条依据音轨不合法。`);
        return;
      }
      if (
        !Array.isArray(item.steps)
        || item.steps.length < 1
        || item.steps.length > 16
        || new Set(item.steps).size !== item.steps.length
        || item.steps.some((step) => !Number.isInteger(step) || step < 1 || step > 16)
      ) {
        errors.push(`第 ${index + 1} 条依据步数不合法。`);
      } else if (item.steps.some((step) => pattern.tracks[item.track][step - 1] !== 1)) {
        errors.push(`第 ${index + 1} 条依据引用了未触发音序格。`);
      }
      if (typeof item.reason !== 'string' || !item.reason.trim() || item.reason.length > 240) {
        errors.push(`第 ${index + 1} 条依据说明不合法。`);
      }
    });
  }
  return errors;
}

export async function requestPatternExplanation(
  fetchImpl,
  masks,
  bpm,
  approximateQuantization = false,
) {
  const pattern = buildExplanationPattern(masks, bpm, approximateQuantization);
  let response;
  try {
    response = await fetchImpl('/api/pattern/explain', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pattern }),
    });
  } catch (_) {
    throw new PatternExplanationError(
      'network_error',
      '无法连接本地 AI 服务；当前 Pattern 仍可编辑和播放。',
    );
  }
  let payload;
  try {
    payload = await response.json();
  } catch (_) {
    throw new PatternExplanationError('server_error', '本地 AI 服务返回了无法解析的响应。');
  }
  if (!response.ok || payload.ok !== true) {
    throw new PatternExplanationError(
      payload?.error?.type || 'server_error',
      payload?.error?.message || 'AI 解释失败，请稍后重试。',
    );
  }
  const errors = validateExplanation(payload.explanation, pattern);
  if (errors.length) {
    throw new PatternExplanationError('validation_error', `网页复核失败：${errors.join(' ')}`);
  }
  return { ...payload, pattern };
}
