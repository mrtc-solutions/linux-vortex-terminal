'use strict';

// Execute the real HUD module against a minimal DOM shim and the exact payload
// shapes returned by /api/dashboard and /api/health. This proves the tactical
// HUD renders only real telemetry (and N/A for unavailable fields) without
// fabricating values, and that it is failure-tolerant when routes are absent.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'frontend', 'hud.js'), 'utf8');

// Real, current payload shapes (captured from the live backend).
const DASHBOARD = {
  dashboard: {
    ai: { state: 'unavailable', endpoint: 'http://127.0.0.1:11434', models_installed: 0, strategy: 'sequential', multi_model: false, message: 'Connection refused' },
    host: { distribution: { id: 'debian', pretty_name: 'Debian GNU/Linux 12 (bookworm)' }, architecture: 'x86_64' },
    offline: false,
    privacy_mode: 'local',
    engagements: { active: 0, total: 0 },
    system: {
      cpu: { processors: 2, loadavg: [0.0, 0.0, 0.0] },
      memory: { total_mb: 3939 },
      disk: { path: '/home/user/linux-vortex-terminal', used_percent: 5 },
      network: { hostname: 'e2b.local', interfaces: 2, ip_tool: 'installed', socket_tool: 'installed' },
    },
    session: { total: 0, running: 0, sessions: [] },
  },
};
const HEALTH = {
  backend: 'online',
  health: {
    components: {
      core: { state: 'healthy', version: '0.2.22' },
      database: { state: 'healthy' },
      terminal_engine: { state: 'healthy' },
      agent_council: { state: 'healthy', available: '0/0', agents: [] },
      local_ai: { state: 'unavailable' },
      ollama: { state: 'unavailable', binary_state: 'absent', diagnostics: { step: 'install', message: 'Ollama binary not found — install it from the Models view.' } },
      storage: { state: 'healthy', used_percent: 5 },
      memory: { state: 'healthy' },
    },
  },
};

function makeEl(id) {
  const listeners = {};
  const children = [];
  return {
    id,
    dataset: {},
    hidden: false,
    disabled: false,
    value: '',
    textContent: '',
    innerHTML: '',
    title: '',
    className: '',
    style: {},
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute() {},
    getAttribute() { return null; },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    children,
    appendChild(child) { children.push(child); return child; },
    parentElement: null,
    querySelectorAll() { return []; },
    querySelector() { return null; },
    focus() {},
  };
}

function shim(id) {
  const node = makeEl(id);
  return node;
}

async function run(apiImpl) {
  const ids = ['tl-cpu', 'tl-cpu-dot', 'tl-ram', 'tl-ram-dot', 'tl-disk', 'tl-disk-dot', 'tl-net', 'tl-net-dot',
    'tl-ollama', 'tl-ollama-dot', 'telemetry-panel', 'diagnostics-panel', 'ai-ops-state', 'ai-ops-pipeline',
    'ai-ops-assistant', 'ai-ops-model', 'ai-ops-task', 'ai-ops-guardian',
    'ft-backend', 'ft-backend-dot', 'ft-host', 'ft-privacy', 'ft-offline', 'ft-engagements', 'ft-refreshed'];
  const elements = {};
  for (const id of ids) {
    elements[id] = shim(id);
    if (id === 'tl-ollama-dot') elements[id].parentElement = elements['tl-ollama'];
  }
  // Persistent pipeline stage nodes so the state map can be asserted.
  const stageNodes = ['request', 'analysis', 'plan', 'validation', 'execution', 'result'].map(() => shim('_stage'));
  elements['ai-ops-pipeline'].querySelectorAll = () => stageNodes;

  const document = {
    hidden: false,
    readyState: 'complete',
    getElementById(id) { return elements[id] || null; },
    addEventListener() {},
  };
  const global = globalThis;
  global.window = global;
  global.document = document;
  global.esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));
  global.api = async (path) => apiImpl(path);
  global.state = { task: null, plan: null };
  global.stopHud = () => {};
  global.refreshHud = () => {};

  vm.runInThisContext(source, { filename: 'hud.js' });
  await global.refreshHud();
  global.stopHud();
  return { elements, stageNodes };
}

(async () => {
  // 1. Live payload path — every chip is populated with real values.
  const { elements } = await run(async (path) => (path === '/api/dashboard' ? DASHBOARD : HEALTH));
  assert.strictEqual(elements['tl-cpu'].textContent, '0.00', 'CPU chip shows loadavg');
  assert.strictEqual(elements['tl-ram'].textContent, '3.8 GB', 'RAM chip shows total memory in GB');
  assert.strictEqual(elements['tl-disk'].textContent, '5%', 'DISK chip shows used percent');
  assert.strictEqual(elements['tl-net'].textContent, '2', 'NET chip shows interface count');
  assert.strictEqual(elements['tl-ollama'].textContent, 'UNAVAILABLE', 'OLLAMA chip shows honest unavailable state');
  assert.ok(String(elements['telemetry-panel'].innerHTML).includes('2 cores'), 'telemetry panel lists core count');
  assert.ok(String(elements['telemetry-panel'].innerHTML).includes('5% used'), 'telemetry panel lists disk usage');
  assert.ok(String(elements['telemetry-panel'].innerHTML).includes('e2b.local'), 'telemetry panel lists hostname');
  assert.ok(String(elements['diagnostics-panel'].innerHTML).includes('INSTALL'), 'diagnostics lists the actionable ollama install step');
  assert.ok(String(elements['diagnostics-panel'].innerHTML).includes('HEALTHY'), 'diagnostics lists healthy subsystems');
  assert.strictEqual(elements['tl-ollama'].title, 'Ollama binary not found — install it from the Models view.', 'ollama chip carries the recovery message');
  assert.strictEqual(elements['ai-ops-state'].textContent, 'IDLE', 'AI ops badge idles with no active task');
  assert.strictEqual(elements['ft-backend'].textContent, 'ONLINE', 'footer shows backend online');
  assert.strictEqual(elements['ft-host'].textContent, 'debian · x86_64', 'footer shows host distro and arch');
  assert.strictEqual(elements['ft-privacy'].textContent, 'LOCAL', 'footer shows privacy mode');
  assert.strictEqual(elements['ft-offline'].textContent, 'OFF', 'footer shows on-network state');
  assert.strictEqual(elements['ft-engagements'].textContent, '0 / 0', 'footer shows engagement counts');

  // 2. Empty/unavailable path — nothing is fabricated; chips render N/A.
  const empty = (await run(async () => ({ dashboard: {}, health: {} }))).elements;
  assert.strictEqual(empty['tl-cpu'].textContent, 'N/A', 'missing CPU renders N/A');
  assert.strictEqual(empty['tl-ram'].textContent, 'N/A', 'missing RAM renders N/A');
  assert.strictEqual(empty['tl-disk'].textContent, 'N/A', 'missing DISK renders N/A');
  assert.strictEqual(empty['tl-net'].textContent, 'N/A', 'missing NET renders N/A');
  assert.strictEqual(empty['tl-ollama'].textContent, 'N/A', 'missing OLLAMA renders N/A');
  assert.ok(String(empty['diagnostics-panel'].innerHTML).includes('UNKNOWN'), 'diagnostics degrade to UNKNOWN, never a fake healthy');

  // 3. Failure path — a rejected fetch can never break the console.
  const failed = (await run(async () => { throw new Error('offline'); })).elements;
  assert.strictEqual(failed['tl-cpu'].textContent, 'N/A', 'failed fetch still renders N/A without throwing');

  // 4. AI Operations snapshot — the event-driven hook drives the pipeline.
  const snap = await run(async () => ({ dashboard: {}, health: {} }));
  globalThis.updateAiOpsHud({
    task: { id: 'task-0001', state: 'COMPLETED' },
    plan: { status: 'executed', workers: [{ id: 'orchestrator', state: 'done' }, { id: 'local-model', state: 'done' }] },
    operation: { status: 'succeeded' },
    guardian: { decision: 'APPROVE', risk: 'low' },
    council: { selected: ['orchestrator', 'guardian'] },
  });
  assert.strictEqual(snap.elements['ai-ops-state'].textContent, 'COMPLETED', 'AI ops badge reflects a completed operation');
  assert.strictEqual(snap.elements['ai-ops-assistant'].textContent, 'orchestrator, guardian', 'AI ops lists consulted assistants');
  assert.strictEqual(snap.elements['ai-ops-guardian'].textContent, 'APPROVE', 'AI ops lists the guardian decision');
  assert.ok(String(snap.stageNodes[4].className).includes('done'), 'execution stage completes');
  assert.ok(String(snap.stageNodes[5].className).includes('done'), 'result stage completes');

  console.log('hud wiring smoke: PASS');
})().catch((error) => { console.error(error); process.exit(1); });
