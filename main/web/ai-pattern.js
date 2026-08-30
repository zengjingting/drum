export const TRACK_IDS = Object.freeze([
  'kick',
  'snare',
  'closed_hat',
  'open_hat',
  'clap',
  'rim',
]);

export class AiPatternError extends Error {
  constructor(type, message) {
    super(message);
    this.name = 'AiPatternError';
    this.type = type;
  }
}

export class PatternAckGate {
  constructor() {
    this.pending = null;
  }

  get hasPending() {
    return this.pending !== null;
  }

  wait(timeoutMs = 3500, matcher = null) {
    if (this.pending) {
      return Promise.reject(new AiPatternError('protocol_busy', '已有 Pattern COMMIT 正在等待硬件确认。'));
    }
    return new Promise((resolve, reject) => {
      const transaction = {
        matcher,
        resolve: (message) => {
          clearTimeout(transaction.timeout);
          this.pending = null;
          resolve(message);
        },
        reject: (error) => {
          clearTimeout(transaction.timeout);
          this.pending = null;
          reject(error);
        },
        timeout: null,
      };
      transaction.timeout = setTimeout(() => {
        if (this.pending === transaction) {
          transaction.reject(
            new AiPatternError('protocol_timeout', '硬件未在规定时间内确认 COMMIT。'),
          );
        }
      }, timeoutMs);
      this.pending = transaction;
    });
  }

  acknowledge(message) {
    if (!this.pending) return false;
    if (this.pending.matcher && !this.pending.matcher(message)) return false;
    this.pending.resolve(message);
    return true;
  }

  reject(error) {
    if (!this.pending) return false;
    this.pending.reject(error);
    return true;
  }
}

export function validatePattern(pattern) {
  const errors = [];
  if (!pattern || typeof pattern !== 'object' || Array.isArray(pattern)) {
    return ['Pattern 必须是对象。'];
  }
  const allowed = new Set(['schemaVersion', 'name', 'style', 'bpm', 'tracks', 'designNote']);
  const required = ['schemaVersion', 'name', 'style', 'bpm', 'tracks'];
  for (const field of required) {
    if (!(field in pattern)) errors.push(`缺少字段 ${field}。`);
  }
  for (const field of Object.keys(pattern)) {
    if (!allowed.has(field)) errors.push(`不支持字段 ${field}。`);
  }
  if (pattern.schemaVersion !== 'easyinput.pattern.v1') {
    errors.push('schemaVersion 不匹配。');
  }
  if (typeof pattern.name !== 'string' || pattern.name.length < 1 || pattern.name.length > 80) {
    errors.push('name 必须是 1–80 个字符。');
  }
  if (typeof pattern.style !== 'string' || pattern.style.length < 1 || pattern.style.length > 40) {
    errors.push('style 必须是 1–40 个字符。');
  }
  if (!Number.isInteger(pattern.bpm) || pattern.bpm < 40 || pattern.bpm > 240) {
    errors.push('BPM 必须是 40–240 的整数。');
  }
  if (!pattern.tracks || typeof pattern.tracks !== 'object' || Array.isArray(pattern.tracks)) {
    errors.push('tracks 必须是对象。');
    return errors;
  }
  const actualTrackIds = Object.keys(pattern.tracks).sort();
  const expectedTrackIds = [...TRACK_IDS].sort();
  if (actualTrackIds.join('|') !== expectedTrackIds.join('|')) {
    errors.push('tracks 必须且只能包含六条固定轨道。');
  }
  let triggerCount = 0;
  for (const trackId of TRACK_IDS) {
    const track = pattern.tracks[trackId];
    if (!Array.isArray(track) || track.length !== 16) {
      errors.push(`${trackId} 必须包含 16 步。`);
      continue;
    }
    track.forEach((value, index) => {
      if (!Number.isInteger(value) || (value !== 0 && value !== 1)) {
        errors.push(`${trackId} 第 ${index + 1} 步必须是整数 0 或 1。`);
      } else {
        triggerCount += value;
      }
    });
  }
  if (triggerCount === 0) errors.push('Pattern 不能全为空。');
  if (
    pattern.designNote !== undefined
    && (typeof pattern.designNote !== 'string' || pattern.designNote.length > 300)
  ) {
    errors.push('designNote 必须是不超过 300 个字符的文本。');
  }
  return errors;
}

export function patternToMasks(pattern) {
  const errors = validatePattern(pattern);
  if (errors.length) throw new AiPatternError('validation_error', errors.join(' '));
  return TRACK_IDS.map((trackId) => pattern.tracks[trackId].reduce(
    (mask, value, index) => mask | (value << index),
    0,
  ));
}

export async function requestGeneratedPattern(fetchImpl, prompt) {
  let response;
  try {
    response = await fetchImpl('/api/pattern/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt }),
    });
  } catch (_) {
    throw new AiPatternError('network_error', '无法连接本地 AI 服务，请确认 pnpm dev 正在运行。');
  }

  let payload;
  try {
    payload = await response.json();
  } catch (_) {
    throw new AiPatternError('server_error', '本地 AI 服务返回了无法解析的响应。');
  }
  if (!response.ok || payload.ok !== true) {
    const type = payload?.error?.type || 'server_error';
    const message = payload?.error?.message || 'AI 生成失败，请稍后重试。';
    throw new AiPatternError(type, message);
  }

  const errors = validatePattern(payload.pattern);
  if (errors.length) {
    throw new AiPatternError('validation_error', `网页复核失败：${errors.join(' ')}`);
  }
  const computedMasks = patternToMasks(payload.pattern);
  if (
    !Array.isArray(payload.masks)
    || payload.masks.length !== 6
    || payload.masks.some((value, index) => value !== computedMasks[index])
  ) {
    throw new AiPatternError('validation_error', '服务端 Mask 与网页复算结果不一致。');
  }
  return payload;
}

export class AiPatternController {
  constructor({ fetchImpl, onState = () => {} }) {
    this.fetchImpl = fetchImpl;
    this.onState = onState;
    this.phase = 'idle';
    this.candidate = null;
    this.metadata = null;
    this.error = null;
    this._emit();
  }

  snapshot() {
    return {
      phase: this.phase,
      candidate: this.candidate,
      metadata: this.metadata,
      error: this.error,
    };
  }

  async generate(prompt) {
    const normalized = String(prompt || '').trim();
    if (!normalized) throw new AiPatternError('request_error', '请输入鼓点描述。');
    if (this.phase === 'generating' || this.phase === 'applying') {
      throw new AiPatternError('busy', '当前操作尚未完成。');
    }
    this.phase = 'generating';
    this.candidate = null;
    this.metadata = null;
    this.error = null;
    this._emit();
    try {
      const payload = await requestGeneratedPattern(this.fetchImpl, normalized);
      this.phase = 'ready';
      this.candidate = payload.pattern;
      this.metadata = {
        model: payload.model,
        latencyMs: payload.latencyMs,
        firstPass: payload.firstPass,
        repairAttempted: payload.repairAttempted,
      };
      this._emit();
      return this.candidate;
    } catch (error) {
      const normalizedError = error instanceof AiPatternError
        ? error
        : new AiPatternError('client_error', '网页处理 AI 结果时发生错误。');
      this.phase = 'error';
      this.error = normalizedError;
      this._emit();
      throw normalizedError;
    }
  }

  async apply(applyFn) {
    if (!this.candidate) throw new AiPatternError('no_candidate', '请先生成一个鼓点。');
    if (this.phase === 'generating' || this.phase === 'applying') {
      throw new AiPatternError('busy', '当前操作尚未完成。');
    }
    this.phase = 'applying';
    this.error = null;
    this._emit();
    try {
      await applyFn(this.candidate);
      this.phase = 'applied';
      this._emit();
    } catch (error) {
      const normalizedError = error instanceof AiPatternError
        ? error
        : new AiPatternError('hardware_error', error?.message || '应用到硬件失败。');
      this.phase = 'apply_error';
      this.error = normalizedError;
      this._emit();
      throw normalizedError;
    }
  }

  _emit() {
    this.onState(this.snapshot());
  }
}
