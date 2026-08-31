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
  const containsChinese = (value) => /[\u3400-\u4dbf\u4e00-\u9fff]/u.test(value);
  if (!explanation || typeof explanation !== 'object' || Array.isArray(explanation)) {
    return ['解释必须是对象。'];
  }
  const required = [
    'schemaVersion',
    'closestStyle',
    'reasons',
    'styleLesson',
    'improvementSuggestions',
  ];
  if (Object.keys(explanation).sort().join('|') !== [...required].sort().join('|')) {
    errors.push('解释字段集合不匹配。');
  }
  if (explanation.schemaVersion !== 'easyinput.pattern.explanation.v2') {
    errors.push('解释 Schema 版本不匹配。');
  }
  if (
    typeof explanation.closestStyle !== 'string'
    || !explanation.closestStyle.trim()
    || explanation.closestStyle.length > 40
  ) {
    errors.push('最接近风格不合法。');
  }

  if (!Array.isArray(explanation.reasons) || explanation.reasons.length < 1 || explanation.reasons.length > 6) {
    errors.push('判断原因必须为 1–6 条。');
  } else {
    explanation.reasons.forEach((item, index) => {
      if (!item || Object.keys(item).sort().join('|') !== 'reason|steps|track') {
        errors.push(`第 ${index + 1} 条判断原因字段不合法。`);
        return;
      }
      if (!TRACK_IDS.includes(item.track)) {
        errors.push(`第 ${index + 1} 条判断原因音轨不合法。`);
        return;
      }
      if (
        !Array.isArray(item.steps)
        || item.steps.length < 1
        || item.steps.length > 16
        || new Set(item.steps).size !== item.steps.length
        || item.steps.some((step) => !Number.isInteger(step) || step < 1 || step > 16)
      ) {
        errors.push(`第 ${index + 1} 条判断原因步数不合法。`);
      } else if (item.steps.some((step) => pattern.tracks[item.track][step - 1] !== 1)) {
        errors.push(`第 ${index + 1} 条判断原因引用了未触发音序格。`);
      }
      if (
        typeof item.reason !== 'string'
        || !item.reason.trim()
        || item.reason.length > 240
        || !containsChinese(item.reason)
      ) {
        errors.push(`第 ${index + 1} 条判断原因说明不合法。`);
      }
    });
  }

  const lesson = explanation.styleLesson;
  if (!lesson || Object.keys(lesson).sort().join('|') !== 'content|title') {
    errors.push('风格小课堂字段不合法。');
  } else {
    for (const [field, limit] of [['title', 80], ['content', 400]]) {
      const value = lesson[field];
      if (
        typeof value !== 'string'
        || !value.trim()
        || value.length > limit
        || !containsChinese(value)
      ) {
        errors.push(`风格小课堂 ${field} 文本不合法。`);
      }
    }
  }

  const suggestions = explanation.improvementSuggestions;
  if (!Array.isArray(suggestions) || suggestions.length < 1 || suggestions.length > 2) {
    errors.push('改进建议必须为 1–2 条。');
  } else {
    suggestions.forEach((item, index) => {
      if (
        !item
        || Object.keys(item).sort().join('|') !== 'expectedEffect|learningPoint|suggestion'
      ) {
        errors.push(`第 ${index + 1} 条改进建议字段不合法。`);
        return;
      }
      for (const field of ['suggestion', 'expectedEffect', 'learningPoint']) {
        const value = item[field];
        if (
          typeof value !== 'string'
          || !value.trim()
          || value.length > 240
          || !containsChinese(value)
        ) {
          errors.push(`第 ${index + 1} 条改进建议 ${field} 文本不合法。`);
        }
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
