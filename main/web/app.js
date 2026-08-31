import {
  AiPatternController,
  AiPatternError,
  PatternAckGate,
  TRACK_IDS,
  patternToMasks,
} from './ai-pattern.js';
import {
  PadRecordingError,
  RECORDING_STORAGE_KEY,
  RecordingBoundaryGate,
  parseSavedPattern,
  quantizePadEvents,
  serializeSavedPattern,
  validatePadEvent,
  validateRecordBoundary,
  verifyRecording,
} from './pad-recording.js';
import {
  PatternExplanationError,
  requestPatternExplanation,
} from './pattern-explanation.js';
import { PatternRevisionStore } from './pattern-session.js';
import { detectTempoCandidates } from './tempo-detection.js';

const REQUIRED_PROTOCOL_VERSION = 3;
const COMMAND_TIMEOUT_MS = 3500;
const RECORDING_TRACE_ENDPOINT = '/api/debug/recording-trace';
const DEFAULT_PATTERN_NAME = '我的鼓点';
const instruments = [
  { key: 'S1', name: 'Kick', color: '#ff7043' },
  { key: 'S2', name: 'Snare', color: '#ffb45b' },
  { key: 'S7', name: 'Closed Hi-Hat', color: '#71e0d4' },
  { key: 'S4', name: 'Open Hi-Hat', color: '#5aaef8' },
  { key: 'S5', name: 'Clap', color: '#be8cff' },
  { key: 'S6', name: 'Rimshot', color: '#f276b2' },
];

const $ = (selector) => document.querySelector(selector);
const padGrid = $('#padGrid');
const sequenceGrid = $('#sequenceGrid');
const squares = [...document.querySelectorAll('.beat')];
const bpmValue = $('#bpmValue');
const tempoState = $('#tempoState');
const patternStatus = $('#patternStatus');
const patternVersion = $('#patternVersion');
const toggle = $('#toggle');
const slower = $('#slower');
const faster = $('#faster');
const connectDevice = $('#connectDevice');
const connectionText = $('#connectionText');
const clearPattern = $('#clearPattern');
const sequenceSource = $('#sequenceSource');
const aiPrompt = $('#aiPrompt');
const generatePattern = $('#generatePattern');
const aiStatus = $('#aiStatus');
const aiResult = $('#aiResult');
const aiPatternTitle = $('#aiPatternTitle');
const aiPatternMeta = $('#aiPatternMeta');
const aiPatternNote = $('#aiPatternNote');
const applyAiPattern = $('#applyAiPattern');
const recordPattern = $('#recordPattern');
const savePatternButton = $('#savePattern');
const explainPattern = $('#explainPattern');
const recordStatus = $('#recordStatus');
const saveStatus = $('#saveStatus');
const explanationStatus = $('#explanationStatus');
const explanationResult = $('#explanationResult');
const explanationStyle = $('#explanationStyle');
const explanationOverview = $('#explanationOverview');
const explanationReasons = $('#explanationReasons');
const explanationLessonTitle = $('#explanationLessonTitle');
const explanationLessonContent = $('#explanationLessonContent');
const explanationSuggestions = $('#explanationSuggestions');
const explanationStale = $('#explanationStale');

let state = {
  bpm: 120,
  running: false,
  accent: true,
  uiPosition: 0,
  sequenceStep: 0,
  padEvent: 0,
  lastPad: 0,
};
let pattern = [0, 0, 0, 0, 0, 0];
let deviceBpm = 120;
let detectedBpm = null;
let selectedBpm = 120;
let commitBpm = null;
let tempoPhase = 'manual';
let tempoDetection = null;
let patternDirty = false;
let patternInFlight = false;
let patternQueued = false;
let sequencerAvailable = false;
let triggerAvailable = false;
let recordingAvailable = false;
let hardwareCaptureAvailable = false;
let revisionCommitAvailable = false;
let captureReadySent = false;
let deviceCaptureReady = false;
let captureReadyTransaction = null;
let serialPort = null;
let reader = null;
let writer = null;
let readLoopPromise = null;
let closing = false;
let lineBuffer = '';
let lastPadEvent = 0;
const patternAckGate = new PatternAckGate();
const recordingBoundaryGate = new RecordingBoundaryGate();
let aiController = null;
let lastApplyHardwareConfirmed = false;
let recordingPhase = 'idle';
let recordedPadEvents = [];
let recordedEventSnapshot = [];
let recordingStart = null;
let storageDirty = false;
let explanationLoading = false;
let explanationPayload = null;
let explanationSourceRevision = null;
let explanationRequestSequence = 0;
let explanationLoadingStartedAt = null;
let explanationLoadingTimer = null;
let patternApproximateQuantization = false;
let recordingTraceSessionId = null;
let recordingTraceSequence = 0;
let lastTracedDeviceState = '';
let lastTracedRecordControlState = '';
const stateWaiters = new Set();
const encoder = new TextEncoder();
const decoder = new TextDecoder();
const patternRevisions = new PatternRevisionStore();

function createRecordingTraceSession() {
  const randomPart = globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  recordingTraceSessionId = `recording-${randomPart}`;
  recordingTraceSequence = 0;
  lastTracedDeviceState = '';
  lastTracedRecordControlState = '';
}

function ensureRecordingTraceSession() {
  if (!recordingTraceSessionId) createRecordingTraceSession();
}

function traceRecording(stage, payload = {}) {
  if (!recordingTraceSessionId) return;
  const event = {
    sessionId: recordingTraceSessionId,
    sequence: recordingTraceSequence++,
    stage,
    clientTimeMs: Date.now(),
    payload,
  };
  console.info('[EasyInput recording trace]', event);
  void fetch(RECORDING_TRACE_ENDPOINT, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(event),
    keepalive: true,
  }).catch(() => {
    // Diagnostics must never interrupt hardware recording or playback.
  });
}

function traceDeviceState(message) {
  if (!recordingTraceSessionId) return;
  const payload = {
    bpm: Number(message.bpm),
    running: Boolean(message.running),
    sequenceStep: Number(message.sequenceStep) + 1,
    uiPosition: Number(message.uiPosition) + 1,
    pattern: Array.isArray(message.pattern)
      ? message.pattern.map((value) => Number(value) & 0xffff)
      : null,
    patternRevision: Number(message.patternRevision),
    captureState: String(message.captureState || 'unknown'),
    captureReady: Boolean(message.captureReady),
    metronomeClickExpected: false,
  };
  const signature = JSON.stringify(payload);
  if (signature === lastTracedDeviceState) return;
  lastTracedDeviceState = signature;
  traceRecording('device_state', payload);
}

function recordControlSnapshot() {
  const canStopRecording = recordingPhase === 'recording';
  const blockers = [];
  if (!canStopRecording) {
    if (!recordingAvailable) blockers.push('recording_unavailable');
    if (patternInFlight) blockers.push('pattern_sync_in_flight');
    if (aiController?.phase === 'applying') blockers.push('ai_pattern_applying');
    if (recordingLocksControls()) blockers.push(`recording_phase_${recordingPhase}`);
    if (state.running) blockers.push('playback_running');
  }
  return {
    disabled: canStopRecording ? false : blockers.length > 0,
    action: canStopRecording ? 'stop' : 'start',
    blockers,
    connected: Boolean(serialPort && writer),
    recordingAvailable,
    recordingPhase,
    stateRunning: Boolean(state.running),
    patternInFlight,
    patternQueued,
    patternDirty,
    storageDirty,
    hasPattern: hasPattern(),
    currentRevision: patternRevisions.currentRevision,
    synced: patternRevisions.isSynced,
    aiPhase: aiController?.phase || 'unavailable',
  };
}

function traceRecordControlState(trigger = 'refresh') {
  const payload = recordControlSnapshot();
  const signature = JSON.stringify(payload);
  if (signature === lastTracedRecordControlState) return;
  ensureRecordingTraceSession();
  lastTracedRecordControlState = signature;
  traceRecording('record_button_state', { trigger, ...payload });
}

function waitForCaptureReadyAck(timeoutMs = COMMAND_TIMEOUT_MS) {
  if (captureReadyTransaction) return captureReadyTransaction.promise;
  let resolvePromise;
  let rejectPromise;
  const promise = new Promise((resolve, reject) => {
    resolvePromise = resolve;
    rejectPromise = reject;
  });
  const transaction = {
    promise,
    timeout: null,
    resolve: (message) => {
      clearTimeout(transaction.timeout);
      if (captureReadyTransaction === transaction) captureReadyTransaction = null;
      deviceCaptureReady = true;
      captureReadySent = true;
      resolvePromise(message);
    },
    reject: (error) => {
      clearTimeout(transaction.timeout);
      if (captureReadyTransaction === transaction) captureReadyTransaction = null;
      deviceCaptureReady = false;
      captureReadySent = false;
      rejectPromise(error);
    },
  };
  transaction.timeout = setTimeout(() => {
    transaction.reject(new AiPatternError(
      'protocol_timeout',
      '硬件未确认录制就绪状态。',
    ));
  }, timeoutMs);
  captureReadyTransaction = transaction;
  return promise;
}

function rejectCaptureReady(error) {
  if (!captureReadyTransaction) return false;
  captureReadyTransaction.reject(error);
  return true;
}

async function ensureCaptureReady({ force = false } = {}) {
  if (!recordingAvailable || !writer) {
    throw new AiPatternError('protocol_error', '设备尚未具备录制就绪能力。');
  }
  if (!force && deviceCaptureReady) return true;
  if (captureReadyTransaction) {
    await captureReadyTransaction.promise;
    return true;
  }
  const ack = waitForCaptureReadyAck();
  captureReadySent = true;
  traceRecording('capture_ready_requested', { force, deviceCaptureReady });
  try {
    await sendCommand('CAPTURE READY 1', true);
    await ack;
    return true;
  } catch (error) {
    rejectCaptureReady(error);
    try { await ack; } catch (_) { /* consume rejected readiness waiter */ }
    throw error;
  }
}

function buildInterface() {
  instruments.forEach((instrument, index) => {
    const button = document.createElement('button');
    button.className = 'pad-card';
    button.type = 'button';
    button.disabled = true;
    button.dataset.pad = index;
    button.style.setProperty('--pad', instrument.color);
    button.setAttribute('aria-label', `${instrument.key} ${instrument.name}，点击试听`);
    button.innerHTML = `<span class="pad-key">${instrument.key}</span><span class="pad-name">${instrument.name}</span>`;
    button.addEventListener('click', () => {
      pulsePad(index);
      void sendCommand(`TRIGGER ${index + 1}`);
    });
    padGrid.append(button);
  });

  const corner = document.createElement('div');
  corner.className = 'corner-label';
  corner.textContent = 'SOUND / STEP';
  sequenceGrid.append(corner);
  for (let step = 0; step < 16; step += 1) {
    const label = document.createElement('div');
    label.className = `step-number${step % 4 === 0 ? ' bar' : ''}`;
    label.textContent = String(step + 1).padStart(2, '0');
    sequenceGrid.append(label);
  }
  instruments.forEach((instrument, pad) => {
    const label = document.createElement('div');
    label.className = 'track-label';
    label.style.setProperty('--pad', instrument.color);
    label.innerHTML = `<span class="track-dot"></span><span>${instrument.key} · ${instrument.name}</span>`;
    sequenceGrid.append(label);
    for (let step = 0; step < 16; step += 1) {
      const button = document.createElement('button');
      button.className = 'step';
      button.type = 'button';
      button.disabled = true;
      button.dataset.pad = pad;
      button.dataset.step = step;
      button.style.setProperty('--pad', instrument.color);
      button.setAttribute('aria-label', `${instrument.name} 第 ${step + 1} 步`);
      button.setAttribute('aria-pressed', 'false');
      button.addEventListener('click', () => {
        setPatternStep(pad, step, !(pattern[pad] & (1 << step)), true);
      });
      sequenceGrid.append(button);
    }
  });
}

function pulsePad(index) {
  const pad = padGrid.querySelector(`[data-pad="${index}"]`);
  if (!pad) return;
  pad.classList.remove('hit');
  void pad.offsetWidth;
  pad.classList.add('hit');
  setTimeout(() => pad.classList.remove('hit'), 150);
}

function renderPattern() {
  document.querySelectorAll('.step').forEach((button) => {
    const pad = Number(button.dataset.pad);
    const step = Number(button.dataset.step);
    const on = Boolean(pattern[pad] & (1 << step));
    button.classList.toggle('on', on);
    button.setAttribute('aria-pressed', String(on));
  });
}

function setPatternStatus(label, isError = false) {
  patternStatus.textContent = label;
  patternStatus.classList.toggle('error', isError);
}

function hasPattern() {
  return pattern.some((mask) => mask !== 0);
}

function recordingLocksControls() {
  return ['starting', 'recording', 'stopping', 'quantizing'].includes(recordingPhase);
}

function controlsLocked() {
  return (
    patternInFlight
    || aiController?.phase === 'applying'
    || recordingLocksControls()
  );
}

function markPatternChanged(source = 'manual') {
  const snapshot = patternRevisions.update({
    bpm: selectedBpm,
    masks: pattern,
    source,
    approximateQuantization: patternApproximateQuantization,
  });
  storageDirty = true;
  patternVersion.textContent = `Pattern v${snapshot.revision}`;
  saveStatus.textContent = '有未保存修改';
  saveStatus.classList.remove('success');
  if (explanationPayload) {
    explanationStale.hidden = explanationSourceRevision === snapshot.revision;
    if (!explanationStale.hidden) {
      explanationStale.textContent = `本解释对应 v${explanationSourceRevision}，当前 Pattern 已更新至 v${snapshot.revision}。`;
    }
  }
  return snapshot;
}

function formatSeconds(milliseconds) {
  const numeric = Number(milliseconds);
  if (!Number.isFinite(numeric) || numeric < 0) return '—';
  return `${(numeric / 1000).toFixed(1)} 秒`;
}

function renderTempo() {
  let value = selectedBpm;
  let mode = 'MANUAL';
  if (['starting', 'recording', 'stopping'].includes(recordingPhase)) {
    value = '--';
    mode = `FREE PLAY · ${recordedPadEvents.length} HITS`;
  } else if (tempoPhase === 'detecting') {
    value = '--';
    mode = 'AUTO · 检测中';
  } else if (tempoPhase === 'detected') {
    value = selectedBpm;
    mode = `检测完成 · ${selectedBpm} BPM`;
  } else if (tempoPhase === 'syncing') {
    value = commitBpm ?? selectedBpm;
    mode = `SYNC · v${patternRevisions.currentRevision}`;
  } else if (state.running) {
    value = deviceBpm;
    mode = 'LIVE';
  }
  bpmValue.textContent = value;
  tempoState.textContent = mode;
}

function refreshControlAvailability() {
  const locked = controlsLocked();
  clearPattern.disabled = locked;
  document.querySelectorAll('.step').forEach((button) => {
    button.disabled = locked;
  });
  document.querySelectorAll('.pad-card').forEach((button) => {
    button.disabled = !triggerAvailable || recordingLocksControls();
  });
  applyAiPattern.disabled = !(
    aiController?.candidate
    && !locked
  );
  toggle.disabled = !(serialPort && writer) || locked;
  slower.disabled = !(serialPort && writer && state.running) || locked;
  faster.disabled = !(serialPort && writer && state.running) || locked;
  const canStopRecording = recordingPhase === 'recording';
  recordPattern.disabled = canStopRecording
    ? false
    : !recordingAvailable || locked || state.running;
  recordPattern.setAttribute('aria-label', canStopRecording ? '停止录制' : '开始录制');
  recordPattern.setAttribute('aria-pressed', String(canStopRecording));
  recordPattern.classList.toggle('recording', canStopRecording);
  traceRecordControlState('control_refresh');
  recordPattern.title = recordPattern.disabled
    ? `暂不可用：${recordControlSnapshot().blockers.join(', ')}`
    : canStopRecording ? '停止录制' : '开始录制';
  savePatternButton.disabled = recordingLocksControls() || !hasPattern() || !storageDirty;
  explainPattern.disabled = explanationLoading || locked || !hasPattern() || Boolean(
    serialPort && !patternRevisions.isSynced,
  );
  generatePattern.disabled = (
    aiController?.phase === 'generating'
    || aiController?.phase === 'applying'
    || recordingLocksControls()
    || explanationLoading
  );
}

function setProtocolFeatures(
  sequencer,
  trigger,
  padEvents,
  hardwareCapture,
  revisionCommit,
  message,
) {
  const becameAvailable = !sequencerAvailable && sequencer;
  sequencerAvailable = sequencer;
  triggerAvailable = trigger;
  hardwareCaptureAvailable = hardwareCapture;
  revisionCommitAvailable = revisionCommit;
  recordingAvailable = padEvents && hardwareCapture && revisionCommit;
  refreshControlAvailability();
  if (!sequencer) setPatternStatus(message, Boolean(serialPort));
  else if (becameAvailable && !patternDirty) setPatternStatus('音序器已就绪');
  return becameAvailable;
}

function applyCapabilities(message) {
  const capabilities = new Set(Array.isArray(message.capabilities) ? message.capabilities : []);
  const compatible = Number(message.protocolVersion) >= REQUIRED_PROTOCOL_VERSION;
  const sequencer = compatible && capabilities.has('pattern') && capabilities.has('sequencer');
  const trigger = compatible && capabilities.has('trigger');
  const padEvents = compatible && capabilities.has('padEvents');
  const hardwareCapture = compatible && capabilities.has('hardwareCaptureButton');
  const revisionCommit = compatible && capabilities.has('revisionCommit');
  const unavailableMessage = serialPort
    ? '当前固件不支持音序器，请升级固件'
    : '连接设备后同步';
  const becameAvailable = setProtocolFeatures(
    sequencer,
    trigger,
    padEvents,
    hardwareCapture,
    revisionCommit,
    unavailableMessage,
  );
  deviceCaptureReady = message.captureReady === true;
  if (!deviceCaptureReady) captureReadySent = false;
  if ((!padEvents || !hardwareCapture || !revisionCommit) && serialPort && !recordingLocksControls()) {
    recordStatus.textContent = '当前固件不支持实体演奏录制，请升级并重新烧录。';
    recordStatus.classList.add('error');
  } else if (!recordingAvailable && !serialPort && !recordingLocksControls()) {
    recordStatus.textContent = '连接支持录制的固件后开始。';
    recordStatus.classList.remove('error', 'success');
  } else if (recordingAvailable && recordingPhase === 'idle') {
    recordStatus.textContent = '设备已支持 S8 / 网页录制；开始后自由演奏。';
    recordStatus.classList.remove('error');
  }
  if (recordingAvailable && !deviceCaptureReady && writer) {
    void ensureCaptureReady().catch((error) => {
      if (!recordingLocksControls()) {
        recordStatus.textContent = `录制就绪失败：${error.message}`;
        recordStatus.classList.add('error');
      }
    });
  }
  if (becameAvailable && patternDirty) void syncPattern();
}

function rejectPendingTransactions(error) {
  patternAckGate.reject(error);
  recordingBoundaryGate.reject(error);
  rejectCaptureReady(error);
  for (const waiter of stateWaiters) waiter.reject(error);
  stateWaiters.clear();
  if (recordingLocksControls()) {
    recordingPhase = 'error';
    recordStatus.textContent = `${error.message} 本次录制未写入音序器。`;
    recordStatus.classList.add('error');
  }
}

function waitForState(predicate, message) {
  if (predicate(state)) return Promise.resolve(state);
  return new Promise((resolve, reject) => {
    const waiter = {
      predicate,
      resolve: (next) => {
        clearTimeout(waiter.timeout);
        stateWaiters.delete(waiter);
        resolve(next);
      },
      reject: (error) => {
        clearTimeout(waiter.timeout);
        stateWaiters.delete(waiter);
        reject(error);
      },
      timeout: null,
    };
    waiter.timeout = setTimeout(() => {
      waiter.reject(new AiPatternError('protocol_timeout', message));
    }, COMMAND_TIMEOUT_MS);
    stateWaiters.add(waiter);
  });
}

function notifyStateWaiters() {
  for (const waiter of [...stateWaiters]) {
    if (waiter.predicate(state)) waiter.resolve(state);
  }
}

function waitForPatternAck(snapshot) {
  return patternAckGate.wait(COMMAND_TIMEOUT_MS, (message) => (
    Number(message.revision) === snapshot.revision
    && Number(message.bpm) === snapshot.bpm
    && Array.isArray(message.pattern)
    && message.pattern.length === snapshot.masks.length
    && message.pattern.every(
      (value, index) => (Number(value) & 0xffff) === snapshot.masks[index],
    )
  ));
}

async function transmitPattern(snapshot) {
  if (!serialPort || !writer) {
    throw new AiPatternError('transport_error', '串口未连接。');
  }
  if (!sequencerAvailable || !revisionCommitAvailable) {
    throw new AiPatternError('protocol_error', '当前固件不支持 revision COMMIT 命令。');
  }
  const ack = waitForPatternAck(snapshot);
  try {
    traceRecording('pattern_sync_sent', {
      revision: snapshot.revision,
      bpm: snapshot.bpm,
      masks: snapshot.masks,
    });
    await sendCommand(
      `COMMIT ${snapshot.revision} ${snapshot.bpm} ${snapshot.masks.join(' ')}`,
      true,
    );
  } catch (error) {
    patternAckGate.reject(error);
    try { await ack; } catch (_) { /* consume the rejected ACK waiter */ }
    throw error;
  }
  const message = await ack;
  if (!patternRevisions.acknowledge({
    revision: Number(message.revision),
    bpm: Number(message.bpm),
    masks: message.pattern,
  })) {
    throw new AiPatternError('protocol_stale', '硬件返回了旧版本或不一致的 COMMIT ACK。');
  }
}

async function syncPattern({ throwOnError = false } = {}) {
  if (!sequencerAvailable || !revisionCommitAvailable || !writer) {
    setPatternStatus('已在网页修改，连接设备后同步');
    refreshControlAvailability();
    return false;
  }
  patternDirty = true;
  if (patternInFlight) {
    patternQueued = true;
    return;
  }
  patternInFlight = true;
  patternQueued = false;
  refreshControlAvailability();
  const snapshot = patternRevisions.commitSnapshot();
  commitBpm = snapshot.bpm;
  tempoPhase = 'syncing';
  renderTempo();
  setPatternStatus(`正在同步 Pattern v${snapshot.revision}…`);
  try {
    await transmitPattern(snapshot);
    if (patternQueued) {
      patternInFlight = false;
      tempoPhase = tempoDetection ? 'detected' : 'manual';
      refreshControlAvailability();
      void syncPattern();
    } else {
      patternInFlight = false;
      patternDirty = patternRevisions.currentRevision !== snapshot.revision;
      tempoPhase = tempoDetection ? 'detected' : 'manual';
      commitBpm = null;
      refreshControlAvailability();
      renderTempo();
      setPatternStatus(`Pattern v${snapshot.revision} 已同步到硬件`);
      if (aiController?.phase === 'applied') {
        lastApplyHardwareConfirmed = true;
        renderAiState(aiController.snapshot());
      }
      return true;
    }
  } catch (error) {
    patternInFlight = false;
    patternQueued = patternDirty;
    tempoPhase = tempoDetection ? 'detected' : 'manual';
    commitBpm = null;
    renderTempo();
    refreshControlAvailability();
    setPatternStatus(`同步失败：${error.message}`, true);
    if (throwOnError) throw error;
    return false;
  }
  return true;
}

function setPatternStep(pad, step, on, send) {
  if (on) pattern[pad] |= 1 << step;
  else pattern[pad] &= ~(1 << step);
  renderPattern();
  markPatternChanged('manual_edit');
  if (send) {
    patternDirty = true;
    void syncPattern();
  }
}

function setPattern(next, send = true, source = 'manual_edit') {
  pattern = next.map((value) => Number(value) & 0xffff);
  renderPattern();
  markPatternChanged(source);
  if (send) {
    patternDirty = true;
    void syncPattern();
  }
}

function setRecordingError(error) {
  recordingPhase = 'error';
  const message = error?.message || '录制失败，请重试。';
  recordStatus.textContent = message;
  recordStatus.classList.add('error');
  refreshControlAvailability();
}

function activateRecording(boundary) {
  recordingStart = boundary;
  recordedPadEvents = [];
  recordedEventSnapshot = [];
  tempoDetection = null;
  detectedBpm = null;
  tempoPhase = 'free';
  patternApproximateQuantization = false;
  pattern = [0, 0, 0, 0, 0, 0];
  patternDirty = true;
  markPatternChanged('recording_clear');
  renderPattern();
  sequenceSource.textContent = '实体录制中 · 等待首个 Pad 作为第 1 步';
  explanationResult.hidden = true;
  recordingPhase = 'recording';
  recordStatus.textContent = '正在录制 · 已记录 0 次敲击';
  recordStatus.classList.remove('error', 'success');
  renderTempo();
  refreshControlAvailability();
}

async function startPadRecording() {
  if (!serialPort || !writer) {
    setRecordingError(new PadRecordingError('transport_error', '请先连接设备。'));
    return;
  }
  if (!recordingAvailable) {
    setRecordingError(new PadRecordingError('protocol_error', '当前固件不支持实体演奏录制。'));
    return;
  }
  if (state.running) {
    setRecordingError(new PadRecordingError('busy', '请先停止音序器播放，再开始录制。'));
    return;
  }
  ensureRecordingTraceSession();
  traceRecording('record_start_requested', {
    bpm: selectedBpm,
    patternBefore: pattern.map((value) => Number(value) & 0xffff),
  });
  recordingPhase = 'starting';
  recordedPadEvents = [];
  recordingStart = null;
  recordStatus.textContent = '正在确认硬件录制就绪状态…';
  recordStatus.classList.remove('error', 'success');
  refreshControlAvailability();
  let boundary = null;
  try {
    await ensureCaptureReady({ force: true });
    recordStatus.textContent = '正在等待硬件确认录制起点…';
    boundary = recordingBoundaryGate.wait('started', COMMAND_TIMEOUT_MS);
    await sendCommand('RECORD START', true);
    const started = await boundary;
    recordingStart = started;
    if (recordingPhase !== 'recording') {
      traceRecording('record_boundary_started', recordingStart);
      activateRecording(started);
    }
  } catch (error) {
    traceRecording('recording_error', {
      phase: 'start',
      type: error?.type || 'unknown',
      message: error?.message || '开始录制失败',
    });
    recordingBoundaryGate.reject(error);
    if (boundary) {
      try { await boundary; } catch (_) { /* consume rejected boundary */ }
    }
    void sendCommand('RECORD STOP');
    setRecordingError(error);
  }
}

async function processRecordingStop(stop) {
  try {
    traceRecording('record_boundary_stopped', stop);
    recordingPhase = 'quantizing';
    tempoPhase = 'detecting';
    recordStatus.textContent = '事件核对完成，正在检测演奏速度…';
    renderTempo();
    refreshControlAvailability();
    const verified = verifyRecording(recordedPadEvents, recordingStart, stop);
    recordedEventSnapshot = verified.events.map((event) => ({ ...event }));
    traceRecording('recording_verified', {
      start: verified.start,
      stop: verified.stop,
      events: verified.events,
    });
    await new Promise((resolve) => requestAnimationFrame(resolve));
    tempoDetection = detectTempoCandidates(recordedEventSnapshot, {
      preferredBpm: deviceBpm,
    });
    detectedBpm = tempoDetection.recommendedBpm;
    selectedBpm = detectedBpm;
    tempoPhase = 'detected';
    const result = quantizePadEvents(recordedEventSnapshot, selectedBpm);
    traceRecording('pattern_quantized', {
      bpm: selectedBpm,
      tempoStatus: tempoDetection.status,
      tempoCandidates: tempoDetection.candidates.map((candidate) => ({
        bpm: candidate.bpm,
        score: candidate.score,
        acceptedCount: candidate.acceptedCount,
        ignoredCount: candidate.ignoredCount,
      })),
      sampleRateHz: 48000,
      anchorFrame: result.anchorFrame,
      framesPerStep: result.framesPerStep,
      assignments: result.assignments,
      masks: result.masks,
      acceptedCount: result.acceptedCount,
      ignoredCount: result.ignoredCount,
      tracks: instruments.map(({ key, name }) => ({ key, name })),
    });
    patternApproximateQuantization = true;
    setPattern(result.masks, false, 'hardware_recording');
    sequenceSource.textContent = `录制完成 · ${selectedBpm} BPM`;
    await syncPattern({ throwOnError: true });
    recordingPhase = 'draft';
    recordStatus.textContent = `录制完成，已自动采用 ${selectedBpm} BPM。`;
    recordStatus.classList.remove('error');
    recordStatus.classList.add('success');
    renderTempo();
    refreshControlAvailability();
  } catch (error) {
    traceRecording('recording_error', {
      phase: 'stop',
      type: error?.type || 'unknown',
      message: error?.message || '停止录制失败',
    });
    tempoPhase = 'error';
    tempoDetection = null;
    pattern = [0, 0, 0, 0, 0, 0];
    renderPattern();
    renderTempo();
    void sendCommand('ABORT');
    setRecordingError(error);
  }
}

async function stopPadRecording() {
  if (recordingPhase !== 'recording') return;
  traceRecording('record_stop_requested', {
    eventCount: recordedPadEvents.length,
  });
  recordingPhase = 'stopping';
  recordStatus.textContent = '正在停止录制并核对事件…';
  renderTempo();
  refreshControlAvailability();
  const boundary = recordingBoundaryGate.wait('stopped', COMMAND_TIMEOUT_MS);
  try {
    await sendCommand('RECORD STOP', true);
    const stop = await boundary;
    await processRecordingStop(stop);
  } catch (error) {
    recordingBoundaryGate.reject(error);
    try { await boundary; } catch (_) { /* consume rejected boundary */ }
    void sendCommand('ABORT');
    setRecordingError(error);
  }
}

function saveCurrentPattern() {
  ensureRecordingTraceSession();
  traceRecording('pattern_save_requested', recordControlSnapshot());
  try {
    const serialized = serializeSavedPattern({
      name: DEFAULT_PATTERN_NAME,
      bpm: selectedBpm,
      masks: pattern,
      approximateQuantization: patternApproximateQuantization,
    });
    localStorage.setItem(RECORDING_STORAGE_KEY, serialized);
    storageDirty = false;
    saveStatus.textContent = '已保存到当前浏览器';
    saveStatus.classList.remove('error');
    saveStatus.classList.add('success');
    if (recordingPhase === 'draft' || recordingPhase === 'error') recordingPhase = 'saved';
    traceRecording('pattern_save_completed', recordControlSnapshot());
  } catch (error) {
    saveStatus.textContent = `保存失败：${error.message}`;
    saveStatus.classList.add('error');
    traceRecording('pattern_save_failed', {
      ...recordControlSnapshot(),
      message: error?.message || '保存失败',
    });
  }
  refreshControlAvailability();
}

function restoreSavedPattern() {
  let serialized;
  try {
    serialized = localStorage.getItem(RECORDING_STORAGE_KEY);
    if (!serialized) return;
    const saved = parseSavedPattern(serialized);
    pattern = saved.masks;
    selectedBpm = saved.bpm;
    detectedBpm = null;
    tempoDetection = null;
    tempoPhase = 'manual';
    patternApproximateQuantization = saved.approximateQuantization;
    patternDirty = true;
    markPatternChanged('saved_restore');
    storageDirty = false;
    sequenceSource.textContent = `已保存 · ${saved.bpm} BPM`;
    saveStatus.textContent = '已恢复浏览器中保存的 Pattern';
    saveStatus.classList.add('success');
  } catch (error) {
    saveStatus.textContent = `未能恢复保存内容：${error.message}`;
    saveStatus.classList.add('error');
  }
}

function renderExplanation(payload) {
  const explanation = payload.explanation;
  explanationResult.hidden = false;
  explanationStyle.textContent = explanation.closestStyle;
  explanationOverview.textContent = explanation.styleOverview;
  explanationReasons.replaceChildren();
  explanation.reasons.forEach((item) => {
    const row = document.createElement('li');
    const trackIndex = TRACK_IDS.indexOf(item.track);
    const label = instruments[trackIndex]?.name || item.track;
    row.textContent = `${label} 第 ${item.steps.join('、')} 步：${item.reason}`;
    explanationReasons.append(row);
  });
  explanationLessonTitle.textContent = explanation.styleLesson.title;
  explanationLessonContent.textContent = explanation.styleLesson.content;
  explanationSuggestions.replaceChildren();
  explanation.improvementSuggestions.forEach((item) => {
    const card = document.createElement('li');
    const title = document.createElement('strong');
    title.textContent = item.suggestion;
    const effect = document.createElement('span');
    effect.textContent = `听感：${item.expectedEffect}`;
    const lesson = document.createElement('span');
    lesson.textContent = `练习：${item.learningPoint}`;
    card.append(title, effect, lesson);
    explanationSuggestions.append(card);
  });
  explanationStale.hidden = (
    explanationSourceRevision === patternRevisions.currentRevision
  );
}

function clearPatternExplanation() {
  stopExplanationLoadingStatus();
  explanationPayload = null;
  explanationSourceRevision = null;
  explanationStatus.textContent = '';
  explanationStatus.classList.remove('error', 'success', 'loading');
  explanationResult.hidden = true;
  explanationStale.hidden = true;
}

function stopExplanationLoadingStatus() {
  if (explanationLoadingTimer !== null) {
    window.clearInterval(explanationLoadingTimer);
    explanationLoadingTimer = null;
  }
  explanationLoadingStartedAt = null;
  explanationStatus.classList.remove('loading');
}

function startExplanationLoadingStatus() {
  stopExplanationLoadingStatus();
  explanationLoadingStartedAt = performance.now();
  explanationStatus.textContent = 'AI正在分析你的鼓点';
  explanationStatus.classList.remove('error', 'success');
  explanationStatus.classList.add('loading');
}

async function explainCurrentPattern() {
  const requestId = `explain-${++explanationRequestSequence}`;
  const request = patternRevisions.beginAiRequest(requestId);
  const sourceMasks = request.snapshot.masks;
  const sourceBpm = request.snapshot.bpm;
  explanationLoading = true;
  startExplanationLoadingStatus();
  refreshControlAvailability();
  try {
    const payload = await requestPatternExplanation(
      (...args) => fetch(...args),
      sourceMasks,
      sourceBpm,
      request.snapshot.approximateQuantization,
    );
    const resolution = patternRevisions.resolveAiRequest(request);
    if (!resolution.accepted) return;
    explanationPayload = payload;
    explanationSourceRevision = request.sourceRevision;
    renderExplanation(payload);
    stopExplanationLoadingStatus();
    const elapsed = formatSeconds(payload.latencyMs?.total);
    explanationStatus.textContent = resolution.stale
      ? `AI 解释完成，用时 ${elapsed}；Pattern 已更新，这份解释对应修改前版本。`
      : `AI 解释完成，用时 ${elapsed}`;
    explanationStatus.classList.add('success');
  } catch (error) {
    const normalized = error instanceof PatternExplanationError
      ? error
      : new PatternExplanationError('client_error', '网页处理 AI 解释时发生错误。');
    stopExplanationLoadingStatus();
    explanationStatus.textContent = `AI 解释失败：${normalized.message} Pattern 和硬件播放不受影响，请重试。`;
    explanationStatus.classList.add('error');
  } finally {
    stopExplanationLoadingStatus();
    explanationLoading = false;
    refreshControlAvailability();
  }
}

function render(next) {
  const previousPadEvent = state.padEvent;
  state = { ...state, ...next };
  deviceBpm = Number(state.bpm) || deviceBpm;
  renderTempo();
  toggle.classList.toggle('running', state.running);
  toggle.setAttribute('aria-label', state.running ? '停止播放' : '开始播放');
  toggle.title = state.running ? '停止播放' : '开始播放';
  toggle.setAttribute('aria-pressed', String(state.running));
  squares.forEach((square, index) => {
    const on = state.running && index === state.uiPosition;
    square.classList.toggle('active', on);
    square.classList.toggle('accent', on && state.accent);
  });
  document.querySelectorAll('.step').forEach((button) => {
    button.classList.toggle(
      'playhead',
      state.running && Number(button.dataset.step) === state.sequenceStep,
    );
  });
  padGrid.querySelectorAll('.pad-card').forEach((button, index) => {
    const active = state.running && Boolean(pattern[index] & (1 << state.sequenceStep));
    button.classList.toggle('sequence-hit', active);
  });
  if (
    next.padEvent !== undefined
    && next.padEvent !== previousPadEvent
    && next.padEvent !== lastPadEvent
  ) {
    lastPadEvent = next.padEvent;
    pulsePad(Number(next.lastPad));
  }
  notifyStateWaiters();
}

function setConnection(status, label) {
  connectDevice.classList.toggle('online', status === 'online');
  connectDevice.classList.toggle('error', status === 'error');
  connectionText.textContent = label;
  const online = status === 'online';
  slower.disabled = !online;
  faster.disabled = !online;
  refreshControlAvailability();
}

function handleLine(line) {
  if (!line.trim()) return;
  try {
    const message = JSON.parse(line);
    if (message.type === 'state') {
      applyCapabilities(message);
      const messageBpm = Number(message.bpm) || deviceBpm;
      deviceBpm = messageBpm;
      if (message.running && messageBpm !== selectedBpm && !recordingLocksControls()) {
        selectedBpm = messageBpm;
        markPatternChanged('tempo_live');
        patternDirty = false;
        patternRevisions.acknowledge({
          revision: patternRevisions.currentRevision,
          bpm: selectedBpm,
          masks: pattern,
        });
      }
      if (
        Array.isArray(message.pattern)
        && message.pattern.length === 6
        && !patternDirty
        && !patternInFlight
        && aiController?.phase !== 'applying'
      ) {
        const incomingPattern = message.pattern.map((value) => Number(value) & 0xffff);
        const deviceDiffers = messageBpm !== selectedBpm || incomingPattern.some(
          (value, index) => value !== pattern[index],
        );
        if (deviceDiffers) {
          pattern = incomingPattern;
          patternApproximateQuantization = false;
          selectedBpm = messageBpm;
          markPatternChanged('device_restore');
          storageDirty = false;
          patternDirty = false;
        }
        patternRevisions.acknowledge({
          revision: patternRevisions.currentRevision,
          bpm: selectedBpm,
          masks: pattern,
        });
        renderPattern();
      }
      render(message);
      traceDeviceState(message);
      return;
    }
    if (message.type === 'ack' && message.command === 'COMMIT') {
      traceRecording('pattern_ack_received', {
        command: 'COMMIT',
        revision: message.revision,
        bpm: message.bpm,
        pattern: message.pattern,
      });
      patternAckGate.acknowledge(message);
      return;
    }
    if (message.type === 'ack' && message.command === 'CAPTURE READY') {
      if (!closing) {
        deviceCaptureReady = true;
        captureReadySent = true;
        traceRecording('capture_ready_ack_received');
        captureReadyTransaction?.resolve(message);
      }
      return;
    }
    if (message.type === 'ack' && message.command === 'ABORT') {
      deviceCaptureReady = false;
      captureReadySent = false;
      return;
    }
    if (message.type === 'pad') {
      try {
        const event = validatePadEvent(message);
        pulsePad(event.track);
        if (recordingPhase === 'recording' || recordingPhase === 'stopping') {
          recordedPadEvents.push(event);
          traceRecording('pad_received', {
            ...event,
            key: instruments[event.track]?.key || null,
            name: instruments[event.track]?.name || null,
          });
          recordStatus.textContent = `正在录制 · 已记录 ${recordedPadEvents.length} 次敲击`;
        }
      } catch (error) {
        if (recordingLocksControls()) {
          traceRecording('recording_error', {
            phase: 'pad',
            type: error?.type || 'unknown',
            message: error?.message || 'Pad 事件不合法',
          });
          setRecordingError(error);
        }
      }
      return;
    }
    if (message.type === 'record') {
      try {
        const boundary = validateRecordBoundary(message, message.phase);
        if (boundary.phase === 'started' && recordingPhase === 'starting') {
          traceRecording('record_boundary_started', boundary);
          activateRecording(boundary);
        }
        if (recordingBoundaryGate.resolve(message)) return;
        if (boundary.phase === 'started' && boundary.origin === 's8') {
          ensureRecordingTraceSession();
          traceRecording('record_start_requested', { origin: 's8' });
          traceRecording('record_boundary_started', boundary);
          activateRecording(boundary);
        } else if (
          boundary.phase === 'stopped'
          && boundary.origin === 's8'
          && recordingPhase === 'recording'
        ) {
          recordingPhase = 'stopping';
          recordStatus.textContent = 'S8 已停止录制，正在核对事件…';
          void processRecordingStop(boundary);
        }
      } catch (error) {
        setRecordingError(error);
      }
      return;
    }
    if (message.type === 'error') {
      const detail = String(message.message || '设备拒绝了命令');
      const error = new AiPatternError('protocol_error', `设备拒绝命令：${detail}`);
      if (captureReadyTransaction) {
        rejectCaptureReady(error);
      } else if (patternAckGate.hasPending) {
        patternAckGate.reject(error);
      } else if (recordingBoundaryGate.hasPending) {
        recordingBoundaryGate.reject(error);
      } else {
        setPatternStatus(`设备提示：${detail}`, true);
      }
      for (const waiter of [...stateWaiters]) waiter.reject(error);
      // A protocol error does not mean that the serial transport is disconnected.
    }
  } catch (_) {
    // Ignore unrelated serial debug output and continue reading the port.
  }
}

function handleBytes(bytes) {
  lineBuffer += decoder.decode(bytes, { stream: true });
  const lines = lineBuffer.split(/\r?\n/);
  lineBuffer = lines.pop() ?? '';
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
  } catch (_) {
    if (!closing) setConnection('error', '串口读取中断');
  } finally {
    if (reader) {
      reader.releaseLock();
      reader = null;
    }
    if (!closing && serialPort === port) {
      if (writer) {
        writer.releaseLock();
        writer = null;
      }
      try { await port.close(); } catch (_) { /* already closed */ }
      serialPort = null;
      patternInFlight = false;
      patternQueued = patternDirty;
      rejectPendingTransactions(new AiPatternError('transport_error', '串口连接已中断。'));
      captureReadySent = false;
      deviceCaptureReady = false;
      patternRevisions.markDisconnected();
      setProtocolFeatures(false, false, false, false, false, '连接设备后同步');
      setConnection('offline', '重新连接');
    }
  }
}

async function sendCommand(command, throwOnError = false) {
  if (!writer) {
    const error = new AiPatternError('transport_error', '串口未连接。');
    if (throwOnError) throw error;
    return false;
  }
  try {
    await writer.write(encoder.encode(`${command}\n`));
    return true;
  } catch (_) {
    const error = new AiPatternError('transport_error', '串口写入失败。');
    setConnection('error', '串口写入失败');
    void disconnectSerial('重新连接');
    if (throwOnError) throw error;
    return false;
  }
}

async function disconnectSerial(label = '连接设备') {
  if (!serialPort) return;
  closing = true;
  const port = serialPort;
  if (writer && captureReadySent) {
    try { await sendCommand('CAPTURE READY 0', true); } catch (_) { /* disconnect continues */ }
  }
  rejectPendingTransactions(new AiPatternError('transport_error', '串口已断开。'));
  if (reader) {
    try { await reader.cancel(); } catch (_) { /* already cancelled */ }
  }
  if (readLoopPromise) {
    try { await readLoopPromise; } catch (_) { /* read loop already ended */ }
  }
  if (writer) {
    writer.releaseLock();
    writer = null;
  }
  try { await port.close(); } catch (_) { /* already closed */ }
  serialPort = null;
  readLoopPromise = null;
  lineBuffer = '';
  patternInFlight = false;
  patternQueued = patternDirty;
  captureReadySent = false;
  deviceCaptureReady = false;
  patternRevisions.markDisconnected();
  closing = false;
  setProtocolFeatures(false, false, false, false, false, '连接设备后同步');
  setConnection('offline', label);
}

async function connectSerial() {
  if (serialPort) {
    await disconnectSerial();
    return;
  }
  try {
    captureReadySent = false;
    deviceCaptureReady = false;
    setProtocolFeatures(false, false, false, false, false, '正在确认固件能力…');
    setConnection('offline', '选择串口…');
    const port = await navigator.serial.requestPort({ filters: [{ usbVendorId: 0x303a }] });
    await port.open({ baudRate: 115200, bufferSize: 1024 });
    serialPort = port;
    writer = port.writable.getWriter();
    readLoopPromise = readSerial(port);
    setConnection('online', '设备在线 · 点击断开');
    await sendCommand('STATE');
  } catch (error) {
    serialPort = null;
    writer = null;
    setProtocolFeatures(false, false, false, false, false, '连接设备后同步');
    setConnection(
      error.name === 'NotFoundError' ? 'offline' : 'error',
      error.name === 'NotFoundError' ? '连接设备' : '连接失败 · 重试',
    );
  }
}

async function applyCandidate(candidate) {
  const masks = patternToMasks(candidate);
  pattern = masks;
  patternApproximateQuantization = false;
  selectedBpm = candidate.bpm;
  detectedBpm = null;
  tempoDetection = null;
  tempoPhase = 'manual';
  patternDirty = true;
  patternQueued = false;
  lastApplyHardwareConfirmed = false;
  sequenceSource.textContent = `AI · ${candidate.name} · ${candidate.style} · ${candidate.bpm} BPM`;
  renderPattern();
  markPatternChanged('ai_generated');
  render(state);
  refreshControlAvailability();

  if (!serialPort || !writer) {
    setPatternStatus('已填入音序器，连接设备后自动同步');
    return;
  }
  if (!sequencerAvailable || !revisionCommitAvailable) {
    throw new AiPatternError('protocol_error', '已填入音序器，但当前固件不支持 COMMIT 协议。');
  }
  await syncPattern({ throwOnError: true });
  lastApplyHardwareConfirmed = true;
}

async function togglePlayback() {
  if (patternDirty) {
    try {
      await syncPattern({ throwOnError: true });
    } catch (_) {
      return;
    }
  }
  traceRecording('playback_toggle_requested', {
    currentlyRunning: Boolean(state.running),
    bpm: selectedBpm,
    masks: pattern.map((value) => Number(value) & 0xffff),
    metronomeClickExpectedAfterToggle: false,
  });
  await sendCommand('TOGGLE');
}

function renderAiState(snapshot) {
  generatePattern.disabled = snapshot.phase === 'generating' || snapshot.phase === 'applying';
  aiStatus.classList.remove('error', 'success');
  if (snapshot.phase === 'generating') {
    clearPatternExplanation();
    aiResult.hidden = true;
    aiStatus.textContent = '正在调用 DeepSeek 并校验六轨 16 步结构…';
  } else if (snapshot.phase === 'ready' || snapshot.phase === 'applied' || snapshot.phase === 'apply_error') {
    const candidate = snapshot.candidate;
    aiResult.hidden = false;
    aiPatternTitle.textContent = candidate.name;
    const firstPass = snapshot.metadata?.firstPass?.valid;
    const repaired = snapshot.metadata?.repairAttempted;
    const totalMs = snapshot.metadata?.latencyMs?.total;
    aiPatternMeta.textContent = `${candidate.style} · ${candidate.bpm} BPM · ${formatSeconds(totalMs)}${repaired ? ' · 首答失败后已修复一次' : ''}`;
    aiPatternNote.textContent = candidate.designNote || '六轨 16 步 Pattern 已通过结构与产品约束校验。';
    if (snapshot.phase === 'ready') {
      aiStatus.textContent = firstPass
        ? '生成并校验完成，点击“应用”后填入 16 步音序器。'
        : '首答未通过，已完成一次定向修复；点击“应用”后填入音序器。';
    } else if (snapshot.phase === 'applied') {
      aiStatus.textContent = lastApplyHardwareConfirmed
        ? '已填入 16 步音序器并收到硬件 ACK；点击“开始”播放。'
        : '已填入 16 步音序器；连接设备同步后，点击“开始”播放。';
      aiStatus.classList.add('success');
    } else {
      aiStatus.textContent = `应用失败：${snapshot.error?.message || '请重试。'}`;
      aiStatus.classList.add('error');
    }
  } else if (snapshot.phase === 'applying') {
    aiStatus.textContent = serialPort
      ? '正在填入音序器、设置 BPM，并等待硬件 COMMIT ACK…'
      : '正在填入现有 16 步音序器…';
  } else if (snapshot.phase === 'error') {
    aiResult.hidden = true;
    aiStatus.textContent = `生成失败：${snapshot.error?.message || '请重试。'}`;
    aiStatus.classList.add('error');
  } else {
    aiStatus.textContent = '';
  }
  refreshControlAvailability();
}

aiController = new AiPatternController({
  fetchImpl: (...args) => fetch(...args),
  onState: renderAiState,
});

buildInterface();
restoreSavedPattern();
connectDevice.addEventListener('click', connectSerial);
toggle.addEventListener('click', () => { void togglePlayback(); });
slower.addEventListener('click', () => {
  if (!state.running) return;
  void sendCommand(`BPM ${Math.max(40, deviceBpm - 1)}`);
});
faster.addEventListener('click', () => {
  if (!state.running) return;
  void sendCommand(`BPM ${Math.min(240, deviceBpm + 1)}`);
});
clearPattern.addEventListener('click', () => {
  patternApproximateQuantization = false;
  tempoDetection = null;
  detectedBpm = null;
  tempoPhase = 'manual';
  setPattern([0, 0, 0, 0, 0, 0], true, 'manual_clear');
});
recordPattern.addEventListener('click', () => {
  if (recordingPhase === 'recording') void stopPadRecording();
  else void startPadRecording();
});
savePatternButton.addEventListener('click', saveCurrentPattern);
explainPattern.addEventListener('click', () => { void explainCurrentPattern(); });
generatePattern.addEventListener('click', async () => {
  try {
    await aiController.generate(aiPrompt.value);
  } catch (_) {
    // Controller state already contains a safe user-facing error.
  }
});
applyAiPattern.addEventListener('click', async () => {
  try {
    await aiController.apply(applyCandidate);
  } catch (_) {
    // Controller state already distinguishes hardware/protocol errors.
  }
});

if ('serial' in navigator) {
  navigator.serial.addEventListener('disconnect', (event) => {
    if (event.target === serialPort) void disconnectSerial('设备已断开');
  });
  setConnection('offline', '连接设备');
} else {
  connectDevice.disabled = true;
  setConnection('error', '浏览器不支持 Web Serial');
}
setProtocolFeatures(false, false, false, false, false, '连接设备后同步');
renderPattern();
render(state);
