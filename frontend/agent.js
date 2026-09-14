/* Agent Mode: goal-directed think → plan → Guardian → execute → observe runs.
 * Thin client of /api/agent/*: starts runs, streams the visible transcript,
 * approves exact paused steps, and stops runs. No simulation: every line
 * rendered comes from a recorded sidecar event. */
(function () {
  'use strict';

  var agent = { runId: null, since: 0, es: null, poll: null, lastPlan: null, loading: false };

  function box(id) { return document.getElementById(id); }

  function closeStream() {
    if (agent.es) { try { agent.es.close(); } catch (_) {} agent.es = null; }
    if (agent.poll) { clearInterval(agent.poll); agent.poll = null; }
  }

  function statusBadge(status) {
    var map = { running: 'badge ok', awaiting_approval: 'badge warn', finished: 'badge' };
    return map[status] || 'badge badge-muted';
  }

  function outcomeBadge(outcome) {
    var good = outcome === 'achieved';
    var bad = outcome === 'error' || outcome === 'needs_model' || outcome === 'interrupted';
    return 'badge ' + (good ? 'ok' : (bad ? 'bad' : 'warn'));
  }

  function renderGuidance(guidance) {
    if (!guidance || !guidance.length) return '';
    var rows = guidance.map(function (item) {
      return '<div class="context-row"><label>' + esc(item.provider || 'models') + '</label><span>' +
        esc(item.action || '') + (item.detail ? ' <small>' + esc(item.detail) + '</small>' : '') + '</span></div>';
    }).join('');
    return '<div class="plan-card"><div class="plan-notes">' + rows + '</div>' +
      '<button class="primary-button" id="agent-open-models" type="button">OPEN MODELS</button></div>';
  }

  function wireModelsButton(scope) {
    var btn = (scope || document).querySelector('#agent-open-models');
    if (btn) btn.addEventListener('click', function () {
      if (typeof window.setView === 'function') window.setView('models');
      var surface = box('agent-window');
      if (surface) surface.hidden = true;
    });
  }

  function renderEvent(event) {
    var kind = event.kind;
    var p = event.payload || {};
    var host = box('agent-transcript');
    if (!host) return;
    var empty = host.querySelector('.empty-inline');
    if (empty) empty.remove();
    var wrap = document.createElement('div');
    wrap.className = 'stream-line';
    wrap.setAttribute('data-seq', String(event.seq));
    var html = '';
    if (kind === 'run_started') {
      html = '<div class="plan-card"><div class="plan-summary"><div class="plan-objective"><span>GOAL</span>' +
        esc(p.goal || '') + '</div><span class="badge">STEPS ≤ ' + esc(p.max_steps || '?') + '</span></div>' +
        '<ul class="plan-notes"><li>' + esc((p.preflight && p.preflight.message) || 'Run started.') + '</li></ul></div>';
    } else if (kind === 'think') {
      var steps = (p.next_steps || []).map(function (s) { return '<li>' + esc(s) + '</li>'; }).join('');
      html = '<div class="plan-card"><div class="plan-summary"><div class="plan-objective"><span>THINK · STEP ' +
        esc(p.step || '?') + '</span>' + esc(p.fact_summary || p.message || 'thinking…') + '</div>' +
        '<span class="badge">' + esc(p.provider || '?') + ' · ' + esc(p.model || '?') + '</span></div>' +
        (steps ? '<ul class="plan-notes">' + steps + '</ul>' : '') +
        (p.unknowns ? '<p class="form-note">Unknowns: ' + esc(p.unknowns) + '</p>' : '') +
        (p.caution ? '<p class="form-note">' + esc(p.caution) + '</p>' : '') + '</div>';
      var modelEl = box('agent-run-model');
      if (modelEl && p.model) modelEl.textContent = (p.provider || '') + ' · ' + p.model;
    } else if (kind === 'step_planned') {
      agent.lastPlan = p;
      var commands = (p.commands || []).map(function (c) { return '<li><code>' + esc(c) + '</code></li>'; }).join('');
      var notes = (p.notes || []).map(function (n) { return '<li>' + esc(n) + '</li>'; }).join('');
      html = '<div class="plan-card"><div class="plan-summary"><div class="plan-objective"><span>PLAN · STEP ' +
        esc(p.step || '?') + ' · ' + esc(p.kind || '?') + '</span>' + esc(p.request || '') + '</div>' +
        '<span class="badge ' + (p.risk === 'low' ? 'ok' : 'warn') + '">' + esc(p.risk || '?') + '</span></div>' +
        (commands ? '<ul class="plan-notes">' + commands + '</ul>' : '') +
        (notes ? '<ul class="plan-notes">' + notes + '</ul>' : '') +
        (p.approval_phrase ? '<p class="form-note">⌁ ' + esc(p.approval_phrase) + '</p>' : '') + '</div>';
    } else if (kind === 'guardian') {
      var reasons = (p.reasons || []).map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('');
      html = '<div class="context-row"><label>GUARDIAN · STEP ' + esc(p.step || '?') + '</label><span class="' +
        (p.decision === 'auto' ? 'badge ok' : (p.decision === 'blocked' ? 'badge bad' : 'badge warn')) + '">' +
        esc(p.decision || '?') + '</span></div>' + (reasons ? '<ul class="plan-notes">' + reasons + '</ul>' : '');
    } else if (kind === 'step_started') {
      html = '<div class="context-row"><label>EXECUTE · STEP ' + esc(p.step || '?') + '</label><span>' +
        (p.approved ? 'operator-approved step started' : 'Guardian-auto step started') + '</span></div>';
    } else if (kind === 'step_finished') {
      var blocks = (p.commands || []).map(function (c) {
        return '<div class="plan-card"><div class="plan-summary"><div class="plan-objective"><span>' +
          esc(c.status || '?') + (c.exit_code !== null && c.exit_code !== undefined ? ' · exit ' + esc(c.exit_code) : '') +
          '</span><code>' + esc(c.display || '') + '</code></div></div>' +
          (c.stdout_tail ? '<pre>' + esc(c.stdout_tail) + '</pre>' : '') +
          (c.stderr_tail ? '<pre>' + esc(c.stderr_tail) + '</pre>' : '') + '</div>';
      }).join('');
      html = '<div class="context-row"><label>RESULT · STEP ' + esc(p.step || '?') + '</label><span class="badge">' +
        esc(p.status || '?') + '</span></div>' + blocks;
    } else if (kind === 'verdict') {
      html = '<div class="context-row"><label>OBJECTIVE · STEP ' + esc(p.step || '?') + '</label><span class="badge ' +
        (p.achieved ? 'ok' : 'warn') + '">' + (p.achieved ? 'ACHIEVED' : 'NOT YET') + '</span></div>' +
        '<p class="form-note">' + esc(p.reason || '') + '</p>';
    } else if (kind === 'paused') {
      html = '<div class="plan-card"><div class="plan-summary"><div class="plan-objective"><span>PAUSED</span>' +
        esc(p.reason || 'Waiting for approval.') + '</div><span class="badge warn">AWAITING APPROVAL</span></div></div>';
      renderApproveCard(p);
    } else if (kind === 'approved' || kind === 'resumed') {
      html = '<div class="context-row"><label>RUN</label><span>' + esc(kind === 'approved' ? 'Step approved — continuing.' : 'Run resumed.') + '</span></div>';
      hideApproveCard();
    } else if (kind === 'stopped') {
      html = '<div class="context-row"><label>RUN</label><span>Stopped by the operator.</span></div>';
      hideApproveCard();
    } else if (kind === 'finished') {
      html = '<div class="plan-card"><div class="plan-summary"><div class="plan-objective"><span>RUN ' +
        esc(p.outcome || 'finished') + '</span>' + esc(p.reason || '') + '</div><span class="' +
        outcomeBadge(p.outcome) + '">' + esc(p.outcome || '') + '</span></div></div>' +
        (p.outcome === 'needs_model' ? renderGuidance(p.guidance) : '');
      hideApproveCard();
    } else if (kind === 'error') {
      html = '<p class="form-note">Error: ' + esc(p.message || 'unknown') + '</p>';
    } else {
      html = '<p class="form-note">' + esc(p.message || kind) + '</p>';
    }
    wrap.innerHTML = html;
    host.appendChild(wrap);
    wireModelsButton(wrap);
    host.scrollTop = host.scrollHeight;
  }

  function renderApproveCard(pause) {
    var card = box('agent-approve');
    if (!card) return;
    var plan = agent.lastPlan || {};
    var commands = (plan.commands || []).map(function (c) { return '<li><code>' + esc(c) + '</code></li>'; }).join('');
    card.hidden = false;
    card.innerHTML = '<div class="plan-card"><div class="plan-summary"><div class="plan-objective">' +
      '<span>APPROVE THIS EXACT STEP</span>' + esc(pause.reason || '') + '</div>' +
      '<span class="badge warn">' + esc(plan.risk || '') + ' · ' + esc(plan.kind || '') + '</span></div>' +
      (commands ? '<ul class="plan-notes">' + commands + '</ul>' : '') +
      (plan.approval_phrase ? '<p class="form-note">⌁ ' + esc(plan.approval_phrase) + '</p>' : '') +
      '<div class="worker-row"><button class="primary-button" id="agent-approve-btn" type="button">APPROVE &amp; CONTINUE</button> ' +
      '<button class="text-button danger" id="agent-reject-btn" type="button">STOP RUN</button></div></div>';
    var approveBtn = box('agent-approve-btn');
    if (approveBtn) approveBtn.addEventListener('click', approveCurrentRun);
    var rejectBtn = box('agent-reject-btn');
    if (rejectBtn) rejectBtn.addEventListener('click', stopCurrentRun);
    card.scrollIntoView({ block: 'nearest' });
  }

  function hideApproveCard() {
    var card = box('agent-approve');
    if (card) { card.hidden = true; card.innerHTML = ''; }
  }

  function renderRunHeader(run) {
    var statusEl = box('agent-run-status');
    if (statusEl && run) {
      statusEl.className = statusBadge(run.status);
      statusEl.textContent = run.status.toUpperCase() + ((run.summary && run.summary.outcome) ? ' · ' + run.summary.outcome.toUpperCase() : '');
    }
    var stepEl = box('agent-run-step');
    if (stepEl && run) stepEl.textContent = 'step ' + ((run.config && run.config.step_index) || 0) + ' / ' + ((run.config && run.config.max_steps) || '?');
    var startBtn = box('agent-start');
    if (startBtn) startBtn.disabled = !!run && run.status !== 'finished';
    var stopBtn = box('agent-stop');
    if (stopBtn) stopBtn.disabled = !run || run.status === 'finished';
  }

  function applyPayload(payload) {
    if (!payload || !payload.run) return;
    agent.runId = payload.run.id;
    renderRunHeader(payload.run);
    (payload.events || []).forEach(function (event) {
      if (event.seq > agent.since) {
        agent.since = event.seq;
        renderEvent(event);
      }
    });
    if (payload.run.status === 'finished') closeStream();
    if (payload.run.status !== agent.lastStatus) {
      agent.lastStatus = payload.run.status;
      refreshRuns(false);
    }
  }

  function startStream() {
    closeStream();
    if (!agent.runId) return;
    if (typeof EventSource === 'undefined') return startPolling();
    var url = '/api/agent/runs/' + encodeURIComponent(agent.runId) + '/stream?since=' + agent.since;
    var es;
    try {
      es = new EventSource(url);
    } catch (_) {
      return startPolling();
    }
    agent.es = es;
    es.onmessage = function (message) {
      try {
        applyPayload(JSON.parse(message.data));
      } catch (_) {}
    };
    es.onerror = function () {
      try { es.close(); } catch (_) {}
      agent.es = null;
      startPolling();
    };
  }

  function startPolling() {
    if (agent.poll || !agent.runId) return;
    agent.poll = setInterval(function () {
      api('/api/agent/runs/' + encodeURIComponent(agent.runId)).then(function (payload) {
        // Poll endpoint returns the full transcript; applyPayload dedupes by seq.
        applyPayload(payload);
      }).catch(function () {});
    }, 2000);
  }

  function resetTranscript(message) {
    var host = box('agent-transcript');
    if (host) host.innerHTML = '<div class="empty-inline">' + esc(message || 'No run selected.') + '</div>';
    agent.since = 0;
    agent.lastPlan = null;
    hideApproveCard();
  }

  function loadRun(runId) {
    closeStream();
    resetTranscript('Loading transcript…');
    agent.runId = runId;
    api('/api/agent/runs/' + encodeURIComponent(runId)).then(function (payload) {
      resetTranscript('Empty transcript.');
      applyPayload(payload);
      if (payload.run && payload.run.status !== 'finished') startStream();
    }).catch(function (err) {
      resetTranscript('Could not load this run: ' + err.message);
    });
  }

  function refreshRuns(announce) {
    var host = box('agent-runs');
    if (!host) return;
    api('/api/agent/runs').then(function (payload) {
      var runs = payload.runs || [];
      if (!runs.length) {
        host.innerHTML = '<div class="empty-inline">No agent runs yet. Describe a goal above and press START RUN.</div>';
        return;
      }
      host.innerHTML = '';
      runs.forEach(function (run) {
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'text-button';
        btn.textContent = (run.id || '').slice(0, 8) + ' · ' + run.status +
          (run.summary && run.summary.outcome ? ' · ' + run.summary.outcome : '') + ' · ' + (run.goal || '').slice(0, 60);
        if (run.id === agent.runId) btn.disabled = true;
        btn.addEventListener('click', function () { loadRun(run.id); });
        host.appendChild(btn);
      });
      if (announce) toast('Run list refreshed.');
    }).catch(function () {});
  }

  function startCurrentRun() {
    var goalEl = box('agent-goal');
    var stepsEl = box('agent-max-steps');
    var goal = goalEl ? goalEl.value.trim() : '';
    if (!goal) { toast('Describe a goal first.', true); return; }
    var maxSteps = stepsEl ? parseInt(stepsEl.value, 10) : 5;
    closeStream();
    resetTranscript('Starting run…');
    agent.runId = null;
    renderRunHeader({ status: 'running', config: { step_index: 0, max_steps: maxSteps }, summary: {} });
    api('/api/agent/runs', { method: 'POST', body: { goal: goal, max_steps: maxSteps } }).then(function (payload) {
      resetTranscript('Empty transcript.');
      applyPayload({ run: payload.run, events: [] });
      loadRun(payload.run.id);
      toast(payload.run.status === 'finished' ? 'Run refused: see the transcript.' : 'Agent run started.');
    }).catch(function (err) {
      resetTranscript('Could not start: ' + err.message);
      renderRunHeader(null);
      toast(err.message, true);
    });
  }

  function approveCurrentRun() {
    if (!agent.runId || !agent.lastPlan) { toast('Nothing is waiting for approval.', true); return; }
    api('/api/agent/runs/' + encodeURIComponent(agent.runId) + '/approve',
      { method: 'POST', body: { plan_id: agent.lastPlan.plan_id, confirm: true } }).then(function (payload) {
      applyPayload({ run: payload.run, events: [] });
      toast('Step approved — the run continues.');
      startStream();
    }).catch(function (err) {
      toast(err.message, true);
    });
  }

  function stopCurrentRun() {
    if (!agent.runId) return;
    api('/api/agent/runs/' + encodeURIComponent(agent.runId) + '/stop', { method: 'POST', body: {} }).then(function (payload) {
      applyPayload({ run: payload.run, events: [] });
      toast('Stop requested.');
      startStream();
    }).catch(function (err) {
      toast(err.message, true);
    });
  }

  function wireOnce() {
    var root = box('agent-window');
    if (!root || root.getAttribute('data-agent-wired') === '1') return;
    root.setAttribute('data-agent-wired', '1');
    var startBtn = box('agent-start');
    if (startBtn) startBtn.addEventListener('click', startCurrentRun);
    var stopBtn = box('agent-stop');
    if (stopBtn) stopBtn.addEventListener('click', stopCurrentRun);
    var refreshBtn = box('agent-refresh');
    if (refreshBtn) refreshBtn.addEventListener('click', function () { refreshRuns(true); });
  }

  window.loadAgent = function () {
    wireOnce();
    refreshRuns(false);
    if (agent.runId) {
      loadRun(agent.runId);
    } else {
      api('/api/agent/runs').then(function (payload) {
        var runs = payload.runs || [];
        if (runs.length && !agent.runId) loadRun(runs[0].id);
      }).catch(function () {});
    }
  };
})();
