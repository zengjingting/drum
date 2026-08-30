import {
  PadRecordingError,
  RECORDING_SAMPLE_RATE_HZ,
  quantizePadEvents,
  validatePadEvent,
} from './pad-recording.js';

export const TEMPO_MIN_BPM = 40;
export const TEMPO_MAX_BPM = 240;
export const TEMPO_MIN_EVENTS = 4;

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function normalizeEvents(events) {
  if (!Array.isArray(events)) {
    throw new PadRecordingError('tempo_error', 'Tempo 检测事件必须是数组。');
  }
  return events.map(validatePadEvent).sort((left, right) => (
    left.frame - right.frame || left.event - right.event
  ));
}

export function evaluateTempoCandidate(
  events,
  bpm,
  sampleRateHz = RECORDING_SAMPLE_RATE_HZ,
) {
  const result = quantizePadEvents(events, bpm, sampleRateHz);
  const accepted = result.assignments.filter((assignment) => assignment.accepted);
  const meanGridError = accepted.length === 0
    ? 1
    : accepted.reduce((sum, assignment) => (
      sum + Math.abs(assignment.relativeStep - Math.round(assignment.relativeStep))
    ), 0) / accepted.length;
  const uniqueCells = new Set(
    accepted.map((assignment) => `${assignment.track}:${assignment.step}`),
  ).size;
  const ignoredRatio = result.assignments.length === 0
    ? 1
    : result.ignoredCount / result.assignments.length;
  const collisionRatio = accepted.length === 0
    ? 1
    : (accepted.length - uniqueCells) / accepted.length;

  return {
    bpm,
    masks: result.masks,
    assignments: result.assignments,
    acceptedCount: result.acceptedCount,
    ignoredCount: result.ignoredCount,
    meanGridError,
    ignoredRatio,
    collisionRatio,
    score: meanGridError + ignoredRatio * 4 + collisionRatio * 0.25,
  };
}

function compareCandidates(left, right, preferredBpm) {
  if (left.score !== right.score) return left.score - right.score;
  if (left.acceptedCount !== right.acceptedCount) {
    return right.acceptedCount - left.acceptedCount;
  }
  const leftDistance = Math.abs(left.bpm - preferredBpm);
  const rightDistance = Math.abs(right.bpm - preferredBpm);
  if (leftDistance !== rightDistance) return leftDistance - rightDistance;
  return left.bpm - right.bpm;
}

function tempoFamily(bestBpm) {
  const values = [Math.round(bestBpm)];
  let slower = bestBpm / 2;
  let faster = bestBpm * 2;
  while (values.length < 3 && (slower >= TEMPO_MIN_BPM || faster <= TEMPO_MAX_BPM)) {
    if (slower >= TEMPO_MIN_BPM) values.push(Math.round(slower));
    if (values.length < 3 && faster <= TEMPO_MAX_BPM) values.push(Math.round(faster));
    slower /= 2;
    faster *= 2;
  }
  return [...new Set(values)].sort((left, right) => left - right);
}

export function detectTempoCandidates(events, {
  sampleRateHz = RECORDING_SAMPLE_RATE_HZ,
  preferredBpm = 120,
} = {}) {
  const normalized = normalizeEvents(events);
  if (normalized.length < TEMPO_MIN_EVENTS) {
    throw new PadRecordingError(
      'tempo_insufficient_events',
      `至少需要 ${TEMPO_MIN_EVENTS} 次有效敲击才能检测速度。`,
    );
  }
  if (!Number.isFinite(sampleRateHz) || sampleRateHz <= 0) {
    throw new PadRecordingError('tempo_error', 'Tempo 检测采样率必须大于零。');
  }
  const preferred = clamp(Math.round(preferredBpm), TEMPO_MIN_BPM, TEMPO_MAX_BPM);
  const evaluated = [];
  for (let bpm = TEMPO_MIN_BPM; bpm <= TEMPO_MAX_BPM; bpm += 1) {
    const candidate = evaluateTempoCandidate(normalized, bpm, sampleRateHz);
    if (candidate.acceptedCount >= TEMPO_MIN_EVENTS) evaluated.push(candidate);
  }
  if (evaluated.length === 0) {
    throw new PadRecordingError(
      'tempo_unstable',
      '没有速度候选能形成可用的 16 步网格，请重新录制。',
    );
  }
  evaluated.sort((left, right) => compareCandidates(left, right, preferred));
  const best = evaluated[0];
  const family = tempoFamily(best.bpm)
    .map((bpm) => evaluateTempoCandidate(normalized, bpm, sampleRateHz));
  if (!family.some((candidate) => candidate.bpm === best.bpm)) family.push(best);
  family.sort((left, right) => left.bpm - right.bpm);

  const rankedFamily = [...family].sort((left, right) => (
    compareCandidates(left, right, preferred)
  ));
  const second = rankedFamily[1];
  const ambiguous = Boolean(second && (
    Math.abs(second.score - rankedFamily[0].score) <= 0.08
    && Math.abs(second.acceptedCount - rankedFamily[0].acceptedCount) <= 1
  ));

  return {
    status: ambiguous ? 'ambiguous' : 'stable',
    eventCount: normalized.length,
    recommendedBpm: best.bpm,
    candidates: family.map((candidate) => ({
      ...candidate,
      recommended: candidate.bpm === best.bpm,
    })),
  };
}
