import assert from 'node:assert/strict';

import { PatternAckGate } from '../main/web/ai-pattern.js';
import { PatternRevisionStore } from '../main/web/pattern-session.js';
import {
  detectTempoCandidates,
  evaluateTempoCandidate,
} from '../main/web/tempo-detection.js';

function eventsAtFrames(frames) {
  return frames.map((frame, index) => ({
    event: index + 1,
    track: index % 2 === 0 ? 0 : 4,
    frame,
    source: 'hardware',
  }));
}

const slowEighths = eventsAtFrames([
  1000, 37000, 73000, 109000, 145000, 181000, 217000, 253000,
]);
const slow = detectTempoCandidates(slowEighths, { preferredBpm: 120 });
assert.equal(slow.recommendedBpm, 40);
assert.deepEqual(slow.candidates.map(({ bpm }) => bpm), [40, 80, 160]);
assert.equal(slow.candidates[0].acceptedCount, 8);
assert.ok(slow.candidates[1].ignoredCount > 0);

const quarterNotes120 = eventsAtFrames([1000, 25000, 49000, 73000]);
const regular = detectTempoCandidates(quarterNotes120, { preferredBpm: 120 });
assert.equal(regular.recommendedBpm, 120, 'preferred BPM resolves an otherwise metrical tie');
assert.ok(regular.candidates.some(({ bpm }) => bpm === 60));
assert.ok(regular.candidates.some(({ bpm }) => bpm === 120));
assert.ok(regular.candidates.some(({ bpm }) => bpm === 240));

const evaluated = evaluateTempoCandidate(quarterNotes120, 120);
assert.deepEqual(
  evaluated.assignments.map(({ step }) => step),
  [1, 5, 9, 13],
);

assert.throws(
  () => detectTempoCandidates(eventsAtFrames([1000, 2000, 3000])),
  (error) => error.type === 'tempo_insufficient_events',
);

const revisions = new PatternRevisionStore();
const first = revisions.update({
  bpm: 120,
  masks: [0x1111, 0x1010, 0, 0, 0, 0],
  source: 'hardware_recording',
  approximateQuantization: true,
});
assert.equal(first.revision, 1);
const commit = revisions.commitSnapshot();
assert.ok(Object.isFrozen(commit));
assert.ok(Object.isFrozen(commit.masks));
assert.equal(revisions.acknowledge(commit), true);
assert.equal(revisions.isSynced, true);

const ai = revisions.beginAiRequest('request-1');
assert.equal(ai.sourceRevision, 1);
revisions.update({
  bpm: 121,
  masks: first.masks,
  source: 'tempo_live',
  approximateQuantization: true,
});
assert.equal(revisions.isSynced, false);
assert.deepEqual(revisions.resolveAiRequest(ai), {
  accepted: true,
  stale: true,
  currentRevision: 2,
  sourceRevision: 1,
});
assert.equal(revisions.acknowledge(commit), false, 'an old ACK must not sync a newer revision');

const current = revisions.commitSnapshot();
assert.equal(revisions.acknowledge(current), true);
const olderRequest = revisions.beginAiRequest('request-2');
const latestRequest = revisions.beginAiRequest('request-3');
assert.equal(revisions.resolveAiRequest(olderRequest).accepted, false);
assert.equal(revisions.resolveAiRequest(latestRequest).accepted, true);

const ackGate = new PatternAckGate();
const expectedAck = ackGate.wait(1000, (message) => message.revision === 3);
assert.equal(
  ackGate.acknowledge({ command: 'COMMIT', revision: 2 }),
  false,
  'a stale ACK must remain ignored while the current transaction waits',
);
assert.equal(ackGate.hasPending, true);
assert.equal(ackGate.acknowledge({ command: 'COMMIT', revision: 3 }), true);
assert.equal((await expectedAck).revision, 3);

console.log('tempo detection and pattern revision tests passed');
