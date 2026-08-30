import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const v1Path = path.join(root, "audition-cases.json");
const v2Path = path.join(root, "audition-cases-blind-v2.json");
const privatePath = path.join(root, "private", "model-mapping-blind-v2.json");
const v1 = JSON.parse(fs.readFileSync(v1Path, "utf8"));
const v2Text = fs.readFileSync(v2Path, "utf8");
const v2 = JSON.parse(v2Text);

const sha256 = value => crypto.createHash("sha256").update(value).digest("hex");
const popcount16 = value => Array.from({ length: 16 }, (_, index) => (value >> index) & 1).reduce((sum, bit) => sum + bit, 0);
const payloadKey = sample => JSON.stringify({ taskId: sample.taskId, task: sample.task, prompt: sample.prompt, bpm: sample.bpm, masks: sample.masks });
const canonicalOrder = samples => samples.map(sample => `${sample.blindId}|${sample.taskId}|${sample.bpm}|${sample.masks.join(",")}`).join("\n");

assert.equal(v2.schemaVersion, "easyinput.audition-cases.v1");
assert.equal(v2.condition, "post_hoc_full_kit_replacement_and_gain_rebalance_retest");
assert.equal(v2.retestDesign, "post_hoc_full_kit_replacement_and_gain_rebalance_retest");
assert.equal(v2.audioCondition.changeScope, "full_kit_replacement_and_gain_rebalance");
assert.equal(v2.audioCondition.currentAssetManifestSha256, "a1156f906ccbdafa19c83426469bf0f8f46bc87f7a432237be10f4e0377d13c4");
assert.equal(v2.audioCondition.baselineAssetManifestSha256, "6ce669953a788076365e33a391b2d237f5efc67d0a89a3a836438a91d91589bb");
assert.equal(v2.audioCondition.closedHatPcmSha256, "5063600d6f3746665da4f98d2cf2b546a36e81190aea5205888ac90b4ae8bad1");
assert.equal(v2.audioCondition.baselineBlindV1ClosedHatPcmSha256, "c0dc46c94e53773ee7b21ff03a86732a285add110a37f905d15c7ced7232830b");
assert.equal(v2.randomization.orderVersion, "blind-v2");
assert.equal(v2.sampleCount, 12);
assert.equal(v2.samples.length, 12);
assert.equal(new Set(v2.samples.map(sample => sample.blindId)).size, 12);
assert.equal(sha256(canonicalOrder(v2.samples)), v2.randomization.orderFingerprint);

for (const sample of v2.samples) {
  assert.match(sample.blindId, /^BLIND-\d{2}$/);
  assert.ok(Number.isInteger(sample.bpm) && sample.bpm >= 40 && sample.bpm <= 240);
  assert.equal(sample.masks.length, 6);
  sample.masks.forEach(mask => assert.ok(Number.isInteger(mask) && mask >= 0 && mask <= 65535));
}

for (const forbidden of ["providerid", "requestedmodel", "responsereportedmodel", "runid", "deepseek", "zhipu", "glm-"]) {
  assert.equal(v2Text.toLowerCase().includes(forbidden), false, `public blind-v2 data contains ${forbidden}`);
}

assert.deepEqual(v2.samples.map(payloadKey).sort(), v1.samples.map(payloadKey).sort(), "blind-v2 must contain exactly the same 12 Pattern payloads as blind-v1");
assert.notDeepEqual(v2.samples.map(payloadKey), v1.samples.map(payloadKey), "blind-v2 order must differ from blind-v1");
v2.samples.forEach((sample, index) => assert.notEqual(payloadKey(sample), payloadKey(v1.samples[index]), `blind-v2 position ${index + 1} repeats blind-v1`));

const extremePositions = v2.samples.map((sample, index) => popcount16(sample.masks[2]) >= 12 ? index + 1 : null).filter(Boolean);
assert.deepEqual(extremePositions, v2.randomization.constraints.extremeExposurePositions);
assert.equal(popcount16(v2.samples.at(-1).masks[2]) >= 12, false);

const taskPositions = new Map();
v2.samples.forEach((sample, index) => {
  const positions = taskPositions.get(sample.taskId) || [];
  positions.push(index + 1);
  taskPositions.set(sample.taskId, positions);
});
for (const positions of taskPositions.values()) {
  assert.equal(positions.length, 2);
  assert.ok(positions[1] - positions[0] >= v2.randomization.constraints.minimumSameTaskSeparation);
}

assert.doesNotThrow(() => execFileSync("git", ["check-ignore", "-q", privatePath], { cwd: root, stdio: "ignore" }));

if (fs.existsSync(privatePath)) {
  const privateMapping = JSON.parse(fs.readFileSync(privatePath, "utf8"));
  assert.equal(privateMapping.condition, v2.condition);
  assert.equal(privateMapping.retestDesign, v2.retestDesign);
  assert.deepEqual(privateMapping.audioCondition, v2.audioCondition);
  assert.equal(`sha256:${sha256(privateMapping.randomization.seed)}`, v2.randomization.seedCommitment);
  assert.equal(privateMapping.randomization.publicOrderFingerprint, v2.randomization.orderFingerprint);
  assert.equal(privateMapping.mapping.length, 12);
  assert.equal(new Set(privateMapping.mapping.map(item => item.blindId)).size, 12);
  assert.equal(new Set(privateMapping.mapping.map(item => item.sourceBlindId)).size, 12);
  const mappingByBlindId = Object.fromEntries(privateMapping.mapping.map(item => [item.blindId, item]));
  const v1ByBlindId = Object.fromEntries(v1.samples.map(item => [item.blindId, item]));
  const providers = privateMapping.mapping.map(item => item.providerId);
  assert.equal(new Set(providers).size, 2);
  for (let index = 1; index < providers.length; index += 1) assert.notEqual(providers[index], providers[index - 1], "hidden provider groups must alternate");
  for (const sample of v2.samples) {
    const item = mappingByBlindId[sample.blindId];
    assert.ok(item);
    assert.equal(sample.taskId, `TASK-${item.caseId}`);
    assert.equal(payloadKey(sample), payloadKey(v1ByBlindId[item.sourceBlindId]));
    assert.equal(item.sortKey, sha256(`${privateMapping.randomization.seed}:${item.providerId}:${item.caseId}`));
  }
  console.log("blind-v2 static checks: OK (public + private mapping)");
} else {
  console.log("blind-v2 static checks: OK (public only; private ignored mapping unavailable)");
}
