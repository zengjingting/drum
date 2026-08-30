import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const casesPath = path.join(root, "audition-cases.json");
const casesV2Path = path.join(root, "audition-cases-blind-v2.json");
const indexPath = path.join(root, "index.html");
const appPath = path.join(root, "app.js");
const stylesPath = path.join(root, "styles.css");
const privateMappingPath = path.join(root, "private", "model-mapping.json");
const privateMappingV2Path = path.join(root, "private", "model-mapping-blind-v2.json");
const data = JSON.parse(fs.readFileSync(casesPath, "utf8"));
const index = fs.readFileSync(indexPath, "utf8");
const app = fs.readFileSync(appPath, "utf8");
const styles = fs.readFileSync(stylesPath, "utf8");

function validatePublicDataset(candidate, expectedOrderVersion, sourcePath) {
  assert.equal(candidate.schemaVersion, "easyinput.audition-cases.v1");
  assert.equal(candidate.sampleCount, 12);
  assert.equal(candidate.samples.length, 12);
  assert.equal(candidate.randomization.orderVersion, expectedOrderVersion);
  if (expectedOrderVersion === "blind-v2") {
    assert.equal(candidate.condition, "post_hoc_full_kit_replacement_and_gain_rebalance_retest");
    assert.equal(candidate.retestDesign, "post_hoc_full_kit_replacement_and_gain_rebalance_retest");
  }
  assert.equal(new Set(candidate.samples.map(sample => sample.blindId)).size, 12);

  for (const sample of candidate.samples) {
    assert.match(sample.blindId, /^BLIND-\d{2}$/);
    assert.ok(Number.isInteger(sample.bpm) && sample.bpm >= 40 && sample.bpm <= 240);
    assert.equal(sample.masks.length, 6);
    sample.masks.forEach(mask => assert.ok(Number.isInteger(mask) && mask >= 0 && mask <= 65535));
    assert.equal("providerId" in sample, false);
    assert.equal("model" in sample, false);
    assert.equal("runId" in sample, false);
  }

  const canonicalOrder = candidate.samples.map(sample => `${sample.blindId}|${sample.taskId}|${sample.bpm}|${sample.masks.join(",")}`).join("\n");
  const fingerprint = crypto.createHash("sha256").update(canonicalOrder).digest("hex");
  assert.equal(fingerprint, candidate.randomization.orderFingerprint);

  const publicDataText = fs.readFileSync(sourcePath, "utf8").toLowerCase();
  for (const forbidden of ["providerid", "requestedmodel", "responsereportedmodel", "deepseek", "zhipu", "glm-"]) assert.equal(publicDataText.includes(forbidden), false, `${sourcePath} contains ${forbidden}`);
}

validatePublicDataset(data, "blind-v1", casesPath);
if (fs.existsSync(casesV2Path)) validatePublicDataset(JSON.parse(fs.readFileSync(casesV2Path, "utf8")), "blind-v2", casesV2Path);

assert.equal(/(?:src|href)=["'](?:https?:)?\/\//i.test(index), false, "index.html has a network dependency");
assert.equal(app.includes("audition-cases.json"), true);
assert.equal(app.includes("audition-cases-blind-v2.json"), true);
assert.equal(app.includes('new URLSearchParams(window.location.search).get("dataset") || "v1"'), true);
assert.equal(app.includes('datasetParameter === "v2" ? "blind-v2"'), true);
assert.match(index, /href=["']\?dataset=blind-v2["']/);
assert.equal(index.includes("整套音色与增益复测 v2"), true);
assert.equal(app.includes("post_hoc_full_kit_replacement_and_gain_rebalance_retest"), true);
assert.equal(app.includes("datasetRetestDesign()"), true);
assert.equal(app.includes("CLOSED-HAT RETEST"), false);
assert.equal(app.includes("PATTERN ${sample.masks.join(\" \")}"), true);
assert.equal(app.includes("REQUIRED_PROTOCOL_VERSION = 2"), true);
assert.equal(app.includes("easyinput.audition.progress.v1:${datasetConfig.id}:${data.randomization.orderFingerprint}"), true);
assert.equal(app.includes("window.localStorage.getItem(progressStorageKey)"), true);
assert.equal(app.includes("window.localStorage.setItem(progressStorageKey"), true);
assert.equal(app.includes("function normalizeStoredRating(value)"), true);
assert.equal(app.includes("navigator.clipboard.writeText(text)"), true);
assert.equal(index.includes('id="resultJson"'), true);
assert.equal(index.includes('id="copyButton"'), true);
assert.equal(index.includes('id="persistenceStatus"'), true);
assert.equal(styles.includes(".revision-notice"), true);
assert.equal(styles.includes("[hidden]{display:none!important}"), true);
assert.equal(/fetch\(["']https?:\/\//i.test(app), false, "app must not upload or fetch remote data");

assert.doesNotThrow(() => execFileSync("git", ["check-ignore", "-q", privateMappingPath], { cwd: root, stdio: "ignore" }));
assert.doesNotThrow(() => execFileSync("git", ["check-ignore", "-q", privateMappingV2Path], { cwd: root, stdio: "ignore" }));

console.log(`audition static checks: OK (v1 + ${fs.existsSync(casesV2Path) ? "v2" : "v2 adapter awaiting dataset"})`);
