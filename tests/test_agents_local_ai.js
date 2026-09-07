'use strict';

// The Agents view must surface the local AI runtime + model pool with the real
// install/download actions, and those actions must be gated on an installed +
// started runtime. This loads the real frontend/models.js against a DOM shim
// and drives renderAgentsLocalAi through the two honest states.
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.join(__dirname, '..');
const source = fs.readFileSync(path.join(root, 'frontend', 'models.js'), 'utf8');

function makeEl(id) {
  const listeners = {};
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
    parentElement: null,
    classList: { add() {}, remove() {}, toggle() {} },
    setAttribute() {},
    getAttribute() { return null; },
    addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    focus() {},
  };
}

function boot(ollamaPayload) {
  const elements = {
    'agents-local-ai': makeEl('agents-local-ai'),
    'ollama-status': makeEl('ollama-status'),
    'ollama-actions': makeEl('ollama-actions'),
    'ollama-install': makeEl('ollama-install'),
    'model-grid': makeEl('model-grid'),
    'downloads-strip': makeEl('downloads-strip'),
  };
  const docListeners = {};
  const winListeners = {};
  const document = {
    readyState: 'loading',
    hidden: false,
    body: makeEl('body'),
    getElementById(id) { return elements[id] || null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    addEventListener(type, fn) { (docListeners[type] ||= []).push(fn); },
  };
  const posts = [];
  const global = globalThis;
  // fresh sandbox globals per boot
  global.window = global;
  global.document = document;
  global.$ = (id) => elements[id] || null;
  global.esc = (s) => String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  global.toast = () => {};
  global.fmtDate = () => '';
  global.api = async (url, opts) => {
    if (opts && opts.method === 'POST') posts.push({ url, body: opts.body });
    return { ollama: ollamaPayload.ollama, models: ollamaPayload.models };
  };
  global.addEventListener = (type, fn) => { (winListeners[type] ||= []).push(fn); };
  global.requestAnimationFrame = () => 1;

  vm.runInThisContext(source, { filename: 'models.js' });
  return { elements, posts, docListeners, winListeners };
}

const notInstalled = {
  ollama: {
    installed: false, api_state: 'unavailable', endpoint: 'http://127.0.0.1:11434',
    install: { status: 'idle', step: '', percent: 0.0 },
    server: { state: 'stopped', managed: false },
    platform: { arch: 'x86_64', supported_arch: true, offline: false },
  },
  models: {
    items: [
      { name: 'phi4-mini:3.8b', label: 'Phi-4 Mini 3.8B', family: 'phi4-mini', recommended: true, installed: false, approx_size_gb: 2.5, roles: ['conversation'] },
      { name: 'llama3.2:3b', label: 'Llama 3.2 3B', family: 'llama3.2', recommended: true, installed: false, approx_size_gb: 2.0, roles: ['fast'] },
    ],
    extras: [], downloads: {},
  },
};

const installedRunning = {
  ollama: {
    installed: true, api_state: 'healthy', endpoint: 'http://127.0.0.1:11434',
    install: { status: 'completed', step: '', percent: 100.0 },
    server: { state: 'running', managed: true },
    platform: { arch: 'x86_64', supported_arch: true, offline: false },
  },
  models: {
    items: [
      { name: 'phi4-mini:3.8b', label: 'Phi-4 Mini 3.8B', family: 'phi4-mini', recommended: true, installed: false, approx_size_gb: 2.5, roles: ['conversation'] },
      { name: 'llama3.2:3b', label: 'Llama 3.2 3B', family: 'llama3.2', recommended: true, installed: true, installed_name: 'llama3.2:3b', approx_size_gb: 2.0, roles: ['fast'] },
    ],
    extras: [], downloads: {},
  },
};

(async () => {
  // 1. Runtime not installed: INSTALL OLLAMA is the only real action; models
  //    must not offer DOWNLOAD until the runtime exists.
  {
    const t = boot(notInstalled);
    await global.loadModels();
    const html = t.elements['agents-local-ai'].innerHTML;
    assert.ok(html.includes('>INSTALL OLLAMA<'), 'not-installed state offers INSTALL OLLAMA');
    assert.ok(html.includes('install &amp; start Ollama first'), 'models gate on an installed runtime');
    assert.ok(!html.includes('data-local-ai-pull='), 'no model DOWNLOAD before Ollama is installed');
  }

  // 2. Runtime installed + service running: catalog models that are not yet
  //    installed now offer a real DOWNLOAD action.
  {
    const t = boot(installedRunning);
    await global.loadModels();
    const html = t.elements['agents-local-ai'].innerHTML;
    assert.ok(html.includes('data-local-ai-pull='), 'models offer DOWNLOAD once the runtime is running');
    assert.ok(!html.includes('>INSTALL OLLAMA<'), 'no install button when Ollama is present');
    assert.ok(html.includes('>DOWNLOAD<'), 'download action is rendered');
  }

  console.log('agents local-AI panel: PASS');
})().catch((error) => { console.error(error); process.exit(1); });
