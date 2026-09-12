/* AI Operations pop-up: the step-by-step trace of the local agent connecting
   to models and AI assistants. Every state is derived from the live routing
   snapshot (fuzzy ranking) and the last turn's local_ai record — nothing is
   fabricated, and every missing layer carries the exact commands to run in
   the main Linux terminal plus COPY / OPEN IN TERMINAL actions. */
(function () {
  'use strict';

  var aiops = {
    routing: null,
    gguf: null,
    lastTurn: null,
    install: null,
    timer: null
  };

  function box(id) { return document.getElementById(id); }
  function esc(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[c]));
  }

  var PROVIDER_META = {
    gguf: { index: 1, title: 'On-device GGUF', sub: 'primary · your own *.gguf files' },
    ollama: { index: 2, title: 'Ollama loopback', sub: 'secondary · 127.0.0.1:11434' },
    council: { index: 3, title: 'Agent council', sub: 'advisory · third-party assistants' },
    deterministic: { index: 4, title: 'Deterministic core', sub: 'always available · authoritative' }
  };

  function scoreOf(ranking, provider) {
    var entry = (ranking || []).find(function (item) { return item.provider === provider; });
    return entry ? entry.score : null;
  }

  function stepState(provider, routing, gguf) {
    var p = (routing && routing.providers) || {};
    var detail = p[provider] || {};
    var state = String(detail.state || 'unknown').toLowerCase();
    var winner = routing && routing.winner === provider;
    var good = ['healthy', 'ready', 'responded', 'running', 'installed', 'online'].indexOf(state) !== -1;
    var tone = good ? 'ok' : (['unavailable', 'absent', 'failed', 'down', 'disabled', 'not installed', 'offline', 'stopped'].indexOf(state) !== -1 ? 'bad' : 'warn');
    var detailText = '';
    if (provider === 'gguf') {
      var g = gguf || {};
      var files = g.files || [];
      var valid = files.filter(function (f) { return f.valid; });
      var engine = (g.engine || {}).state || 'unknown';
      detailText = files.length
        ? files.length + ' file(s) found · ' + valid.length + ' valid · engine ' + engine
        : 'no *.gguf files found';
      if (detail.reason && detail.state) detailText += ' · ' + detail.reason;
    } else if (provider === 'ollama') {
      detailText = 'state ' + state + ((detail.models != null) ? ' · ' + detail.models + ' model(s) in pool' : '');
      if (detail.endpoint) detailText += ' · ' + detail.endpoint;
    } else if (provider === 'council') {
      var agents = detail.agents || {};
      detailText = agents.total != null
        ? agents.available + '/' + agents.total + ' agent adapter(s) available'
        : (detail.reason || 'not probed');
    } else {
      detailText = detail.reason || 'Planning, Guardian and execution run without a model.';
    }
    var label;
    if (winner) label = 'SELECTED';
    else if (good) label = 'READY · FALLBACK';
    else label = 'SKIPPED';
    return { state: state, tone: tone, winner: winner, detail: detailText, label: label, raw: detail };
  }

  function commandBox(title, commands, extraNote) {
    var lines = Array.isArray(commands) ? commands : String(commands || '').split('\n');
    var text = lines.join('\n').trim();
    if (!text) return '';
    return '<div class="install-box">' +
      '<div class="install-box-head"><strong>' + esc(title) + '</strong>' +
      '<div class="command-actions">' +
      '<button class="secondary-button" data-aiops-copy="' + esc(text) + '">COPY</button>' +
      '<button class="secondary-button" data-aiops-terminal="' + esc(text) + '">OPEN IN TERMINAL</button>' +
      '</div></div>' +
      (extraNote ? '<p class="form-note">' + esc(extraNote) + '</p>' : '') +
      '<pre class="install-commands">' + esc(text) + '</pre></div>';
  }

  function renderHelp(routing, gguf) {
    var section = box('ai-ops-help-section');
    var host = box('ai-ops-help');
    if (!section || !host) return;
    var p = (routing && routing.providers) || {};
    var ggufDetail = p.gguf || {};
    var ollamaDetail = p.ollama || {};
    var files = (gguf && gguf.files) || [];
    var validFiles = files.filter(function (f) { return f.valid; });
    var engine = ((gguf && gguf.engine) || {}).state || 'unknown';
    var boxes = [];

    if (!files.length) {
      boxes.push(commandBox(
        'Step 1 — add on-device GGUF models (primary layer)',
        [
          'mkdir -p ~/linux-vortex-terminal/models',
          '# put e.g. Llama-3.2-3B-Instruct-Q4_K_M.gguf and Qwen2.5-3B-Instruct-Q4_K_M.gguf in that folder',
          'then click REFRESH in the app (or: ls -lh ~/linux-vortex-terminal/models)'
        ],
        'GGUF files are your own on-device models; they answer first when a local engine is present.'
      ));
    } else if (engine === 'unavailable') {
      boxes.push(commandBox(
        'Step 1 — install a local GGUF engine so the ' + validFiles.length + ' found model(s) can load',
        [
          '# option A: Python engine (recommended)',
          'python3 -m pip install --user llama-cpp-python',
          '# option B: llama.cpp CLI, then put llama-cli on PATH',
          'git clone https://github.com/ggml-org/llama.cpp.git && cd llama.cpp && cmake -B build && cmake --build build --config Release -j'
        ],
        'After installing, click REFRESH ALL. Ollama and the council remain as fallback until then.'
      ));
    }

    if (!ollamaDetail.installed && ['unavailable', 'absent', 'not found', 'offline'].indexOf(String(ollamaDetail.state || '').toLowerCase()) !== -1) {
      boxes.push(commandBox(
        'Step 2 — install the Ollama loopback runtime (secondary layer)',
        [
          'curl -fsSL https://ollama.com/install.sh | sh',
          'ollama serve   # or use the in-app installer: Agents → Local model runtime → INSTALL OLLAMA'
        ],
        'The in-app installer verifies the release size and published SHA-256; the terminal route is the upstream script.'
      ));
    } else if (String(ollamaDetail.state || '').toLowerCase() === 'installed' || (ollamaDetail.installed && !/running|healthy/.test(String(ollamaDetail.state || '').toLowerCase()))) {
      boxes.push(commandBox(
        'Step 2 — start the Ollama service',
        ['ollama serve   # or: Agents → Local model runtime → START SERVICE'],
        'Ollama binds to loopback only; models are pulled from the Models view.'
      ));
    }

    var councilDetail = p.council || {};
    var agents = councilDetail.agents || {};
    if (agents.total && agents.available < agents.total) {
      var missing = (agents.missing_names || []).slice(0, 6);
      boxes.push(
        '<div class="install-box"><div class="install-box-head"><strong>Step 3 — make missing AI assistants available</strong></div>' +
        '<p class="form-note">' + esc(agents.available + ' of ' + agents.total + ' agent adapter(s) are available on this host.') +
        (missing.length ? ' Missing: ' + esc(missing.join(', ')) + '.' : '') +
        ' Open the Agents view, click INSTALL PROPOSAL on the one you need, then COPY / OPEN IN TERMINAL the exact commands.</p>' +
        '<div class="command-actions"><button class="secondary-button" data-aiops-view="agents">OPEN AGENTS VIEW</button>' +
        '<button class="secondary-button" data-aiops-copy="vortex agents --json">COPY CLI CHECK</button></div></div>'
      );
    }

    host.innerHTML = boxes.join('') || '<div class="empty-inline">All available layers are accounted for. Install any optional layer above and it will rank on the next REFRESH.</div>';
    host.querySelectorAll('[data-aiops-copy]').forEach(function (btn) {
      btn.addEventListener('click', function () { if (typeof copyText === 'function') copyText(btn.dataset.aiopsCopy, 'Commands copied — run them in your main Linux terminal.'); });
    });
    host.querySelectorAll('[data-aiops-terminal]').forEach(function (btn) {
      btn.addEventListener('click', function () { if (typeof openInTerminal === 'function') openInTerminal(btn.dataset.aiopsTerminal, 'Install commands'); });
    });
    host.querySelectorAll('[data-aiops-view]').forEach(function (btn) {
      btn.addEventListener('click', function () { if (typeof setView === 'function') setView(btn.dataset.aiopsView); });
    });
    section.hidden = !boxes.length;
  }

  function renderSteps() {
    var host = box('ai-ops-steps');
    var resolved = box('ai-ops-resolved');
    if (!host) return;
    var routing = aiops.routing;
    if (!routing) {
      host.innerHTML = '<div class="empty-inline">Routing snapshot unavailable — is the backend online?</div>';
      if (resolved) resolved.hidden = true;
      return;
    }
    var providers = ['gguf', 'ollama', 'council', 'deterministic'];
    host.innerHTML = providers.map(function (key) {
      var meta = PROVIDER_META[key];
      var info = stepState(key, routing, aiops.gguf);
      var score = scoreOf(routing.ranking, key);
      var scoreText = score == null ? '' : 'score ' + Number(score).toFixed(2);
      return '<div class="ai-ops-step ' + (info.winner ? 'selected' : '') + ' ' + info.tone + '">' +
        '<div class="ai-ops-step-node"><span class="step-index">' + meta.index + '</span></div>' +
        '<div class="ai-ops-step-body">' +
        '<div class="ai-ops-step-head"><span class="ai-ops-step-title">' + esc(meta.title) + '</span>' +
        '<span class="ai-ops-step-sub">' + esc(meta.sub) + '</span>' +
        '<span class="badge ' + (info.winner ? 'badge-green' : info.tone === 'bad' ? 'badge-red' : info.tone === 'ok' ? 'badge-muted' : 'badge-amber') + '">' + esc(info.label) + (scoreText ? ' · ' + esc(scoreText) : '') + '</span></div>' +
        '<div class="ai-ops-step-detail">' + esc(info.detail) + '</div>' +
        '</div></div>';
    }).join('');
    if (resolved) {
      resolved.hidden = false;
      resolved.innerHTML = '<span class="resolved-mark">↳</span><strong>RESOLVED → ' + esc(String(routing.winner || 'deterministic').toUpperCase()) + '</strong>' +
        '<span class="form-note">confidence ' + esc(routing.confidence || 'unavailable') + ' · ' + esc(routing.reason || '') + '</span>';
    }
  }

  function turnRow(label, spanHtml) {
    return '<div class="ai-ops-turn-row"><label>' + esc(label) + '</label><span>' + spanHtml + '</span></div>';
  }

  function renderLastTurn() {
    var section = box('ai-ops-turn-section');
    var host = box('ai-ops-turn');
    if (!section || !host) return;
    var turn = aiops.lastTurn;
    if (!turn) { section.hidden = true; return; }
    section.hidden = false;
    var localAi = (turn.operation && turn.operation.analysis && turn.operation.analysis.local_ai) || turn.localAi || {};
    var route = localAi.route || {};
    var selected = route.selected || [];
    var responses = localAi.responses || [];
    var fuzzy = localAi.fuzzy || {};
    var synthesis = localAi.synthesis || {};
    var rows = [];
    if (selected.length) {
      rows.push(turnRow('RAN', selected.map(function (item) {
        return esc((item.provider || 'model') + ':' + (item.model || '?') + ' (' + (item.role || 'advisory') + ')');
      }).join(' · ')));
    } else {
      rows.push(turnRow('RAN', 'no model responded — deterministic core produced the result'));
    }
    // The agent's own explanation of this turn — its "thinking", verbatim.
    if (localAi.message) rows.push(turnRow('THINKING', esc(localAi.message)));
    if (route.reason || route.strategy) rows.push(turnRow('STRATEGY', [route.reason, route.strategy].filter(Boolean).map(esc).join(' · ')));
    var prefs = route.preferences || {};
    var roleBits = ['primary', 'planner', 'fast', 'specialist'].reduce(function (acc, role) {
      var p = prefs[role];
      if (!p) return acc;
      acc.push(role + ' ' + (p.resolved || p.configured || '?') + ' (' + (p.state || 'unknown') + ')');
      return acc;
    }, []);
    if (roleBits.length) rows.push(turnRow('MODELS SET', roleBits.map(esc).join(' · ')));
    if (responses.length) {
      rows.push(turnRow('LATENCY', responses.map(function (r) {
        return esc((r.model || '?') + ' ' + (r.latency_ms != null ? r.latency_ms + ' ms' : 'n/a'));
      }).join(' · ')));
    }
    rows.push(turnRow('CONFIDENCE', esc(fuzzy.confidence || 'unavailable') + ' · ' + esc(fuzzy.evidence_basis || 'plan-only')));
    if (synthesis.fact_summary) rows.push(turnRow('FACTS', esc(synthesis.fact_summary)));
    if (synthesis.meaning) rows.push(turnRow('MEANING', esc(synthesis.meaning)));
    if (synthesis.unknowns) rows.push(turnRow('UNKNOWN', esc(synthesis.unknowns)));
    var guardian = turn.guardian || (turn.operation && turn.operation.analysis && turn.operation.analysis.guardian) || null;
    if (guardian && (guardian.decision || guardian.risk)) {
      rows.push(turnRow('GUARDIAN', esc(guardian.decision || '') + (guardian.risk ? ' · risk ' + esc(guardian.risk) : '')));
    }
    host.innerHTML = rows.join('');
  }

  async function loadInstallAll() {
    var section = box('ai-ops-install-section');
    var host = box('ai-ops-install');
    if (!section || !host) return;
    try {
      var data = await api('/api/install/commands');
      var payload = data.install_commands || {};
      aiops.install = payload;
      var sections = payload.sections || [];
      if (!sections.length) { section.hidden = true; return; }
      section.hidden = false;
      var combined = payload.combined || '';
      host.innerHTML =
        '<p class="form-note">' + esc(sections.length) + ' item(s) missing on this host. Copy the whole block and paste it into your main Linux terminal, then return and click REFRESH ALL. VORTEX never runs any of this itself.</p>' +
        '<div class="command-actions"><button class="secondary-button" data-aiops-copy-all>COPY ALL COMMANDS</button>' +
        '<button class="secondary-button" data-aiops-terminal-all>OPEN IN TERMINAL</button></div>' +
        '<pre class="install-commands">' + esc(combined) + '</pre>';
      host.querySelector('[data-aiops-copy-all]').addEventListener('click', function () {
        if (typeof copyText === 'function') copyText(combined, 'All install commands copied — paste them in your main Linux terminal.');
      });
      host.querySelector('[data-aiops-terminal-all]').addEventListener('click', function () {
        if (typeof openInTerminal === 'function') openInTerminal(combined, 'Install everything missing');
      });
    } catch (e) {
      if (!aiops.install) host.innerHTML = '<div class="empty-inline">Install block unavailable: ' + esc(e.message) + '</div>';
    }
  }

  function renderAll() {
    renderSteps();
    renderHelp(aiops.routing, aiops.gguf);
    renderLastTurn();
    loadInstallAll();
  }

  async function loadAiOps(fresh) {
    var host = box('ai-ops-steps');
    if (host && !aiops.routing) host.innerHTML = '<div class="empty-inline">Opening connection trace…</div>';
    try {
      var data = await api(fresh ? '/api/ollama?fresh=1' : '/api/ollama');
      aiops.routing = data.routing || null;
      aiops.gguf = (data.models && data.models.gguf) || null;
      renderAll();
    } catch (e) {
      if (aiops.routing) return; // keep the last good trace when the backend hiccups
      if (host) host.innerHTML = '<div class="empty-inline">Connection trace unavailable: ' + esc(e.message) + '</div>';
    }
  }

  window.loadAiOps = loadAiOps;
  window.renderAiOpsRouting = function (routing) {
    if (routing) {
      aiops.routing = routing;
      if (box('ai-ops-window') && !box('ai-ops-window').hidden) renderAll();
    }
  };

  // Fed by hud.js on every task/plan/operation snapshot so the LAST TURN
  // section stays in step with the plan card without an extra round trip.
  window.updateAiOpsTurn = function (snapshot) {
    var s = snapshot || {};
    if (s.operation || s.task || s.guardian) {
      aiops.lastTurn = {
        operation: s.operation || aiops.lastTurn?.operation || null,
        task: s.task || aiops.lastTurn?.task || null,
        guardian: s.guardian || aiops.lastTurn?.guardian || null,
        localAi: s.localAi
          || (s.operation && s.operation.analysis && s.operation.analysis.local_ai)
          || (s.task && s.task.result && s.task.result.local_ai)
          || null
      };
      renderLastTurn();
    }
  };

  function boot() {
    // Refresh the trace periodically while the window is open.
    aiops.timer = setInterval(function () {
      var win = box('ai-ops-window');
      if (!win || !win.hidden && win.dataset.windowState !== 'minimized' && !document.hidden) loadAiOps();
    }, 15000);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
})();
