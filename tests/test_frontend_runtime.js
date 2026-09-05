'use strict';

// Execute the real frontend scripts against a minimal DOM shim. This catches
// top-level/initialization ReferenceErrors and verifies the workspace overrides
// (makePlan/setView/openDependency) are actually exposed when the app boots.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.join(__dirname, '..');
const index = fs.readFileSync(path.join(root, 'frontend', 'index.html'), 'utf8');
const ids = [...new Set([...index.matchAll(/id="([^"]+)"/g)].map(m => m[1]))];

function makeEl(id) {
  const listeners = {};
  const children = [];
  const ctxStub = { fillStyle: '', font: '', clearRect() {}, fillRect() {}, fillText() {} };
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
    tabIndex: 0,
    width: 0,
    height: 0,
    clientWidth: 1000,
    clientHeight: 500,
    scrollTop: 0,
    scrollHeight: 0,
    parentElement: null,
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute() {},
    getAttribute() { return null; },
    getContext() { return ctxStub; },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    children,
    appendChild(child) { children.push(child); return child; },
    remove() {},
    click() {},
    querySelector() { return null; },
    querySelectorAll() { return []; },
    focus() {},
    blur() {},
  };
}

const elements = Object.fromEntries(ids.map(id => [id, makeEl(id)]));
const documentListeners = {};
const windowListeners = {};

const document = {
  body: makeEl('body'),
  activeElement: null,
  getElementById(id) { return elements[id] || null; },
  querySelector() { return null; },
  querySelectorAll() { return []; },
  createElement(tag) { return makeEl('_' + tag); },
  addEventListener(type, fn) { (documentListeners[type] ||= []).push(fn); },
};

const global = globalThis;
global.window = global;
global.document = document;
global.innerWidth = 1200;
global.innerHeight = 900;
global.matchMedia = () => ({ matches: false });
global.requestAnimationFrame = () => 1;
global.addEventListener = (type, fn) => { (windowListeners[type] ||= []).push(fn); };
const opened = [];
global.open = (url, target) => { opened.push({ url, target }); return { closed: false }; };
global.EventSource = function () { return { close() {}, onmessage: null, onerror: null }; };
global.VortexTerminal = class { constructor() {} feed() {} render() {} resize() {} };
const fetched = [];
global.fetch = async (url) => {
  fetched.push(url);
  return {
    ok: true,
    status: 200,
    json: async () => {
      const path = decodeURIComponent(url);
      if (path.includes('/api/doctor')) return { doctor: null };
      if (path.includes('/api/setup')) return { setup: { first_run_complete: false, ready: true, steps: [] } };
      if (path.includes('/api/health')) return { health: { interrupted_tasks: [] } };
      if (path.includes('/api/mobile/apk')) return { apk: { ok: true, size_bytes: 4096 } };
      if (path.includes('/api/desktop/deb')) return { deb: { ok: true, size_bytes: 8192, filename: 'linux-vortex-terminal_0.2.21_all.deb' } };
      if (path.includes('/api/dependencies/proposal')) {
        if (path.includes('tool:podman')) {
          return { install: { id: 'tool:podman', title: 'podman', method: 'apt', installed: false, plan_request: 'install package podman', commands: ['sudo apt-get install podman'] } };
        }
        if (path.includes('agent:test')) return { install: { id: 'agent:test', title: 'Test agent', method: 'operator-manual', commands: [] } };
      }
      return { tools: [], history: [], engagements: [], conversations: [], tasks: [], messages: [], memories: [], procedures: [], experiences: [], settings: {}, agents: [], model: { local: {} }, dependencies: { dependencies: { missing: [], counts: {} } } };
    },
  };
};

const files = ['frontend/terminal.js', 'frontend/windows.js', 'frontend/app.js', 'frontend/workspace.js'];
const source = files.map(file => fs.readFileSync(path.join(root, file), 'utf8')).join('\n;\n');
// vm.runInThisContext mirrors classic browser scripts: top-level `function`
// declarations become window properties and `const` globals are shared across
// <script> blocks exactly as the real frontend relies on.
vm.runInThisContext(source, { filename: 'frontend-runtime.js' });

assert.strictEqual(typeof global.makePlan, 'function', 'workspace makePlan override is exposed');
assert.strictEqual(typeof global.setView, 'function', 'workspace setView override is exposed');

for (const fn of (documentListeners.DOMContentLoaded || [])) fn();
for (const fn of (windowListeners.DOMContentLoaded || [])) fn();

assert.strictEqual(typeof global.openDependency, 'function', 'dependency proposal surface is exposed');
assert.strictEqual(typeof global.openDependencies, 'function', 'dependency inventory surface is exposed');

// Every primary/secondary view must be reachable without a boot error, and the
// workspace setView override must actually load that view's data.
const baseline = fetched.length;
const expectLoad = {
  conversations: '/api/conversations',
  tasks: '/api/tasks',
  agents: '/api/agents',
  memory: '/api/memory',
  learning: '/api/learning',
  system: '/api/system/health',
  settings: '/api/settings',
  assets: '/api/assets/graph',
};
for (const view of ['overview', 'conversations', 'terminal', 'tasks', 'reports', 'engagements', 'activity', 'agents', 'tools', 'memory', 'learning', 'system', 'settings', 'assets']) {
  global.setView(view);
}
for (const [view, endpoint] of Object.entries(expectLoad)) {
  assert.ok(fetched.slice(baseline).some(url => url.includes(endpoint)), `view ${view} loads ${endpoint}`);
}

// The Agents install path must be able to open the reviewed proposal surface,
// and a mapped apt tool must produce a real CREATE APT PLAN action.
(async () => {
  await global.openDependency('agent:test');
  assert.ok(fetched.some(url => url.includes('/api/dependencies/proposal')), 'agent install opens the proposal route');
  assert.ok(!String(elements['dep-detail'].innerHTML).includes('CREATE APT PLAN'), 'agent proposal stays operator-controlled');

  await global.openDependency('tool:podman');
  assert.ok(String(elements['dep-detail'].innerHTML).includes('CREATE APT PLAN'), 'apt tool proposal offers a reviewed plan path');

  // APK download: embedded contexts must trigger a top-level tab instead of a
  // synthetic anchor click, and the completion toast must expose a real
  // manual download link even if every automatic trigger is blocked.
  await global.downloadApk();
  assert.ok(fetched.some(url => url.includes('/api/mobile/apk')), 'APK download syncs the live workbench first');
  assert.strictEqual(opened[opened.length - 1]?.url, '/api/mobile/apk/download', 'APK download opens a top-level tab');
  assert.strictEqual(opened[opened.length - 1]?.target, '_blank', 'APK download tab opens in the background');
  const toastEl = elements['toast'];
  assert.ok(String(toastEl.textContent).includes('APK synced'), 'APK toast reports the synced build');
  assert.ok(toastEl.children.some((c) => c.href === '/api/mobile/apk/download' && c.download === 'vortex.apk'), 'APK toast carries the manual download link');

  // Desktop .deb download: same guarantees — build first, top-level tab
  // trigger, and a manual link in the toast for blocked contexts.
  await global.downloadDeb();
  assert.ok(fetched.some(url => url.includes('/api/desktop/deb')), 'desktop build posts before the download');
  assert.strictEqual(opened[opened.length - 1]?.url, '/api/desktop/deb/download', 'desktop download opens a top-level tab');
  assert.strictEqual(opened[opened.length - 1]?.target, '_blank', 'desktop download tab opens in the background');
  assert.ok(String(toastEl.textContent).includes('Desktop .deb built'), 'desktop toast reports the built package');
  assert.ok(toastEl.children.some((c) => c.href === '/api/desktop/deb/download' && c.download === 'linux-vortex-terminal_0.2.21_all.deb'), 'desktop toast carries the manual download link');

  console.log('frontend runtime smoke: PASS');
})().catch((error) => { console.error(error); process.exit(1); });
