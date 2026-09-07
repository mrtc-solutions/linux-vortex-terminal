/* ARENA AI // VORTEX — tactical HUD wiring.
   Loaded last, after app.js/workspace.js/models.js (which provide $, esc, api,
   toast, fmtDate, state). Every readout is derived from real backend state:
   /api/dashboard (CPU load, memory, disk, network, AI, sessions) and
   /api/health (subsystem states). Nothing here fabricates telemetry; an
   unavailable metric renders N/A. All writes are null-safe and failure-
   tolerant so a missing route or element can never break the console. */
(function () {
  'use strict';

  var TELEMETRY_INTERVAL_MS = 12000;

  var hud = {
    dashboard: null,
    health: null,
    aiOpsSignature: '',
    timer: null,
    inflight: null,
    task: null,
    plan: null,
    operation: null,
    guardian: null,
    council: null,
  };

  function el(id) {
    return typeof document !== 'undefined' ? document.getElementById(id) : null;
  }

  function setText(id, value) {
    var node = el(id);
    if (node) node.textContent = value == null || value === '' ? 'N/A' : String(value);
  }

  function setDot(id, tone) {
    var node = el(id);
    if (!node) return;
    node.className = 'dot' + (tone === 'warn' ? ' warn' : tone === 'off' ? ' off' : '');
  }

  function row(label, value, cls) {
    return '<div class="context-row"><label>' + esc(label) + '</label><span class="' +
      esc(cls || '') + '">' + esc(value) + '</span></div>';
  }

  function diagRow(name, value, tone) {
    var dotCls = tone === 'good' ? 'dot' : tone === 'warn' ? 'dot warn' : tone === 'bad' ? 'dot off' : 'dot unknown';
    return '<div class="diag-row"><span class="diag-name">' + esc(name) + '</span>' +
      '<span class="diag-value"><span class="' + dotCls + '"></span>' + esc(value) + '</span></div>';
  }

  function toneOf(state) {
    var s = String(state || '').toLowerCase();
    var good = ['healthy', 'running', 'ready', 'available', 'installed', 'connected', 'online', 'succeeded', 'completed'];
    var bad = ['unavailable', 'failed', 'blocked', 'absent', 'error', 'disconnected', 'offline', 'empty', 'degraded'];
    if (good.indexOf(s) !== -1) return 'good';
    if (bad.indexOf(s) !== -1) return 'bad';
    if (s === 'warning' || s === 'disabled') return 'warn';
    return 'unknown';
  }

  function loadAvg(loadavg) {
    if (!Array.isArray(loadavg) || !loadavg.length) return 'N/A';
    return loadavg.map(function (n) { return Number(n).toFixed(2); }).join(' / ');
  }

  function gb(mb) {
    if (mb == null || !isFinite(Number(mb))) return 'N/A';
    return (Number(mb) / 1024).toFixed(1) + ' GB';
  }

  function renderTelemetry() {
    var dash = hud.dashboard || {};
    var system = dash.system || {};
    var cpu = system.cpu || {};
    var mem = system.memory || {};
    var disk = system.disk || {};
    var net = system.network || {};

    var load1 = Array.isArray(cpu.loadavg) && cpu.loadavg.length ? cpu.loadavg[0] : null;
    var cpuVal = load1 == null ? 'N/A' : Number(load1).toFixed(2);
    setText('tl-cpu', cpuVal);
    setDot('tl-cpu-dot', load1 == null ? 'off' : '');

    var ramVal = mem.total_mb == null ? 'N/A' : gb(mem.total_mb);
    setText('tl-ram', ramVal);
    setDot('tl-ram-dot', mem.total_mb == null ? 'off' : '');

    var diskVal = disk.used_percent == null ? 'N/A' : disk.used_percent + '%';
    setText('tl-disk', diskVal);
    setDot('tl-disk-dot', disk.used_percent == null ? 'off' : (Number(disk.used_percent) >= 95 ? 'warn' : ''));

    var netVal = net.interfaces == null ? 'N/A' : String(net.interfaces);
    setText('tl-net', netVal);
    setDot('tl-net-dot', net.interfaces == null ? 'off' : (Number(net.interfaces) > 0 ? '' : 'off'));

    var panel = el('telemetry-panel');
    if (panel) {
      var hostname = net.hostname || 'N/A';
      panel.innerHTML =
        row('CPU', cpu.processors == null ? 'N/A' : cpu.processors + ' cores') +
        row('LOAD AVG', loadAvg(cpu.loadavg)) +
        row('MEMORY', gb(mem.total_mb) + (mem.total_mb != null ? ' total' : '')) +
        row('DISK', disk.used_percent == null ? 'N/A' : disk.used_percent + '% used') +
        row('NETWORK', (net.interfaces == null ? 'N/A' : net.interfaces + ' interface(s)') + ' · ' + hostname) +
        row('AI STATE', String((dash.ai || {}).state || 'N/A'));
    }
  }

  function renderOllama() {
    var components = (hud.health && hud.health.components) || {};
    var ollama = components.ollama || {};
    var state = ollama.state || ollama.binary_state || null;
    setText('tl-ollama', state ? String(state).toUpperCase() : null);
    setDot('tl-ollama-dot', !state ? 'off' : toneOf(state) === 'good' ? '' : toneOf(state) === 'bad' ? 'off' : 'warn');
    var chip = el('tl-ollama-dot');
    if (chip && chip.parentElement) {
      var hint = ollama.diagnostics && ollama.diagnostics.message ? String(ollama.diagnostics.message) : '';
      chip.parentElement.title = hint;
      chip.parentElement.setAttribute('aria-label', hint || 'Open Local AI / Models view');
    }
  }

  function renderDiagnostics() {
    var panel = el('diagnostics-panel');
    if (!panel) return;
    var components = (hud.health && hud.health.components) || {};
    var core = components.core || {};
    var db = components.database || {};
    var terminal = components.terminal_engine || {};
    var council = components.agent_council || {};
    var localAi = components.local_ai || {};
    var ollama = components.ollama || {};
    var storage = components.storage || {};

    function pair(name, state) {
      return diagRow(name, String(state).toUpperCase(), toneOf(state));
    }

    var rows = [];
    rows.push(pair('Application', core.state || 'healthy'));
    rows.push(pair('Database', db.state || 'unknown'));
    rows.push(pair('Terminal', terminal.state || 'unknown'));
    rows.push(pair('AI Agents', council.state || 'unknown'));
    rows.push(pair('Local Model', localAi.state || 'unavailable'));
    var ollamaState = ollama.state || 'unavailable';
    if (ollama.diagnostics && ollama.diagnostics.step) ollamaState = ollamaState + ' · ' + String(ollama.diagnostics.step).toUpperCase();
    rows.push(pair('Ollama', ollamaState));
    rows.push(pair('Storage', storage.state || 'unknown'));

    // Network comes from the dashboard probe, not the health document.
    var net = ((hud.dashboard || {}).system || {}).network || {};
    var netState = net.interfaces == null ? 'unknown' : (Number(net.interfaces) > 0 ? 'online' : 'offline');
    rows.push(pair('Network', netState));

    panel.innerHTML = rows.join('');
  }

  function renderAiOps() {
    var task = hud.task || ((typeof state !== 'undefined' && state) ? state.task : null);
    var plan = hud.plan || ((typeof state !== 'undefined' && state) ? state.plan : null);
    var op = hud.operation || (task && task.result) || null;
    var guardian = hud.guardian || null;
    var council = hud.council || null;

    var stages = ['request', 'analysis', 'plan', 'validation', 'execution', 'result'];
    var stageState = { request: '', analysis: '', plan: '', validation: '', execution: '', result: '' };

    var opStatus = (op && op.status) || '';
    var taskState = (task && task.state) || '';

    if (task) stageState.request = 'done';
    if (plan) stageState.analysis = 'done';
    if (plan && (plan.status === 'planned' || plan.status === 'awaiting_confirmation' || (plan.commands && plan.commands.length))) stageState.plan = 'done';
    else if (plan) stageState.plan = 'active';
    stageState.validation = guardian ? 'done' : (plan ? 'active' : '');

    var running = ['started', 'running', 'awaiting_confirmation'].indexOf(opStatus) !== -1 || taskState === 'EXECUTING' || taskState === 'OBSERVING';
    var succeeded = ['succeeded', 'completed'].indexOf(opStatus) !== -1 || taskState === 'COMPLETED';
    var failed = ['failed', 'timed_out', 'cancelled'].indexOf(opStatus) !== -1 || taskState === 'FAILED';

    if (running) stageState.execution = 'active';
    else if (succeeded) { stageState.execution = 'done'; stageState.result = 'done'; }
    else if (failed) { stageState.execution = 'fail'; stageState.result = 'fail'; }

    var signature = [stageState.request, stageState.analysis, stageState.plan, stageState.validation, stageState.execution, stageState.result,
      taskState, opStatus, plan ? plan.status : '', task ? task.id : ''].join('|');
    if (signature === hud.aiOpsSignature) return;
    hud.aiOpsSignature = signature;

    var pipeline = el('ai-ops-pipeline');
    if (pipeline) {
      Array.prototype.forEach.call(pipeline.querySelectorAll('.pipeline-stage'), function (node, index) {
        var key = stages[index];
        node.className = 'pipeline-stage' + (stageState[key] ? ' ' + stageState[key] : '');
      });
    }

    var badge = el('ai-ops-state');
    if (badge) {
      var label = 'IDLE';
      var tone = 'badge-muted';
      if (running) { label = taskState === 'EXECUTING' || taskState === 'OBSERVING' ? taskState : 'EXECUTING'; tone = 'badge-amber'; }
      else if (plan && plan.status === 'planned') { label = 'AWAITING APPROVAL'; tone = 'badge-amber'; }
      else if (taskState === 'WAITING_FOR_APPROVAL') { label = 'AWAITING APPROVAL'; tone = 'badge-amber'; }
      else if (succeeded) { label = 'COMPLETED'; tone = 'badge-green'; }
      else if (failed) { label = 'FAILED'; tone = 'badge-red'; }
      else if (taskState) { label = taskState; tone = 'badge-muted'; }
      badge.textContent = label;
      badge.className = 'badge ' + tone;
    }

    var workers = (plan && plan.workers) || [];
    var selected = (council && council.selected) || [];
    var assistant = selected.join(', ') || (workers.map(function (w) { return w.id; }).filter(function (id) { return id !== 'local-model'; }).join(', ')) || 'deterministic planner';
    setText('ai-ops-assistant', assistant);
    var localAi = (op && op.analysis && op.analysis.local_ai) || (task && task.result && task.result.local_ai) || null;
    setText('ai-ops-model', (localAi && (localAi.state || localAi.route)) || '—');
    setText('ai-ops-task', task ? String(task.id || '').slice(0, 12) + ' · ' + (opStatus || taskState || '') : '—');
    setText('ai-ops-guardian', guardian ? (guardian.decision || guardian.risk || '') : '—');
  }

  window.updateAiOpsHud = function (snapshot) {
    if (snapshot) {
      if (snapshot.task) hud.task = snapshot.task;
      if (snapshot.plan) hud.plan = snapshot.plan;
      if (snapshot.operation) hud.operation = snapshot.operation;
      if (snapshot.guardian) hud.guardian = snapshot.guardian;
      if (snapshot.council) hud.council = snapshot.council;
    }
    renderAiOps();
  };

  async function loadTelemetry() {
    try {
      var data = await api('/api/dashboard');
      hud.dashboard = data.dashboard || {};
    } catch (e) {
      hud.dashboard = {};
    }
    renderTelemetry();
    renderDiagnostics();
    renderFooter();
  }

  async function loadDiagnostics() {
    try {
      var data = await api('/api/health');
      hud.health = data.health || {};
      hud.backendStatus = data.backend || null;
    } catch (e) {
      hud.health = {};
      hud.backendStatus = null;
    }
    renderOllama();
    renderDiagnostics();
    renderFooter();
  }

  function renderFooter() {
    var dash = hud.dashboard || {};
    var backend = hud.backendStatus || null;
    setText('ft-backend', backend ? String(backend).toUpperCase() : null);
    setDot('ft-backend-dot', !backend ? 'off' : String(backend).toLowerCase() === 'online' ? '' : 'off');
    var host = dash.host || {};
    var distro = (host.distribution && (host.distribution.id || host.distribution.pretty_name)) || '';
    var hostVal = (distro + (host.architecture ? ' · ' + host.architecture : '')).trim();
    setText('ft-host', hostVal || null);
    setText('ft-privacy', dash.privacy_mode ? String(dash.privacy_mode).toUpperCase() : null);
    setText('ft-offline', dash.offline == null ? null : (dash.offline ? 'ON' : 'OFF'));
    var eng = dash.engagements || {};
    setText('ft-engagements', eng.active == null ? null : eng.active + ' / ' + (eng.total == null ? '?' : eng.total));
    setText('ft-refreshed', 'REFRESHED ' + new Date().toLocaleTimeString());
  }

  function refresh() {
    if (hud.inflight) return hud.inflight;
    hud.inflight = Promise.all([loadTelemetry(), loadDiagnostics()]).finally(function () { hud.inflight = null; });
    return hud.inflight;
  }

  function tickTelemetry() {
    if (document.hidden) return;
    refresh();
  }

  function bind() {
    var refreshBtn = el('refresh-telemetry');
    if (refreshBtn && !refreshBtn._hudBound) {
      refreshBtn._hudBound = true;
      refreshBtn.addEventListener('click', refresh);
    }
  }

  window.refreshHud = refresh;
  window.stopHud = function () {
    if (hud.timer) { clearInterval(hud.timer); hud.timer = null; }
  };

  function boot() {
    if (hud.booted) return;
    hud.booted = true;
    bind();
    renderAiOps();
    refresh();
    hud.timer = setInterval(tickTelemetry, TELEMETRY_INTERVAL_MS);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
