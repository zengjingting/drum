import { masksToTracks } from './pad-recording.js';

function normalizeBpm(bpm) {
  if (!Number.isInteger(bpm) || bpm < 40 || bpm > 240) {
    throw new TypeError('Pattern BPM must be an integer from 40 to 240.');
  }
  return bpm;
}

function normalizeMasks(masks) {
  masksToTracks(masks);
  return masks.map((mask) => Number(mask) & 0xffff);
}

function sameMasks(left, right) {
  return left.length === right.length && left.every((value, index) => value === right[index]);
}

export class PatternRevisionStore {
  constructor({ bpm = 120, masks = [0, 0, 0, 0, 0, 0], source = 'initial' } = {}) {
    this.currentRevision = 0;
    this.syncedRevision = null;
    this.current = Object.freeze({
      revision: 0,
      bpm: normalizeBpm(bpm),
      masks: Object.freeze(normalizeMasks(masks)),
      source,
      approximateQuantization: false,
    });
    this.latestAiRequestId = null;
  }

  update({ bpm, masks, source, approximateQuantization = false }) {
    this.currentRevision += 1;
    this.current = Object.freeze({
      revision: this.currentRevision,
      bpm: normalizeBpm(bpm),
      masks: Object.freeze(normalizeMasks(masks)),
      source: String(source || 'manual'),
      approximateQuantization: Boolean(approximateQuantization),
    });
    return this.snapshot();
  }

  clear(source = 'recording') {
    return this.update({
      bpm: this.current.bpm,
      masks: [0, 0, 0, 0, 0, 0],
      source,
      approximateQuantization: false,
    });
  }

  snapshot() {
    return {
      ...this.current,
      masks: [...this.current.masks],
    };
  }

  commitSnapshot() {
    return Object.freeze({
      ...this.current,
      masks: Object.freeze([...this.current.masks]),
    });
  }

  acknowledge({ revision, bpm, masks }) {
    const normalizedMasks = normalizeMasks(masks);
    if (
      revision !== this.current.revision
      || normalizeBpm(bpm) !== this.current.bpm
      || !sameMasks(normalizedMasks, this.current.masks)
    ) {
      return false;
    }
    this.syncedRevision = revision;
    return true;
  }

  markDisconnected() {
    this.syncedRevision = null;
  }

  get isSynced() {
    return this.syncedRevision === this.current.revision;
  }

  beginAiRequest(requestId) {
    const normalizedId = String(requestId || '');
    if (!normalizedId) throw new TypeError('AI requestId is required.');
    this.latestAiRequestId = normalizedId;
    return {
      requestId: normalizedId,
      sourceRevision: this.current.revision,
      snapshot: this.snapshot(),
    };
  }

  resolveAiRequest({ requestId, sourceRevision }) {
    const latestRequest = String(requestId) === this.latestAiRequestId;
    const latestRevision = sourceRevision === this.current.revision;
    return {
      accepted: latestRequest,
      stale: !latestRevision,
      currentRevision: this.current.revision,
      sourceRevision,
    };
  }
}

