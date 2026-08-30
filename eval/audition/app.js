"use strict";

const REQUIRED_PROTOCOL_VERSION = 2;
const ZERO_PATTERN = [0, 0, 0, 0, 0, 0];
const DATASET_CONFIGS = Object.freeze({
  v1: {
    id: "v1",
    path: "./audition-cases.json",
    orderVersion: "blind-v1",
    postHoc: false,
    resultLabel: "blind-v1"
  },
  "blind-v2": {
    id: "blind-v2",
    path: "./audition-cases-blind-v2.json",
    orderVersion: "blind-v2",
    postHoc: true,
    resultLabel: "blind-v2-post-hoc"
  }
});
const METRICS = [
  { key: "styleRecognition", label: "风格辨识度", low: "1 · 很不明显", high: "5 · 很明显" },
  { key: "grooveNaturalness", label: "律动自然度", low: "1 · 很生硬", high: "5 · 很自然" },
  { key: "willingnessToUse", label: "直接应用意愿", low: "1 · 不会使用", high: "5 · 会直接使用" }
];

const ui = Object.fromEntries([
  "connectButton", "connectionDot", "connectionStatus", "progressStatus",
  "blindId", "bpmBadge", "taskPrompt", "playButton", "replayButton",
  "stopButton", "deviceMessage", "ratings", "previousButton", "nextButton",
  "downloadButton", "copyButton", "exportPanel", "resultJson", "exportStatus",
  "studyMode", "revisionNotice", "retestTitle", "retestDescription", "persistenceStatus"
].map(id => [id, document.getElementById(id)]));

const encoder = new TextEncoder();
const decoder = new TextDecoder();
const datasetParameter = new URLSearchParams(window.location.search).get("dataset") || "v1";
const requestedDatasetId = datasetParameter === "v2" ? "blind-v2" : datasetParameter;
const datasetConfig = DATASET_CONFIGS[requestedDatasetId] || null;
let data = null;
let currentIndex = 0;
let ratings = {};
let listeningStats = {};
let startedAt = new Date().toISOString();
let completedAt = null;
let sessionId = crypto.randomUUID?.() || `pilot-${Date.now()}`;
let progressStorageKey = null;
let persistenceAvailable = true;
let serialPort = null;
let reader = null;
let writer = null;
let readLoopPromise = null;
let lineBuffer = "";
let waiters = [];
let busy = false;
let closing = false;
let deviceRunning = null;
let verifiedProtocolVersion = null;

function setMessage(text, error = false) {
  ui.deviceMessage.textContent = text;
  ui.deviceMessage.style.color = error ? "#ff8b66" : "";
}

function setConnection(status, text) {
  ui.connectionDot.className = `dot${status === "online" ? " online" : status === "error" ? " error" : ""}`;
  ui.connectionStatus.textContent = text;
  ui.connectButton.textContent = status === "online" ? "断开并清空" : "连接 USB 设备";
  renderControls();
}

function setExportStatus(text, error = false) {
  ui.exportStatus.textContent = text;
  ui.exportStatus.classList.toggle("error-text", error);
}

function setPersistenceStatus(text, error = false) {
  ui.persistenceStatus.textContent = text;
  ui.persistenceStatus.classList.toggle("error-text", error);
}

function datasetRetestDesign() {
  if (!data) return null;
  const candidates = [
    data.retestDesign,
    typeof data.condition === "object" ? data.condition?.retestDesign : data.condition
  ];
  return candidates.find(value => typeof value === "string" && value) || null;
}

function retestPresentation() {
  const design = datasetRetestDesign();
  if (design === "post_hoc_full_kit_replacement_and_gain_rebalance_retest") {
    return {
      eyebrow: "POST-HOC FULL-KIT + GAIN RETEST",
      title: "Post-hoc 整套音色与增益重平衡复测",
      description: "本轮使用完成整套音色替换与增益重平衡后的 blind-v2；结果必须与 blind-v1 分开保存和报告，不能替代原 Pilot。"
    };
  }
  return {
    eyebrow: "POST-HOC RETEST",
    title: "Post-hoc 复测",
    description: design
      ? `本轮复测定义为 ${design}；结果必须与 blind-v1 分开保存和报告，不能替代原 Pilot。`
      : "正在读取本轮复测定义；结果必须与 blind-v1 分开保存和报告，不能替代原 Pilot。"
  };
}

function renderStudyMode() {
  document.querySelectorAll("[data-dataset-link]").forEach(link => {
    const active = link.dataset.datasetLink === requestedDatasetId;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  if (!datasetConfig) {
    ui.studyMode.textContent = "未知数据集";
    ui.revisionNotice.hidden = true;
    return;
  }
  const presentation = retestPresentation();
  ui.studyMode.textContent = datasetConfig.postHoc
    ? `${presentation.eyebrow} · ${data?.samples?.length || 12} SAMPLES`
    : "SINGLE-PERSON PILOT · 12 SAMPLES";
  ui.revisionNotice.hidden = !datasetConfig.postHoc;
  ui.retestTitle.textContent = presentation.title;
  ui.retestDescription.textContent = presentation.description;
}

function sampleComplete(sample) {
  return METRICS.every(metric => Number.isInteger(ratings[sample.blindId]?.[metric.key]));
}

function completedCount() {
  return data ? data.samples.filter(sampleComplete).length : 0;
}

function buildProgressStorageKey() {
  return `easyinput.audition.progress.v1:${datasetConfig.id}:${data.randomization.orderFingerprint}`;
}

function normalizeStoredRating(value) {
  if (!value || typeof value !== "object") return null;
  const normalized = {};
  for (const metric of METRICS) {
    const score = value[metric.key];
    if (Number.isInteger(score) && score >= 1 && score <= 5) normalized[metric.key] = score;
  }
  if (typeof value.ratedAt === "string") normalized.ratedAt = value.ratedAt;
  return Object.keys(normalized).some(key => key !== "ratedAt") ? normalized : null;
}

function restoreProgress() {
  progressStorageKey = buildProgressStorageKey();
  try {
    const raw = window.localStorage.getItem(progressStorageKey);
    if (!raw) {
      setPersistenceStatus("本机暂存：已启用");
      return;
    }
    const saved = JSON.parse(raw);
    if (saved?.schemaVersion !== "easyinput.audition-progress.v1" || saved.datasetId !== datasetConfig.id || saved.orderFingerprint !== data.randomization.orderFingerprint) return;
    const sampleIds = new Set(data.samples.map(sample => sample.blindId));
    ratings = Object.fromEntries(Object.entries(saved.ratings || {}).flatMap(([blindId, value]) => {
      const normalized = normalizeStoredRating(value);
      return sampleIds.has(blindId) && normalized ? [[blindId, normalized]] : [];
    }));
    listeningStats = Object.fromEntries(Object.entries(saved.listeningStats || {}).filter(([blindId, value]) => sampleIds.has(blindId) && value && Number.isInteger(value.playCount) && Number.isInteger(value.replayCount)));
    currentIndex = Number.isInteger(saved.currentIndex) ? Math.min(Math.max(saved.currentIndex, 0), data.samples.length - 1) : 0;
    if (typeof saved.startedAt === "string") startedAt = saved.startedAt;
    if (typeof saved.completedAt === "string") completedAt = saved.completedAt;
    if (typeof saved.sessionId === "string" && saved.sessionId) sessionId = saved.sessionId;
    setPersistenceStatus(`本机暂存：已恢复 ${completedCount()} / ${data.samples.length} 条评分`);
  } catch (_) {
    persistenceAvailable = false;
    setPersistenceStatus("本机暂存不可用；完成后请立即复制或下载", true);
  }
}

function persistProgress() {
  if (!progressStorageKey || !persistenceAvailable) return;
  const progress = {
    schemaVersion: "easyinput.audition-progress.v1",
    datasetId: datasetConfig.id,
    orderFingerprint: data.randomization.orderFingerprint,
    sessionId,
    startedAt,
    completedAt,
    currentIndex,
    ratings,
    listeningStats,
    savedAt: new Date().toISOString()
  };
  try {
    window.localStorage.setItem(progressStorageKey, JSON.stringify(progress));
    setPersistenceStatus(`本机暂存：已保存 ${completedCount()} / ${data.samples.length} 条评分`);
  } catch (_) {
    persistenceAvailable = false;
    setPersistenceStatus("本机暂存失败；完成后请立即复制或下载", true);
  }
}

function buildResults() {
  if (!data || completedCount() !== data.samples.length) return null;
  return {
    schemaVersion: "easyinput.audition-results.v1",
    studyDesign: datasetConfig.postHoc ? "single-person-post-hoc-retest" : "single-person-pilot",
    datasetId: datasetConfig.id,
    postHoc: datasetConfig.postHoc,
    condition: datasetConfig.postHoc ? data.condition || null : null,
    retestDesign: datasetConfig.postHoc ? datasetRetestDesign() : null,
    sessionId,
    sourceSessionId: data.sourceSessionId,
    orderVersion: data.randomization.orderVersion,
    orderFingerprint: data.randomization.orderFingerprint,
    startedAt,
    completedAt,
    deviceProtocolVersion: verifiedProtocolVersion,
    ratings: data.samples.map((sample, blindOrder) => ({
      blindOrder: blindOrder + 1,
      blindId: sample.blindId,
      taskId: sample.taskId,
      styleRecognition: ratings[sample.blindId].styleRecognition,
      grooveNaturalness: ratings[sample.blindId].grooveNaturalness,
      willingnessToUse: ratings[sample.blindId].willingnessToUse,
      ratedAt: ratings[sample.blindId].ratedAt,
      playCount: listeningStats[sample.blindId]?.playCount || 0,
      replayCount: listeningStats[sample.blindId]?.replayCount || 0
    }))
  };
}

function renderExportPanel() {
  const complete = Boolean(data && completedCount() === data.samples.length);
  if (complete && !completedAt) {
    completedAt = new Date().toISOString();
    persistProgress();
  }
  ui.exportPanel.hidden = !complete;
  if (complete) ui.resultJson.value = `${JSON.stringify(buildResults(), null, 2)}\n`;
}

function renderControls() {
  const connected = Boolean(serialPort && writer);
  const loaded = Boolean(data?.samples?.length);
  const sample = loaded ? data.samples[currentIndex] : null;
  ui.connectButton.disabled = busy || !("serial" in navigator);
  ui.playButton.disabled = busy || !connected || !sample;
  ui.replayButton.disabled = busy || !connected || !sample || !(listeningStats[sample.blindId]?.playCount > 0);
  ui.stopButton.disabled = busy || !connected;
  ui.previousButton.disabled = busy || !loaded || currentIndex === 0 || deviceRunning === true;
  ui.nextButton.disabled = busy || !loaded || currentIndex === data.samples.length - 1 || deviceRunning === true;
  ui.downloadButton.disabled = busy || !loaded || completedCount() !== data.samples.length;
  ui.copyButton.disabled = busy || !loaded || completedCount() !== data.samples.length;
  if (loaded) ui.progressStatus.textContent = `${currentIndex + 1} / ${data.samples.length} · 已评分 ${completedCount()} 条`;
  renderExportPanel();
}

function buildRatingControls() {
  ui.ratings.replaceChildren();
  for (const metric of METRICS) {
    const fieldset = document.createElement("fieldset");
    fieldset.className = "rating-group";
    fieldset.dataset.metric = metric.key;
    fieldset.innerHTML = `<legend>${metric.label}</legend><div class="anchors"><span>${metric.low}</span><span>${metric.high}</span></div><div class="scale">${[1, 2, 3, 4, 5].map(value => `<input id="${metric.key}-${value}" name="${metric.key}" type="radio" value="${value}"><label for="${metric.key}-${value}">${value}</label>`).join("")}</div>`;
    fieldset.addEventListener("change", event => {
      const value = Number(event.target.value);
      if (!Number.isInteger(value) || value < 1 || value > 5) return;
      const sample = data.samples[currentIndex];
      ratings[sample.blindId] = { ...(ratings[sample.blindId] || {}), [metric.key]: value, ratedAt: new Date().toISOString() };
      persistProgress();
      renderControls();
    });
    ui.ratings.append(fieldset);
  }
}

function renderSample() {
  if (!data) return;
  const sample = data.samples[currentIndex];
  ui.blindId.textContent = sample.blindId;
  ui.bpmBadge.textContent = `${sample.bpm} BPM`;
  ui.taskPrompt.textContent = sample.prompt;
  for (const metric of METRICS) {
    const selected = ratings[sample.blindId]?.[metric.key];
    document.querySelectorAll(`input[name="${metric.key}"]`).forEach(input => {
      input.checked = Number(input.value) === selected;
    });
  }
  setMessage(deviceRunning === true ? "请先停止当前盲样，再切换上一条或下一条。" : "点击播放后才会把当前盲样写入硬件。连接和切换样本不会发送 Pattern。" );
  renderControls();
}

function validateDataset(candidate) {
  if (candidate?.schemaVersion !== "easyinput.audition-cases.v1" || !Array.isArray(candidate.samples) || candidate.samples.length !== 12) throw new Error("盲样文件格式不正确");
  if (candidate.randomization?.orderVersion !== datasetConfig.orderVersion) throw new Error(`盲样版本不匹配：需要 ${datasetConfig.orderVersion}`);
  if (new Set(candidate.samples.map(sample => sample.blindId)).size !== candidate.samples.length) throw new Error("盲样 ID 必须唯一");
  for (const sample of candidate.samples) {
    if (!/^BLIND-\d{2}$/.test(sample.blindId) || !Number.isInteger(sample.bpm) || sample.bpm < 40 || sample.bpm > 240 || !Array.isArray(sample.masks) || sample.masks.length !== 6 || sample.masks.some(value => !Number.isInteger(value) || value < 0 || value > 65535)) throw new Error(`盲样 ${sample.blindId || "?"} 数据无效`);
  }
}

async function loadDataset() {
  if (!datasetConfig) throw new Error("dataset 参数仅支持 v1 或 blind-v2（v2 是兼容别名）");
  const response = await fetch(datasetConfig.path, { cache: "no-store" });
  if (!response.ok) throw new Error(`读取盲样失败：HTTP ${response.status}`);
  const candidate = await response.json();
  validateDataset(candidate);
  data = candidate;
  renderStudyMode();
  restoreProgress();
  buildRatingControls();
  renderSample();
}

function createWaiter(predicate, timeoutMs = 1500) {
  let entry;
  let timer;
  const promise = new Promise((resolve, reject) => {
    timer = setTimeout(() => {
      waiters = waiters.filter(item => item !== entry);
      reject(new Error("等待设备响应超时"));
    }, timeoutMs);
    entry = { predicate, resolve: value => { clearTimeout(timer); resolve(value); } };
    waiters.push(entry);
  });
  return { promise, cancel: () => { clearTimeout(timer); waiters = waiters.filter(item => item !== entry); } };
}

function handleLine(line) {
  if (!line.trim()) return;
  let message;
  try { message = JSON.parse(line); } catch (_) { return; }
  if (message.type === "state") deviceRunning = Boolean(message.running);
  const matched = waiters.filter(entry => entry.predicate(message));
  waiters = waiters.filter(entry => !matched.includes(entry));
  matched.forEach(entry => entry.resolve(message));
  renderControls();
}

function handleBytes(bytes) {
  lineBuffer += decoder.decode(bytes, { stream: true });
  const lines = lineBuffer.split(/\r?\n/);
  lineBuffer = lines.pop() || "";
  lines.forEach(handleLine);
}

async function readSerial(port) {
  try {
    reader = port.readable.getReader();
    while (serialPort === port) {
      const { value, done } = await reader.read();
      if (done) break;
      if (value) handleBytes(value);
    }
  } catch (error) {
    if (!closing) {
      setConnection("error", "串口读取中断");
      setMessage(error.message || "串口读取中断", true);
    }
  } finally {
    if (reader) { reader.releaseLock(); reader = null; }
  }
}

async function sendCommand(command) {
  if (!writer) throw new Error("设备尚未连接");
  await writer.write(encoder.encode(`${command}\n`));
}

async function sendAndWait(command, predicate, timeoutMs = 1500) {
  const waiter = createWaiter(predicate, timeoutMs);
  try {
    await sendCommand(command);
    return await waiter.promise;
  } catch (error) {
    waiter.cancel();
    throw error;
  }
}

async function queryState(predicate = () => true) {
  return sendAndWait("STATE", message => message.type === "state" && predicate(message));
}

function assertProtocol(state) {
  const capabilities = new Set(Array.isArray(state.capabilities) ? state.capabilities : []);
  if (Number(state.protocolVersion) < REQUIRED_PROTOCOL_VERSION || !capabilities.has("pattern") || !capabilities.has("sequencer")) throw new Error("设备固件不支持 Web Serial protocol v2 音序器");
  verifiedProtocolVersion = Number(state.protocolVersion);
}

async function confirmState(predicate) {
  for (let attempt = 0; attempt < 4; attempt += 1) {
    try { return await queryState(predicate); } catch (_) { /* retry */ }
  }
  throw new Error("设备状态未按预期更新");
}

async function withHardwareOperation(action) {
  if (busy) return;
  busy = true;
  renderControls();
  try { await action(); }
  catch (error) { setMessage(error.message || "设备操作失败", true); }
  finally { busy = false; renderControls(); }
}

async function playCurrent(isReplay) {
  await withHardwareOperation(async () => {
    const sample = data.samples[currentIndex];
    setMessage("正在确认设备并写入盲样…");
    const initial = await queryState();
    assertProtocol(initial);
    if (initial.running) {
      await sendCommand("TOGGLE");
      await confirmState(state => state.running === false);
    }
    await sendCommand(`BPM ${sample.bpm}`);
    await confirmState(state => Number(state.bpm) === sample.bpm);
    const patternReply = await sendAndWait(`PATTERN ${sample.masks.join(" ")}`, message => (message.type === "ack" && message.command === "PATTERN") || message.type === "error");
    if (patternReply.type === "error") throw new Error(patternReply.message || "设备拒绝 Pattern");
    await sendCommand("TOGGLE");
    await confirmState(state => state.running === true);
    const prior = listeningStats[sample.blindId] || { playCount: 0, replayCount: 0 };
    listeningStats[sample.blindId] = { ...prior, playCount: prior.playCount + 1, replayCount: prior.replayCount + (isReplay ? 1 : 0), lastPlayedAt: new Date().toISOString() };
    persistProgress();
    setMessage(`${sample.blindId} 正在硬件播放。评分前可重复试听。`);
  });
}

async function stopCurrent() {
  await withHardwareOperation(async () => {
    setMessage("正在停止…");
    const state = await queryState();
    assertProtocol(state);
    if (state.running) {
      await sendCommand("TOGGLE");
      await confirmState(next => next.running === false);
    }
    deviceRunning = false;
    setMessage("已停止。Pattern 会在断开或离开页面时清空。" );
  });
}

async function bestEffortStopAndClear() {
  if (!writer) return;
  try {
    const state = await queryState();
    if (state.running) {
      await sendCommand("TOGGLE");
      await confirmState(next => next.running === false);
    }
  } catch (_) {
    if (deviceRunning === true) {
      try { await sendCommand("TOGGLE"); } catch (_) { /* best effort */ }
    }
  }
  try {
    await sendAndWait(`PATTERN ${ZERO_PATTERN.join(" ")}`, message => (message.type === "ack" && message.command === "PATTERN") || message.type === "error", 1000);
  } catch (_) { /* best effort */ }
  deviceRunning = false;
}

async function closePort() {
  if (!serialPort) return;
  closing = true;
  const port = serialPort;
  if (reader) { try { await reader.cancel(); } catch (_) { /* already closed */ } }
  if (readLoopPromise) { try { await readLoopPromise; } catch (_) { /* already closed */ } }
  if (writer) { writer.releaseLock(); writer = null; }
  try { await port.close(); } catch (_) { /* already closed */ }
  serialPort = null;
  readLoopPromise = null;
  lineBuffer = "";
  closing = false;
  setConnection("offline", "尚未连接");
}

async function toggleConnection() {
  if (serialPort) {
    await withHardwareOperation(async () => {
      setMessage("正在停止并清空板载 Pattern…");
      await bestEffortStopAndClear();
      await closePort();
      setMessage("已断开，板载 Pattern 已尽力清空。" );
    });
    return;
  }
  await withHardwareOperation(async () => {
    const port = await navigator.serial.requestPort({ filters: [{ usbVendorId: 0x303a }] });
    await port.open({ baudRate: 115200, bufferSize: 1024 });
    serialPort = port;
    writer = port.writable.getWriter();
    readLoopPromise = readSerial(port);
    deviceRunning = null;
    setConnection("online", "设备已连接");
    setMessage("连接成功；尚未向设备发送任何 Pattern。点击播放开始。" );
  });
}

function downloadResults() {
  const result = buildResults();
  if (!result) return;
  const blob = new Blob([`${JSON.stringify(result, null, 2)}\n`], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `easyinput-${datasetConfig.resultLabel}-pilot-${new Date().toISOString().replace(/[:.]/g, "-")}.json`;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1500);
  setExportStatus("已请求浏览器下载。若未生成文件，请使用“复制 JSON”或直接复制下方文本。" );
}

async function copyResults() {
  const result = buildResults();
  if (!result) return;
  const text = `${JSON.stringify(result, null, 2)}\n`;
  ui.resultJson.value = text;
  try {
    await navigator.clipboard.writeText(text);
    setExportStatus("评分 JSON 已复制到剪贴板。" );
  } catch (_) {
    ui.resultJson.focus();
    ui.resultJson.select();
    setExportStatus("自动复制不可用，已选中下方 JSON；请按 Cmd/Ctrl+C。", true);
  }
}

function bestEffortPageExit() {
  if (!writer) return;
  const commands = [];
  if (deviceRunning === true) commands.push("TOGGLE");
  commands.push(`PATTERN ${ZERO_PATTERN.join(" ")}`);
  deviceRunning = false;
  void writer.write(encoder.encode(`${commands.join("\n")}\n`)).catch(() => {});
}

ui.connectButton.addEventListener("click", toggleConnection);
ui.playButton.addEventListener("click", () => playCurrent(false));
ui.replayButton.addEventListener("click", () => playCurrent(true));
ui.stopButton.addEventListener("click", stopCurrent);
ui.previousButton.addEventListener("click", () => { currentIndex -= 1; persistProgress(); renderSample(); });
ui.nextButton.addEventListener("click", () => { currentIndex += 1; persistProgress(); renderSample(); });
ui.downloadButton.addEventListener("click", downloadResults);
ui.copyButton.addEventListener("click", copyResults);
window.addEventListener("pagehide", bestEffortPageExit);

if ("serial" in navigator) {
  navigator.serial.addEventListener("disconnect", event => {
    if (event.target === serialPort) {
      if (writer) { try { writer.releaseLock(); } catch (_) { /* port already gone */ } }
      serialPort = null;
      writer = null;
      deviceRunning = null;
      setConnection("offline", "设备已断开");
      setMessage("USB 设备已断开。意外拔线时无法清空板载 Pattern。", true);
    }
  });
} else {
  setConnection("error", "浏览器不支持 Web Serial");
  setMessage("请使用桌面版 Chrome 或 Edge，并通过 localhost 打开此页面。", true);
}

renderStudyMode();
loadDataset().catch(error => {
  ui.progressStatus.textContent = "样本加载失败";
  setMessage(error.message || "无法读取盲样文件", true);
});
