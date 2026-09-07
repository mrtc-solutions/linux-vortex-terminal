'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const source = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'app.js'), 'utf8');

function response(status, payload) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() { return payload; }
  };
}

function harness({ hash = '', stored = {}, storageDisabled = false, fetchImpl }) {
  const listeners = {};
  const elements = {};
  const makeElement = id => ({
    id,
    open: false,
    value: '',
    textContent: '',
    addEventListener(type, fn) { (listeners[`${id}:${type}`] ||= []).push(fn); },
    showModal() { this.open = true; },
    focus() { this.focused = true; }
  });
  for (const id of ['capability-dialog', 'capability-form', 'capability-input', 'capability-error']) {
    elements[id] = makeElement(id);
  }

  const storage = new Map(Object.entries(stored));
  const historyCalls = [];
  let reloads = 0;
  const domReady = [];
  const context = {
    console,
    URLSearchParams,
    Intl,
    Date,
    Promise,
    Error,
    JSON,
    Number,
    String,
    Array,
    Object,
    Math,
    encodeURIComponent,
    decodeURIComponent,
    location: {
      hash,
      pathname: '/mobile/workbench',
      search: '?mode=remote',
      reload() { reloads += 1; }
    },
    history: {
      replaceState(state, title, url) { historyCalls.push({ state, title, url }); }
    },
    sessionStorage: {
      getItem(key) {
        if (storageDisabled) throw new Error('storage disabled');
        return storage.has(key) ? storage.get(key) : null;
      },
      setItem(key, value) {
        if (storageDisabled) throw new Error('storage disabled');
        storage.set(key, String(value));
      },
      removeItem(key) {
        if (storageDisabled) throw new Error('storage disabled');
        storage.delete(key);
      }
    },
    document: {
      getElementById(id) { return elements[id] || null; },
      querySelector() { return null; },
      querySelectorAll() { return []; },
      createElement() { return makeElement('created'); },
      body: { appendChild() {} },
      title: ''
    },
    fetch: fetchImpl,
    setTimeout(fn) { fn(); return 1; },
    clearTimeout() {},
    requestAnimationFrame(fn) { fn(); return 1; },
    addEventListener(type, fn) { if (type === 'DOMContentLoaded') domReady.push(fn); },
    innerWidth: 1200,
    innerHeight: 800,
    EventSource: undefined,
    VortexTerminal: class {},
  };
  context.window = context;
  vm.createContext(context);
  vm.runInContext(
    `${source}\n;globalThis.__vortexAuth = Object.freeze({ api, establishBrowserSession, bindCapabilityForm });`,
    context,
    { filename: 'frontend/app.js' }
  );
  return {
    auth: context.__vortexAuth,
    elements,
    historyCalls,
    storage,
    listeners,
    get reloads() { return reloads; },
    async submit() {
      const handlers = listeners['capability-form:submit'] || [];
      assert.strictEqual(handlers.length, 1, 'capability form has exactly one submit handler');
      return handlers[0]({ preventDefault() {} });
    }
  };
}

(async () => {
  // A fragment capability is scrubbed synchronously, exchanged once, removed
  // from script-readable storage, and never attached to subsequent API calls.
  const calls = [];
  const capability = 'A'.repeat(64);
  const valid = harness({
    hash: `#vortex-token=${capability}&ignored=value`,
    fetchImpl: async (url, options = {}) => {
      calls.push({ url, options });
      if (url === '/api/auth/session') return response(200, { authenticated: true, expires_in: 28800 });
      return response(200, { ok: true });
    }
  });
  assert.deepStrictEqual(valid.historyCalls.map(call => call.url), ['/mobile/workbench?mode=remote'], 'capability fragment is removed before API startup');
  assert.strictEqual(valid.storage.get('vortex-capability'), capability, 'capability is retained only until exchange');
  assert.deepStrictEqual(await valid.auth.api('/api/health'), { ok: true });
  assert.strictEqual(calls.length, 2, 'one exchange precedes one application request');
  assert.strictEqual(calls[0].url, '/api/auth/session');
  assert.strictEqual(calls[0].options.headers['X-Vortex-Token'], capability, 'capability is sent only to the exchange endpoint');
  assert.strictEqual(calls[1].url, '/api/health');
  assert.ok(!('X-Vortex-Token' in calls[1].options.headers), 'application request relies on the HTTP-only cookie');
  assert.ok(!valid.storage.has('vortex-capability'), 'script-readable capability is deleted after exchange');

  // Web Storage can be disabled by privacy policy. The fragment still works
  // from memory and is scrubbed rather than turning into a dead connection.
  const privateCalls = [];
  const privateMode = harness({
    hash: `#vortex-token=${capability}`,
    storageDisabled: true,
    fetchImpl: async (url, options = {}) => {
      privateCalls.push({ url, options });
      return response(200, url === '/api/auth/session' ? { authenticated: true } : { private: true });
    }
  });
  assert.strictEqual((await privateMode.auth.api('/api/health')).private, true);
  assert.strictEqual(privateCalls[0].options.headers['X-Vortex-Token'], capability, 'storage failure does not discard the in-memory capability');
  assert.strictEqual(privateMode.historyCalls.length, 1, 'private-mode fragment is still scrubbed');

  // Empty/invalid fragments override stale tab storage, are scrubbed, and fall
  // back to an explicit credential dialog after the protected API returns 401.
  let emptyCalls = 0;
  const empty = harness({
    hash: '#vortex-token=',
    stored: { 'vortex-capability': 'stale-capability' },
    fetchImpl: async () => { emptyCalls += 1; return response(401, { error: { message: 'invalid sidecar capability' } }); }
  });
  assert.strictEqual(empty.historyCalls.length, 1, 'even an empty credential fragment is scrubbed');
  assert.ok(!empty.storage.has('vortex-capability'), 'invalid fragment clears a stale stored capability');
  await assert.rejects(empty.auth.api('/api/health'), /invalid sidecar capability/);
  assert.strictEqual(emptyCalls, 1, 'invalid fragment does not attempt a capability exchange');
  assert.strictEqual(empty.elements['capability-dialog'].open, true, '401 opens the manual recovery dialog');

  // A wrong fragment is forgotten. Validation blocks malformed manual input,
  // then a corrected capability exchanges successfully and reloads the page.
  const recoveryCalls = [];
  const recovery = harness({
    hash: '#vortex-token=wrong-token',
    fetchImpl: async (url, options = {}) => {
      recoveryCalls.push({ url, options });
      if (url !== '/api/auth/session') return response(200, { ok: true });
      const token = options.headers['X-Vortex-Token'];
      return token === capability
        ? response(200, { authenticated: true, expires_in: 28800 })
        : response(401, { error: { message: 'invalid sidecar capability' } });
    }
  });
  recovery.auth.bindCapabilityForm();
  await assert.rejects(recovery.auth.api('/api/health'), /invalid sidecar capability/);
  assert.ok(!recovery.storage.has('vortex-capability'), 'rejected capability is removed from storage');
  assert.strictEqual(recovery.elements['capability-dialog'].open, true);

  const beforeValidation = recoveryCalls.length;
  recovery.elements['capability-input'].value = `bad\nvalue`;
  await recovery.submit();
  assert.strictEqual(recoveryCalls.length, beforeValidation, 'control characters are rejected before fetch');
  assert.match(recovery.elements['capability-error'].textContent, /valid sidecar capability/i);

  recovery.elements['capability-input'].value = `  ${capability}  `;
  await recovery.submit();
  assert.strictEqual(recovery.reloads, 1, 'successful manual recovery reloads into the cookie-authenticated app');
  assert.strictEqual(recoveryCalls.at(-1).options.headers['X-Vortex-Token'], capability, 'manual capability is trimmed and exchanged');
  assert.ok(!recovery.storage.has('vortex-capability'), 'corrected capability is removed after exchange');

  console.log('frontend browser authentication: PASS');
})().catch(error => {
  console.error(error);
  process.exit(1);
});
