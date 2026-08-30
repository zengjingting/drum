export const RECORDING_STORAGE_KEY = 'easyinput.current-pattern.v1';
export const RECORDING_SAMPLE_RATE_HZ = 48000;

export class PadRecordingError extends Error {
  constructor(type, message) {
    super(message);
    this.name = 'PadRecordingError';
    this.type = type;
  }
}

function isSafeNonNegativeInteger(value) {
  return Number.isSafeInteger(value) && value >= 0;
}

export function validatePadEvent(message) {
  if (!message || typeof message !== 'object' || Array.isArray(message)) {
    throw new PadRecordingError('protocol_error', 'Pad 事件必须是对象。');
  }
  if (!isSafeNonNegativeInteger(message.event) || message.event === 0) {
    throw new PadRecordingError('protocol_error', 'Pad 事件编号不合法。');
  }
  if (!Number.isInteger(message.track) || message.track < 0 || message.track > 5) {
    throw new PadRecordingError('protocol_error', 'Pad 音轨必须是 0–5。');
  }
  if (!isSafeNonNegativeInteger(message.frame)) {
    throw new PadRecordingError('protocol_error', 'Pad 事件缺少有效设备时钟。');
  }
  if (message.source !== 'hardware') {
    throw new PadRecordingError('protocol_error', '录制只接受实体 Pad 事件。');
  }
  return {
    event: message.event,
    track: message.track,
    frame: message.frame,
    source: message.source,
  };
}

export function validateRecordBoundary(message, expectedPhase) {
  if (!message || message.type !== 'record' || message.phase !== expectedPhase) {
    throw new PadRecordingError('protocol_error', `缺少录制 ${expectedPhase} 边界。`);
  }
  for (const field of ['frame', 'lastEvent', 'dropped']) {
    if (!isSafeNonNegativeInteger(message[field])) {
      throw new PadRecordingError('protocol_error', `录制边界字段 ${field} 不合法。`);
    }
  }
  const origin = message.origin || 'web';
  if (!['web', 's8', 'system'].includes(origin)) {
    throw new PadRecordingError('protocol_error', '录制边界 origin 不合法。');
  }
  return {
    phase: message.phase,
    origin,
    frame: message.frame,
    lastEvent: message.lastEvent,
    dropped: message.dropped,
  };
}

export class RecordingBoundaryGate {
  constructor() {
    this.pending = null;
  }

  get hasPending() {
    return this.pending !== null;
  }

  wait(expectedPhase, timeoutMs = 3500) {
    if (this.pending) {
      return Promise.reject(new PadRecordingError('protocol_busy', '已有录制边界正在等待硬件确认。'));
    }
    return new Promise((resolve, reject) => {
      const transaction = {
        expectedPhase,
        resolve: (message) => {
          let boundary;
          try {
            boundary = validateRecordBoundary(message, expectedPhase);
          } catch (error) {
            transaction.reject(error);
            return;
          }
          clearTimeout(transaction.timeout);
          this.pending = null;
          resolve(boundary);
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
          transaction.reject(new PadRecordingError(
            'protocol_timeout',
            expectedPhase === 'started' ? '硬件未确认开始录制。' : '硬件未确认停止录制。',
          ));
        }
      }, timeoutMs);
      this.pending = transaction;
    });
  }

  resolve(message) {
    if (!this.pending || message?.phase !== this.pending.expectedPhase) return false;
    this.pending.resolve(message);
    return true;
  }

  reject(error) {
    if (!this.pending) return false;
    this.pending.reject(error);
    return true;
  }
}

export function verifyRecording(events, startBoundary, stopBoundary) {
  const start = validateRecordBoundary({ type: 'record', ...startBoundary }, 'started');
  const stop = validateRecordBoundary({ type: 'record', ...stopBoundary }, 'stopped');
  if (stop.frame <= start.frame) {
    throw new PadRecordingError('recording_error', '录制时长过短，请重新录制。');
  }
  if (stop.lastEvent < start.lastEvent || stop.dropped < start.dropped) {
    throw new PadRecordingError('protocol_error', '设备录制计数发生回退。');
  }
  if (stop.dropped !== start.dropped) {
    throw new PadRecordingError('event_loss', '录制期间设备事件队列发生溢出，请重新录制。');
  }

  const accepted = events
    .map(validatePadEvent)
    .filter((event) => (
      event.event > start.lastEvent
      && event.event <= stop.lastEvent
      && event.frame >= start.frame
      && event.frame <= stop.frame
    ))
    .sort((left, right) => left.event - right.event);
  const expectedCount = stop.lastEvent - start.lastEvent;
  if (accepted.length !== expectedCount) {
    throw new PadRecordingError(
      'event_loss',
      `录制应收到 ${expectedCount} 次敲击，实际收到 ${accepted.length} 次，请重新录制。`,
    );
  }
  for (let index = 0; index < accepted.length; index += 1) {
    if (accepted[index].event !== start.lastEvent + index + 1) {
      throw new PadRecordingError('event_loss', 'Pad 事件编号不连续，请重新录制。');
    }
  }
  return { events: accepted, start, stop };
}

export function quantizePadEvents(events, bpm, sampleRateHz = RECORDING_SAMPLE_RATE_HZ) {
  if (!Number.isFinite(bpm) || bpm < 40 || bpm > 240) {
    throw new PadRecordingError('quantization_error', '量化 BPM 必须是 40–240。');
  }
  if (!Number.isFinite(sampleRateHz) || sampleRateHz <= 0) {
    throw new PadRecordingError('quantization_error', '量化采样率必须大于零。');
  }
  if (!Array.isArray(events)) {
    throw new PadRecordingError('quantization_error', '录制事件必须是数组。');
  }

  const validatedEvents = events.map(validatePadEvent);
  const masks = [0, 0, 0, 0, 0, 0];
  if (validatedEvents.length === 0) {
    return {
      masks,
      acceptedCount: 0,
      ignoredCount: 0,
      anchorFrame: null,
      framesPerStep: sampleRateHz * 60 / bpm / 4,
      assignments: [],
    };
  }

  const anchorFrame = Math.min(...validatedEvents.map((event) => event.frame));
  const framesPerStep = sampleRateHz * 60 / bpm / 4;
  let acceptedCount = 0;
  let ignoredCount = 0;
  const assignments = [];
  for (const event of validatedEvents) {
    const relativeStep = (event.frame - anchorFrame) / framesPerStep;
    if (relativeStep < 0 || relativeStep >= 16) {
      ignoredCount += 1;
      assignments.push({
        event: event.event,
        track: event.track,
        frame: event.frame,
        relativeStep,
        step: null,
        accepted: false,
      });
      continue;
    }
    const step = Math.min(15, Math.round(relativeStep));
    masks[event.track] |= 1 << step;
    acceptedCount += 1;
    assignments.push({
      event: event.event,
      track: event.track,
      frame: event.frame,
      relativeStep,
      step: step + 1,
      accepted: true,
    });
  }
  return {
    masks: masks.map((mask) => mask & 0xffff),
    acceptedCount,
    ignoredCount,
    anchorFrame,
    framesPerStep,
    assignments,
  };
}

export function masksToTracks(masks) {
  if (!Array.isArray(masks) || masks.length !== 6) {
    throw new PadRecordingError('validation_error', 'Pattern 必须包含六条音轨。');
  }
  return masks.map((mask) => {
    if (!Number.isInteger(mask) || mask < 0 || mask > 0xffff) {
      throw new PadRecordingError('validation_error', '音轨 Mask 必须是 0–65535。');
    }
    return Array.from({ length: 16 }, (_, step) => (mask >> step) & 1);
  });
}

export function serializeSavedPattern({
  name,
  bpm,
  masks,
  approximateQuantization = false,
  savedAt = new Date().toISOString(),
}) {
  const normalizedName = String(name || '我的鼓点').trim().slice(0, 80) || '我的鼓点';
  if (!Number.isInteger(bpm) || bpm < 40 || bpm > 240) {
    throw new PadRecordingError('validation_error', '保存的 BPM 必须是 40–240。');
  }
  masksToTracks(masks);
  if (typeof approximateQuantization !== 'boolean') {
    throw new PadRecordingError('validation_error', '量化来源标记必须是布尔值。');
  }
  return JSON.stringify({
    schemaVersion: 'easyinput.saved-pattern.v1',
    name: normalizedName,
    bpm,
    masks: [...masks],
    approximateQuantization,
    savedAt,
  });
}

export function parseSavedPattern(serialized) {
  let value;
  try {
    value = JSON.parse(serialized);
  } catch (_) {
    throw new PadRecordingError('storage_error', '已保存的 Pattern 无法解析。');
  }
  if (!value || value.schemaVersion !== 'easyinput.saved-pattern.v1') {
    throw new PadRecordingError('storage_error', '已保存的 Pattern 版本不受支持。');
  }
  const encoded = serializeSavedPattern(value);
  return JSON.parse(encoded);
}
