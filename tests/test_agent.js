'use strict';
// Agent Mode surface: transcript escaping, approve-card variants, stream
// wiring, and the out-of-order transcript guard. Runs frontend/agent.js in
// a vm sandbox with a minimal fake DOM (no parser: innerHTML is asserted
// as a string, which is exactly where escaping bugs would show).
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

function makeElement(tag, doc) {
  return {
    tagName: String(tag || 'div').toUpperCase(),
    children: [],
    attributes: {},
    listeners: {},
    innerHTML: '',
    textContent: '',
    value: '',
    disabled: false,
    hidden: false,
    className: '',
    scrollTop: 0,
    scrollHeight: 0,
    style: {},
    dataset: {},
    setAttribute(name, value) { this.attributes[name] = String(value); },
    getAttribute(name) { return Object.prototype.hasOwnProperty.call(this.attributes, name) ? this.attributes[name] : null; },
    addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); },
    appendChild(child) { this.children.push(child); return child; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    scrollIntoView() {},
    click() { (this.listeners.click || []).forEach((fn) => fn()); },
  };
}

function makeDocument() {
  const registry = {};
  const doc = {
    registry,
    getElementById(id) {
      if (!registry[id]) registry[id] = makeElement('div', doc);
      return registry[id];
    },
    createElement(tag) { return makeElement(tag, doc); },
    querySelector() { return null; },
    querySelectorAll() { return []; },
  };
  // InnerHTML assignment is opaque; querySelector for the empty marker is
  // emulated so renderEvent clears the placeholder like a real DOM.
  const transcript = doc.getElementById('agent-transcript');
  transcript.querySelector = function (selector) {
    if (selector === '.empty-inline' && this.innerHTML.includes('empty-inline')) {
      const host = this;
      return { remove() { host.innerHTML = ''; } };
    }
    return null;
  };
  doc.getElementById('agent-goal').value = '';
  doc.getElementById('agent-max-steps').value = '5';
  return doc;
}

function loadAgent(harness) {
  const doc = harness.doc || makeDocument();
  const apiCalls = [];
  const intervals = new Map();
  let intervalSeq = 0;
  const sources = [];
  const sandbox = {
    document: doc,
    window: {},
    console,
    setInterval(fn, ms) { intervalSeq += 1; intervals.set(intervalSeq, { fn, ms }); return intervalSeq; },
    clearInterval(id) { intervals.delete(id); },
    api: (url, options) => {
      apiCalls.push({ url, options });
      const behavior = (harness.routes || {})[url];
      if (typeof behavior === 'function') return behavior(url, options);
      if (behavior !== undefined) return Promise.resolve(behavior);
      return Promise.reject(new Error('no route stubbed: ' + url));
    },
    esc: (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c])),
    toast: (message) => { (harness.toasts = harness.toasts || []).push(message); },
    EventSource: harness.withEventSource === false ? undefined : class FakeEventSource {
      constructor(url) {
        this.url = url;
        this.closed = false;
        this.onmessage = null;
        this.onerror = null;
        sources.push(this);
      }
      close() { this.closed = true; }
      emit(payload) { if (this.onmessage) this.onmessage({ data: JSON.stringify(payload) }); }
      fail() { if (this.onerror) this.onerror({}); }
    },
  };
  sandbox.window = sandbox;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  const code = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'agent.js'), 'utf8');
  vm.runInContext(code, sandbox, { filename: 'agent.js' });
  assert.strictEqual(typeof sandbox.window.loadAgent, 'function', 'agent.js must expose loadAgent');
  return {
    doc, sandbox, apiCalls, intervals, sources,
    transcriptHtml() {
      const host = doc.getElementById('agent-transcript');
      return host.innerHTML + host.children.map((child) => child.innerHTML || '').join('\n');
    },
    fireInterval(id) {
      const entry = intervals.get(id);
      assert.ok(entry, 'interval exists');
      return entry.fn();
    },
  };
}

const tick = () => new Promise((resolve) => setImmediate(resolve));

(async () => {
  // 1. Transcript escapes hostile model/operation text.
  {
    const run = { id: 'a1', status: 'finished', goal: 'x', config: { step_index: 1, max_steps: 5 }, summary: { outcome: 'achieved' } };
    const events = [
      { seq: 1, kind: 'think', payload: { step: 1, provider: 'llamafile', model: 'm', fact_summary: '<script>alert(1)</script>', next_steps: ['<img src=x onerror=y>'] } },
      { seq: 2, kind: 'step_finished', payload: { step: 1, status: 'succeeded', commands: [{ display: 'whoami', status: 'succeeded', exit_code: 0, stdout_tail: '</pre><script>z</script>' }] } },
    ];
    const h = loadAgent({ routes: { '/api/agent/runs': { runs: [{ id: 'a1', status: 'finished', goal: 'x', summary: { outcome: 'achieved' } }] }, '/api/agent/runs/a1': { run, events } } });
    h.sandbox.window.loadAgent();
    await tick(); await tick();
    const html = h.transcriptHtml();
    assert.ok(html.includes('&lt;script&gt;alert(1)&lt;/script&gt;'), 'think text escaped');
    assert.ok(html.includes('&lt;img src=x onerror=y&gt;'), 'next step escaped');
    assert.ok(html.includes('&lt;/pre&gt;&lt;script&gt;z&lt;/script&gt;'), 'output escaped');
    assert.ok(!html.includes('<script>alert(1)</script>'), 'no raw script survives');
  }

  // 2. Plan pauses show the exact-step approve card; preflight pauses show resume.
  {
    const planned = { step: 1, plan_id: 'p1', kind: 'package_operation', risk: 'high', request: 'install htop', commands: ['apt-get install htop'], approval_phrase: 'APPROVE apt' };
    const run = { id: 'b1', status: 'awaiting_approval', goal: 'x', config: {}, summary: {} };
    const h = loadAgent({
      routes: {
        '/api/agent/runs': { runs: [{ id: 'b1', status: 'awaiting_approval', goal: 'x', summary: {} }] },
        '/api/agent/runs/b1': { run, events: [{ seq: 1, kind: 'step_planned', payload: planned }, { seq: 2, kind: 'paused', payload: { step: 1, plan_id: 'p1', reason: 'needs approval' } }] },
      },
    });
    h.sandbox.window.loadAgent();
    await tick(); await tick(); await tick();
    const card = h.doc.getElementById('agent-approve');
    assert.strictEqual(card.hidden, false, 'approve card visible on plan pause');
    assert.ok(card.innerHTML.includes('APPROVE THIS EXACT STEP'), 'exact-step approval label');
    assert.ok(card.innerHTML.includes('apt-get install htop'), 'approve card shows commands');

    const run2 = { id: 'b2', status: 'awaiting_approval', goal: 'x', config: {}, summary: {} };
    const h2 = loadAgent({
      routes: {
        '/api/agent/runs': { runs: [{ id: 'b2', status: 'awaiting_approval', goal: 'x', summary: {} }] },
        '/api/agent/runs/b2': { run: run2, events: [{ seq: 1, kind: 'step_planned', payload: planned }, { seq: 2, kind: 'paused', payload: { reason: 'preflight needs review', operation_id: 'op1' } }] },
      },
    });
    h2.sandbox.window.loadAgent();
    await tick(); await tick();
    const card2 = h2.doc.getElementById('agent-approve');
    assert.ok(card2.innerHTML.includes('PREFLIGHT REVIEW'), 'preflight pause shows resume label');
    assert.ok(!card2.innerHTML.includes('APPROVE THIS EXACT STEP'), 'preflight pause is not an approval');
  }

  // 3. A stale transcript response never overwrites a newer selection.
  {
    let releaseA = null;
    const runA = { id: 'ca', status: 'finished', goal: 'old', config: {}, summary: { outcome: 'achieved' } };
    const runB = { id: 'cb', status: 'finished', goal: 'new', config: {}, summary: { outcome: 'achieved' } };
    const h = loadAgent({
      routes: {
        '/api/agent/runs': { runs: [{ id: 'ca', status: 'finished', goal: 'old', summary: { outcome: 'achieved' } }, { id: 'cb', status: 'finished', goal: 'new', summary: { outcome: 'achieved' } }] },
        '/api/agent/runs/ca': () => new Promise((resolve) => { releaseA = () => resolve({ run: runA, events: [{ seq: 1, kind: 'finished', payload: { outcome: 'achieved', reason: 'STALE-A' } }] }); }),
        '/api/agent/runs/cb': { run: runB, events: [{ seq: 1, kind: 'finished', payload: { outcome: 'achieved', reason: 'FRESH-B' } }] },
      },
    });
    h.sandbox.window.loadAgent();
    await tick(); await tick();
    assert.ok(releaseA, 'auto-load of the first run is in flight');
    const buttons = h.doc.getElementById('agent-runs').children;
    assert.strictEqual(buttons.length, 2, 'two run buttons render');
    buttons[1].click(); // select B while A is outstanding
    await tick(); await tick(); await tick();
    releaseA(); // stale A arrives late
    await tick(); await tick();
    const html = h.transcriptHtml();
    assert.ok(html.includes('FRESH-B'), 'newer selection renders');
    assert.ok(!html.includes('STALE-A'), 'stale response discarded');
  }

  // 4. Live runs open a stream from the last seen seq; stream errors fall back to polling.
  {
    const run = { id: 'd1', status: 'running', goal: 'x', config: { step_index: 0, max_steps: 3 }, summary: {} };
    const h = loadAgent({
      routes: {
        '/api/agent/runs': { runs: [{ id: 'd1', status: 'running', goal: 'x', summary: {} }] },
        '/api/agent/runs/d1': { run, events: [{ seq: 4, kind: 'think', payload: { step: 1, provider: 'p', model: 'm', fact_summary: 's' } }] },
      },
    });
    h.sandbox.window.loadAgent();
    await tick(); await tick(); await tick();
    assert.strictEqual(h.sources.length, 1, 'one stream opened for a live run');
    assert.ok(h.sources[0].url.includes('/api/agent/runs/d1/stream?since=4'), 'stream resumes from last seq, got ' + h.sources[0].url);
    h.sources[0].fail();
    await tick();
    assert.strictEqual(h.intervals.size, 1, 'stream failure falls back to polling');
  }

  console.log('agent surface tests: PASS');
})().catch((err) => { console.error(err); process.exit(1); });
