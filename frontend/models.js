/* Vortex Models view: Ollama runtime + local model management.
   Loaded after app.js/workspace.js, which provide $, esc, api, toast, fmtDate.
   Everything here is failure-tolerant: a missing backend route or a thrown
   error renders an inline notice and never breaks the rest of the app. */
(function () {
  'use strict';

  var modelsState = { runtime: null, catalog: null, pollTimer: null, busy: {} };

  function host() { return modelsState.runtime || {}; }
  function install() { return host().install || {}; }
  function activeJobs() {
    var out = {};
    var downloads = (modelsState.catalog && modelsState.catalog.downloads) || {};
    Object.keys(downloads).forEach(function (name) {
      var job = downloads[name] || {};
      if (job.status === 'preparing' || job.status === 'downloading' || job.status === 'verifying' || job.status === 'cancelling') out[name] = job;
    });
    return out;
  }
  function pollable() {
    if (install().status === 'preparing' || install().status === 'downloading' || install().status === 'verifying' || install().status === 'installing' || install().status === 'starting' || install().status === 'cancelling') return true;
    var server = host().server || {};
    return Object.keys(activeJobs()).length > 0 || server.state === 'starting';
  }

  function fmtBytes(bytes) {
    var n = Number(bytes);
    if (!isFinite(n) || n < 0) return null;
    if (n < 1024) return n + ' B';
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB';
    if (n < 1024 * 1024 * 1024) return (n / (1024 * 1024)).toFixed(1) + ' MB';
    return (n / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
  }
  function fmtSpeed(bps) {
    var n = Number(bps);
    if (!isFinite(n) || n <= 0) return null;
    return fmtBytes(n) + '/s';
  }
  function fmtEta(seconds) {
    var n = Number(seconds);
    if (!isFinite(n) || n == null || n <= 0) return null;
    if (n < 60) return Math.round(n) + 's left';
    if (n < 3600) return Math.round(n / 60) + 'm left';
    return (n / 3600).toFixed(1) + 'h left';
  }

  // True when the underlying operation exposes real byte progress; false when
  // we can only show an indeterminate bar (no fabricated percentages).
  function measurable(job) {
    return job && job.total_bytes != null && Number(job.total_bytes) > 0;
  }
  function renderBar(job, error) {
    var cls = error ? ' error' : (job && job.status === 'completed' ? ' done' : '');
    if (measurable(job)) {
      var pct = Math.max(2, Math.min(100, Math.round(Number(job.percent) || 0)));
      return '<div class="progress' + cls + '"><i style="width:' + pct + '%"></i></div>' +
        '<div class="model-meta">' + fmtBytes(job.downloaded_bytes) + ' / ' + fmtBytes(job.total_bytes) +
        (fmtSpeed(job.speed_bps) ? ' · ' + fmtSpeed(job.speed_bps) : '') +
        (fmtEta(job.eta_seconds) ? ' · ' + fmtEta(job.eta_seconds) : '') + '</div>';
    }
    return '<div class="progress indeterminate' + cls + '"><i></i></div><div class="model-meta">progress not measurable — download is streaming</div>';
  }

  function failureLabel(reason) {
    return ({ permission: 'Permission denied', storage: 'Insufficient storage', network: 'Network failure', runtime_missing: 'Runtime not installed', pull_failed: 'Download failed', verification_failed: 'Verification failed', integration_failed: 'Advisory preference integration failed', service: 'Service failure' })[reason] || 'Install failed';
  }

  function stateClass(value, okValues) {
    okValues = okValues || ['healthy', 'installed', 'running', 'completed', 'online'];
    if (okValues.indexOf(value) !== -1) return 'ok';
    if (value === 'unavailable' || value === 'failed' || value === 'blocked' || value === 'disabled' || value === 'absent' || value === 'error') return 'bad';
    return 'warn';
  }

  function statusRow(label, value, cls) {
    return '<div class="ollama-row"><label>' + esc(label) + '</label><span class="' + esc(cls || '') + '">' + esc(value == null ? '—' : value) + '</span></div>';
  }

  function renderStatus() {
    var box = $('ollama-status');
    var actions = $('ollama-actions');
    var installBox = $('ollama-install');
    if (!box) return;
    var runtime = host();
    if (!runtime || typeof runtime.installed !== 'boolean') {
      box.innerHTML = '<div class="empty-inline">Ollama status is unavailable from the sidecar.</div>';
      if (actions) actions.innerHTML = '';
      if (installBox) installBox.hidden = true;
      return;
    }
    var apiState = runtime.api_state || 'unknown';
    var installed = runtime.installed;
    var server = runtime.server || {};
    var serviceReady = apiState === 'healthy';
    var platform = runtime.platform || {};
    var rows = [
      statusRow('INSTALLED', installed ? 'yes · ' + (runtime.path || 'ollama') : 'not found', installed ? 'ok' : 'bad'),
      statusRow('VERSION', runtime.version || runtime.api_version || 'unknown', runtime.version ? 'ok' : 'warn'),
      statusRow('SERVICE', apiState + (runtime.api_reason ? ' · ' + runtime.api_reason : ''), stateClass(apiState)),
      statusRow('ENDPOINT', runtime.endpoint || '—', ''),
      statusRow('SERVER', server.managed ? 'vortex-managed · ' + (server.state || 'stopped') : (serviceReady ? 'external service · running' : 'not managed by VORTEX'), serviceReady || server.state === 'running' ? 'ok' : stateClass(server.state)),
      statusRow('ARCH', platform.arch + (platform.supported_arch === false ? ' (no user-space build)' : ''), platform.supported_arch === false ? 'bad' : ''),
      statusRow('ARCHIVE HELPER', platform.zstd_available ? 'zstd available' : 'zstd missing — install it in Dependencies', platform.zstd_available ? 'ok' : 'warn'),
      statusRow('OFFLINE', platform.offline ? 'yes — install/download disabled' : 'no', platform.offline ? 'warn' : 'ok'),
      statusRow('DISK FREE', runtime.disk_free_gb != null ? runtime.disk_free_gb + ' GB' : 'unknown', ''),
      statusRow('MODELS', ((runtime.installed_candidates || []).length) + ' catalog model(s) matched', (runtime.installed_candidates || []).length ? 'ok' : ''),
    ];
    var preferences = (modelsState.catalog && modelsState.catalog.routing_preferences) || {};
    ['primary', 'planner', 'fast', 'specialist'].forEach(function (role) {
      var pref = preferences[role];
      if (!pref) return;
      var value = pref.state === 'active'
        ? (pref.resolved || pref.configured) + (pref.family_fallback ? ' · family fallback' : '')
        : (pref.configured || 'not configured') + ' · unavailable (router will fall back)';
      rows.push(statusRow('ROLE · ' + role.toUpperCase(), value, pref.state === 'active' ? 'ok' : 'warn'));
    });
    box.innerHTML = rows.join('');

    var installJob = install();
    var installActive = ['preparing', 'downloading', 'verifying', 'installing', 'starting', 'cancelling'].indexOf(installJob.status) !== -1;
    if (actions) {
      var actionHtml = '';
      if (!installed) {
        actionHtml = installActive ? '<button class="text-button danger" id="cancel-install-ollama">CANCEL INSTALL</button>' : '<button class="primary-button" id="install-ollama-btn">INSTALL OLLAMA</button>';
      } else if (serviceReady && !server.managed) {
        actionHtml = '<span class="form-note">EXTERNAL SERVICE ACTIVE</span>';
      } else if (server.state !== 'running') {
        actionHtml = server.state === 'starting'
          ? '<button class="primary-button" id="start-ollama-btn" disabled>STARTING SERVICE…</button>'
          : '<button class="primary-button" id="start-ollama-btn">START SERVICE</button>';
      } else {
        actionHtml = '<button class="text-button" id="stop-ollama-btn">STOP SERVICE</button>';
      }
      actions.innerHTML = actionHtml;
      var installBtn = $('install-ollama-btn');
      if (installBtn) installBtn.addEventListener('click', installOllama);
      var cancelInstallBtn = $('cancel-install-ollama');
      if (cancelInstallBtn) cancelInstallBtn.addEventListener('click', cancelInstall);
      var startBtn = $('start-ollama-btn');
      if (startBtn) startBtn.addEventListener('click', startServer);
      var stopBtn = $('stop-ollama-btn');
      if (stopBtn) stopBtn.addEventListener('click', stopServer);
    }

    if (installBox) {
      var job = installJob;
      var active = installActive;
      var failed = job.status === 'failed';
      var cancelled = job.status === 'cancelled';
      var done = job.status === 'completed';
      if (installed && !active && !failed && !done) { installBox.hidden = true; }
      else {
        installBox.hidden = false;
        var bar = renderBar(active ? job : null, failed);
        var line = job.step || (failed ? 'Install failed.' : cancelled ? 'Install cancelled.' : active ? 'Preparing install…' : 'Ollama is not installed.');
        if (failed) line += ' — ' + (failureLabel(job.failure_reason) + (job.error ? ': ' + job.error : ''));
        if (job.executable_verified) line += ' · executable ' + job.executable_verified;
        if (job.api_verified) line += ' · API ' + job.api_verified;
        var controls = (installed || done || failed) ? '' : '<button class="primary-button" id="confirm-install-ollama">DOWNLOAD &amp; INSTALL</button>';
        if (active) controls = '<button class="text-button danger" id="cancel-install-ollama-progress">CANCEL INSTALL</button>';
        if (failed || cancelled) controls = '<button class="text-button" id="retry-install-ollama">RETRY</button>';
        installBox.innerHTML =
          '<h3>Install the Ollama runtime</h3>' +
          '<p>VORTEX resolves the official Ollama release into its own data directory (no root, no <code>curl | sh</code>), requires its published SHA-256 digest, and serves it on loopback only.</p>' +
          '<ol><li>Operator-confirmed, on-network download.</li><li>Exact release size and mandatory published SHA-256 enforced; malformed archives are rejected.</li><li>Executable and loopback API always verified after install.</li></ol>' +
          '<p>' + esc(line) + '</p>' +
          bar + '<div class="ollama-actions">' + controls + '</div>';
        var confirmBtn = $('confirm-install-ollama');
        if (confirmBtn) confirmBtn.addEventListener('click', function () { installOllama(); });
        var retryBtn = $('retry-install-ollama');
        if (retryBtn) retryBtn.addEventListener('click', function () { installOllama(); });
        var cancelProgressBtn = $('cancel-install-ollama-progress');
        if (cancelProgressBtn) cancelProgressBtn.addEventListener('click', cancelInstall);
      }
    }
  }

  function suggestedRole(item) {
    var phases = item.primary_for || [];
    if (phases.indexOf('plan') !== -1 || phases.indexOf('tooling') !== -1) return 'planner';
    if (phases.indexOf('fast') !== -1) return 'fast';
    if (phases.indexOf('specialist') !== -1) return 'specialist';
    return 'primary';
  }

  function roleSelect(item, selected, includeNone) {
    var choices = [
      ['primary', 'PRIMARY ANALYSIS'], ['planner', 'PLANNING ADVISORY'],
      ['fast', 'FAST CONVERSATION'], ['specialist', 'SPECIALIST'],
    ];
    if (includeNone) choices.push(['none', 'DOWNLOAD ONLY']);
    return '<select class="model-role-select" aria-label="Advisory role for ' + esc(item.name) + '">' + choices.map(function (entry) {
      return '<option value="' + entry[0] + '"' + (entry[0] === selected ? ' selected' : '') + '>' + entry[1] + '</option>';
    }).join('') + '</select>';
  }

  function downloadControls(item) {
    var job = item.download || null;
    if (!job || job.status === 'completed') {
      if (item.installed) {
        var active = item.active_roles || [];
        var activeText = active.length ? 'ACTIVE: ' + active.join(' · ') : 'INSTALLED · NOT ASSIGNED';
        return '<div class="model-meta model-role-state">' + esc(activeText) + '</div><div class="model-controls role-controls">' +
          roleSelect(item, active[0] || suggestedRole(item), false) +
          '<button class="secondary-button" data-activate-model="' + esc(item.installed_name || item.name) + '">USE FOR ROLE</button>' +
          '<button class="text-button" data-remove-model="' + esc(item.installed_name || item.name) + '">REMOVE</button></div>';
      }
      return '<div class="model-controls role-controls">' + roleSelect(item, suggestedRole(item), true) +
        '<button class="primary-button" data-pull-model="' + esc(item.name) + '">DOWNLOAD &amp; USE</button>' +
        (item.approx_size_gb != null ? '<span class="model-size">~' + esc(item.approx_size_gb) + ' GB</span>' : '') + '</div>';
    }
    if (job.status === 'failed') {
      return '<div class="model-meta" style="color:var(--red)">' + esc(failureLabel(job.failure_reason)) + (job.error ? ' · ' + esc(job.error) : '') + '</div>' +
        '<div class="model-controls role-controls">' + roleSelect(item, job.requested_role || suggestedRole(item), true) + '<button class="text-button" data-pull-model="' + esc(item.name) + '">RETRY</button></div>';
    }
    if (job.status === 'cancelled') {
      return '<div class="model-meta">download cancelled</div>' +
        '<div class="model-controls role-controls">' + roleSelect(item, job.requested_role || suggestedRole(item), true) + '<button class="text-button" data-pull-model="' + esc(item.name) + '">RETRY</button></div>';
    }
    var active = job.status === 'preparing' || job.status === 'downloading' || job.status === 'verifying' || job.status === 'cancelling';
    if (!active) {
      return '<div class="model-controls role-controls">' + roleSelect(item, job.requested_role || suggestedRole(item), true) + '<button class="primary-button" data-pull-model="' + esc(item.name) + '">DOWNLOAD &amp; USE</button>' + (item.approx_size_gb != null ? '<span class="model-size">~' + esc(item.approx_size_gb) + ' GB</span>' : '') + '</div>';
    }
    var statusLine = (job.status === 'verifying' ? 'verifying…' : (job.last_status || job.status)) +
      (job.step && job.status === 'verifying' ? ' · ' + job.step : '');
    return '<div class="model-meta">' + esc(statusLine) + '</div>' +
      renderBar(job, false) +
      '<div class="model-controls"><button class="text-button" data-cancel-model="' + esc(item.name) + '">CANCEL</button></div>';
  }

  function renderGrid() {
    var grid = $('model-grid');
    if (!grid) return;
    var catalog = modelsState.catalog || {};
    var items = catalog.items || [];
    var extras = catalog.extras || [];
    if (!items.length && !extras.length) {
      grid.innerHTML = '<div class="empty-inline">Model catalog is unavailable from the sidecar.</div>';
      return;
    }
    var cards = items.map(function (item) {
      var badge = item.installed ? 'badge-green' : (item.recommended ? 'badge-amber' : 'badge-muted');
      var badgeText = item.installed ? 'INSTALLED' : (item.recommended ? 'RECOMMENDED' : 'OPTIONAL');
      var stateCls = item.installed ? 'installed' : ((item.download && item.download.status === 'failed') ? 'failed' : ((item.download && (item.download.status === 'downloading' || item.download.status === 'cancelling')) ? 'downloading' : ''));
      return '<article class="model-card ' + stateCls + '"><span class="badge ' + badge + '">' + badgeText + '</span>' +
        '<h3>' + esc(item.label || item.name) + '</h3>' +
        '<div class="model-meta">' + esc(item.family || '') + ' · ' + esc(item.name) + '</div>' +
        '<p>' + esc(item.description || '') + '</p>' +
        '<div class="model-meta">' + (item.roles || []).map(esc).join(' · ') + '</div>' +
        downloadControls(item) + '</article>';
    });
    var extraCards = extras.map(function (item) {
      var active = item.active_roles || [];
      return '<article class="model-card installed"><span class="badge badge-green">INSTALLED</span>' +
        '<h3>' + esc(item.name) + '</h3>' +
        '<div class="model-meta">outside curated catalog · ' + esc(active.length ? 'ACTIVE: ' + active.join(' · ') : 'NOT ASSIGNED') + '</div>' +
        '<p>' + esc(item.description || 'Installed on this host.') + '</p>' +
        '<div class="model-controls role-controls">' + roleSelect(item, active[0] || 'primary', false) +
        '<button class="secondary-button" data-activate-model="' + esc(item.name) + '">USE FOR ROLE</button>' +
        '<button class="text-button" data-remove-model="' + esc(item.name) + '">REMOVE</button></div></article>';
    });
    grid.innerHTML = cards.join('') + extraCards.join('');

    grid.querySelectorAll('[data-pull-model]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var select = btn.parentElement && btn.parentElement.querySelector('.model-role-select');
        pullModel(btn.dataset.pullModel, select ? select.value : 'none');
      });
    });
    grid.querySelectorAll('[data-activate-model]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var select = btn.parentElement && btn.parentElement.querySelector('.model-role-select');
        activateModel(btn.dataset.activateModel, select ? select.value : 'primary');
      });
    });
    grid.querySelectorAll('[data-cancel-model]').forEach(function (btn) {
      btn.addEventListener('click', function () { cancelDownload(btn.dataset.cancelModel); });
    });
    grid.querySelectorAll('[data-remove-model]').forEach(function (btn) {
      btn.addEventListener('click', function () { removeModel(btn.dataset.removeModel); });
    });
  }

  function renderDownloadsStrip() {
    var strip = $('downloads-strip');
    if (!strip) return;
    var jobs = activeJobs();
    var names = Object.keys(jobs);
    var inst = install();
    var installing = inst.status === 'preparing' || inst.status === 'downloading' || inst.status === 'verifying' || inst.status === 'installing' || inst.status === 'starting' || inst.status === 'cancelling';
    if (!names.length && !installing) { strip.hidden = true; strip.innerHTML = ''; return; }
    strip.hidden = false;
    var parts = [];
    if (installing) {
      var pct = measurable(inst) ? Math.round(Number(inst.percent) || 0) + '%' : '…';
      parts.push('<span class="spinner"></span> installing Ollama ' + pct + (measurable(inst) ? ' · ' + fmtBytes(inst.downloaded_bytes) : '') + ' <button class="text-button danger" data-cancel-install-strip>CANCEL</button>');
    }
    names.forEach(function (name) {
      var job = jobs[name];
      var pct = measurable(job) ? Math.round(Number(job.percent) || 0) + '%' : '…';
      parts.push('<span class="spinner"></span> ' + esc(name) + ' ' + pct + (measurable(job) ? ' · ' + fmtBytes(job.downloaded_bytes) : '') + ' <button class="text-button" data-cancel-strip="' + esc(name) + '">CANCEL</button>');
    });
    strip.innerHTML = parts.join('<span style="color:var(--dim)">·</span>');
    strip.querySelectorAll('[data-cancel-strip]').forEach(function (btn) {
      btn.addEventListener('click', function () { cancelDownload(btn.dataset.cancelStrip); });
    });
    strip.querySelector('[data-cancel-install-strip]')?.addEventListener('click', cancelInstall);
  }

  // Compact local-AI panel rendered inside the Agents view so the operator can
  // install Ollama and download the local model pool without hunting for the
  // Models view. Reuses the same manager routes and the same honest state.
  function renderAgentsLocalAi() {
    var box = $('agents-local-ai');
    if (!box) return;
    var runtime = modelsState.runtime;
    if (!runtime || typeof runtime.installed !== 'boolean') {
      box.innerHTML = '<div class="empty-inline">Ollama status is unavailable from the sidecar.</div>';
      return;
    }
    var installed = runtime.installed;
    var server = runtime.server || {};
    var running = server.state === 'running';
    var apiState = runtime.api_state || 'unknown';
    var serviceReady = apiState === 'healthy';
    var installJob = runtime.install || {};
    var installActive = installJob.status === 'preparing' || installJob.status === 'downloading' || installJob.status === 'verifying' || installJob.status === 'installing' || installJob.status === 'starting' || installJob.status === 'cancelling';

    var rows = [];
    var runtimeAction = '';
    var runtimeBadge = installed ? '<span class="badge badge-green">INSTALLED</span>' : '<span class="badge badge-muted">NOT INSTALLED</span>';
    if (installActive) {
      runtimeAction = '<span class="spinner"></span><span class="form-note" style="margin:0">' + esc(installJob.step || 'Installing…') + '</span><button class="text-button danger" data-local-ai="cancel-install">CANCEL</button>';
    } else if (!installed) {
      runtimeAction = '<button class="primary-button" data-local-ai="install">INSTALL OLLAMA</button>';
    } else if (serviceReady && !server.managed) {
      runtimeAction = '<span class="form-note" style="margin:0">EXTERNAL SERVICE ACTIVE</span>';
    } else if (!running) {
      runtimeAction = server.state === 'starting'
        ? '<button class="primary-button" data-local-ai="start" disabled>STARTING SERVICE…</button>'
        : '<button class="primary-button" data-local-ai="start">START SERVICE</button>';
    } else {
      runtimeAction = '<button class="text-button" data-local-ai="stop">STOP SERVICE</button>';
    }
    rows.push('<div class="dep-row"><div><strong>Ollama — local model runtime</strong><small>runtime · loopback only · ' + esc(apiState) + '</small></div>' + runtimeBadge + '<div class="dep-controls">' + runtimeAction + '</div></div>');

    var items = (modelsState.catalog && modelsState.catalog.items) || [];
    items.forEach(function (item) {
      var badge = item.installed ? '<span class="badge badge-green">INSTALLED</span>' : (item.recommended ? '<span class="badge badge-amber">RECOMMENDED</span>' : '<span class="badge badge-muted">OPTIONAL</span>');
      var controls;
      var job = item.download || null;
      var active = job && (job.status === 'preparing' || job.status === 'downloading' || job.status === 'verifying' || job.status === 'cancelling');
      if (item.installed) {
        var activeRoles = item.active_roles || [];
        controls = '<span class="form-note" style="margin:0">' + esc(activeRoles.length ? 'active: ' + activeRoles.join(' · ') : 'not assigned') + '</span><button class="text-button" data-local-ai-remove="' + esc(item.installed_name || item.name) + '">REMOVE</button>';
      } else if (active) {
        controls = '<span class="spinner"></span><span class="form-note" style="margin:0">' + esc(job.status) + '</span>';
      } else if (!installed || !serviceReady) {
        controls = '<span class="form-note" style="margin:0">install &amp; start Ollama first</span>';
      } else {
        controls = '<button class="primary-button" data-local-ai-pull="' + esc(item.name) + '">DOWNLOAD &amp; USE</button>';
      }
      rows.push('<div class="dep-row"><div><strong>' + esc(item.label || item.name) + '</strong><small>' + esc(item.family || '') + ' · ' + esc(item.name) + (item.approx_size_gb != null ? ' · ~' + esc(item.approx_size_gb) + ' GB' : '') + '</small></div>' + badge + '<div class="dep-controls">' + controls + '</div></div>');
    });

    box.innerHTML = rows.join('');
    box.querySelectorAll('[data-local-ai]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var action = btn.dataset.localAi;
        if (action === 'install') installOllama();
        else if (action === 'cancel-install') cancelInstall();
        else if (action === 'start') startServer();
        else if (action === 'stop') stopServer();
      });
    });
    box.querySelectorAll('[data-local-ai-pull]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var item = ((modelsState.catalog && modelsState.catalog.items) || []).find(function (candidate) { return candidate.name === btn.dataset.localAiPull; });
        pullModel(btn.dataset.localAiPull, item ? suggestedRole(item) : 'primary');
      });
    });
    box.querySelectorAll('[data-local-ai-remove]').forEach(function (btn) {
      btn.addEventListener('click', function () { removeModel(btn.dataset.localAiRemove); });
    });
  }

  function gguf() { return (modelsState.catalog && modelsState.catalog.gguf) || {}; }

  function renderGguf() {
    var box = $('gguf-status');
    var grid = $('gguf-grid');
    var badge = $('gguf-badge');
    if (!box) return;
    var snapshot = gguf();
    var state = snapshot.state || 'unknown';
    if (badge) {
      badge.textContent = state.replace('-', ' ').toUpperCase();
      badge.className = 'badge ' + (state === 'healthy' ? 'badge-green' : (state === 'unavailable' || state === 'disabled' ? 'badge-muted' : 'badge-amber'));
    }
    if (!snapshot || typeof snapshot.state !== 'string') {
      box.innerHTML = '<div class="empty-inline">GGUF status is unavailable from the sidecar.</div>';
      if (grid) grid.innerHTML = '';
      return;
    }
    var engine = snapshot.engine || {};
    var tuning = snapshot.tuning || {};
    var rows = [
      statusRow('STATE', state + (snapshot.reason ? ' · ' + snapshot.reason : ''), stateClass(state, ['healthy', 'ready'])),
      statusRow('ENGINE', (engine.python ? 'llama-cpp-python' : (engine.cli || 'none')) + ' · ' + (engine.detail || engine.state || ''), engine.state === 'ready' || engine.state === 'test-double' ? 'ok' : 'warn'),
      statusRow('TUNING', tuning.profile ? (tuning.profile + ' · ctx ' + tuning.n_ctx + ' · threads ' + tuning.n_threads) : '—', ''),
      statusRow('LOADED', snapshot.loaded || 'none resident (single-slot policy)', ''),
      statusRow('CURATED', ((snapshot.curated_present || []).join(', ') || 'none') + (((snapshot.curated_missing || []).length) ? ' · missing: ' + snapshot.curated_missing.join(', ') : ''), (snapshot.curated_missing || []).length ? 'warn' : 'ok'),
      statusRow('DIRECTORIES', (snapshot.directories || []).join(' · ') || '—', ''),
    ];
    ['primary', 'planner', 'fast', 'specialist'].forEach(function (role) {
      var pref = (snapshot.roles || {})[role];
      if (!pref) return;
      var value = pref.state === 'active'
        ? (pref.resolved || pref.configured) + (pref.family_fallback ? ' · family fallback' : '')
        : (pref.configured || 'not configured') + ' · unavailable (fuzzy router falls back)';
      rows.push(statusRow('ROLE · ' + role.toUpperCase(), value, pref.state === 'active' ? 'ok' : 'warn'));
    });
    box.innerHTML = rows.join('');
    if (!grid) return;
    var files = snapshot.files || [];
    if (!files.length) {
      grid.innerHTML = '<div class="empty-inline">No *.gguf files found. Place Llama-3.2-3B-Instruct-Q4_K_M.gguf plus a Qwen2.5-3B or Qwen3-4B GGUF in ~/linux-vortex-terminal/models.</div>';
      return;
    }
    grid.innerHTML = files.map(function (item) {
      var ram = item.ram || {};
      var fit = ram.fits_8gb === true ? 'FITS 8 GB' : (ram.fits_8gb === false ? 'TIGHT ON 8 GB' : 'RAM UNKNOWN');
      var badgeCls = item.valid ? (ram.fits_8gb === false ? 'badge-amber' : 'badge-green') : 'badge-muted';
      var badgeText = item.valid ? (item.curated ? 'CURATED · ' + fit : 'VALID · ' + fit) : 'INVALID';
      var detail = item.valid
        ? ((item.size_gb != null ? item.size_gb + ' GB' : '') + ' · ' + (item.family || '') + ' ' + (item.quant || '') + ' · ~' + (ram.resident_mb != null ? ram.resident_mb + ' MB resident' : 'resident unknown'))
        : (item.reason || 'failed validation');
      return '<article class="model-card ' + (item.valid ? 'installed' : 'failed') + '"><span class="badge ' + badgeCls + '">' + badgeText + '</span>' +
        '<h3>' + esc(item.name) + '</h3>' +
        '<div class="model-meta">' + esc(detail) + '</div>' +
        '<div class="model-meta">' + esc(item.path || '') + '</div>' +
        (item.valid
          ? '<div class="model-controls role-controls">' + roleSelect(item, 'primary', false) +
            '<button class="secondary-button" data-activate-gguf="' + esc(item.name) + '">USE FOR ROLE</button></div>'
          : '') +
        '</article>';
    }).join('');
    grid.querySelectorAll('[data-activate-gguf]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var select = btn.parentElement && btn.parentElement.querySelector('.model-role-select');
        activateGguf(btn.dataset.activateGguf, select ? select.value : 'primary');
      });
    });
  }

  async function activateGguf(name, role) {
    name = String(name || '').trim();
    role = String(role || '').trim();
    if (!name || !role || modelsState.busy['gguf:' + name]) return;
    setBusy('gguf:' + name, true);
    try {
      var data = await api('/api/models/gguf/activate', { method: 'POST', body: { file: name, role: role } });
      var preference = data.preference || {};
      toast((preference.model || name) + ' is now active for ' + (preference.role || role) + ' on-device advisory work.');
      await loadModels();
    } catch (e) {
      toast(e.message, true);
    } finally {
      setBusy('gguf:' + name, false);
    }
  }

  async function importLocalModels(files) {
    var getLocalFilePath = window.vortexApi && window.vortexApi.localFilePath;
    if (typeof getLocalFilePath !== 'function') {
      toast('Local model selection is available in the VORTEX desktop application.', true);
      return;
    }
    var paths = Array.prototype.map.call(files || [], function (file) { return getLocalFilePath(file); }).filter(Boolean);
    if (!paths.length) {
      toast('Select at least one local GGUF file.', true);
      return;
    }
    if (modelsState.busy.import) return;
    setBusy('import', true);
    try {
      var data = await api('/api/models/gguf/import', { method: 'POST', body: { paths: paths } });
      var imported = data.import || {};
      toast(imported.message || 'Local model source added.');
      await loadModels();
    } catch (e) {
      toast(e.message || 'Unable to inspect the selected model.', true);
    } finally {
      setBusy('import', false);
    }
  }

  function renderModels() {
    renderStatus();
    renderGguf();
    renderGrid();
    renderDownloadsStrip();
    renderAgentsLocalAi();
  }

  async function loadModels() {
    try {
      var data = await api('/api/ollama');
      modelsState.runtime = data.ollama || {};
      modelsState.catalog = data.models || {};
      renderModels();
      schedulePoll();
    } catch (e) {
      modelsState.runtime = null;
      modelsState.catalog = null;
      renderModels();
      toast(e.message, true);
    }
  }

  function schedulePoll() {
    clearTimeout(modelsState.pollTimer);
    if (pollable()) {
      modelsState.pollTimer = setTimeout(loadModels, 1400);
    }
  }

  function setBusy(key, busy) {
    if (busy) modelsState.busy[key] = true; else delete modelsState.busy[key];
  }

  async function installOllama() {
    if (modelsState.busy.install) return;
    setBusy('install', true);
    toast('Preparing the operator-confirmed Ollama install…');
    try {
      var context = (typeof state === 'object' && state) ? state : {};
      var result = await api('/api/ollama/install', {
        method: 'POST',
        body: { confirm: true, cwd: context.doctor && context.doctor.cwd, conversation_id: context.conversationId },
      });
      if (result.planned) {
        if (typeof window.showDependencyPlan !== 'function' || !window.showDependencyPlan(result)) {
          throw new Error('Ollama needs the reviewed zstd prerequisite, but its installation plan could not be displayed.');
        }
        toast('Ollama needs zstd first. Approve the prepared secure install, then retry Ollama.');
        return;
      }
      await loadModels();
    } catch (e) {
      toast(e.message, true);
      await loadModels();
    } finally {
      setBusy('install', false);
    }
  }

  async function cancelInstall() {
    try {
      await api('/api/ollama/install/cancel', { method: 'POST', body: {} });
      toast('Cancelling the Ollama install…');
      await loadModels();
    } catch (e) { toast(e.message, true); }
  }

  async function startServer() {
    if (modelsState.busy.server) return;
    setBusy('server', true);
    try {
      var result = await api('/api/ollama/server/start', { method: 'POST', body: {} });
      var server = result.server || {};
      if (server.state !== 'running') throw new Error((server.logs || []).slice(-1)[0] || 'Ollama did not remain running.');
      toast('Ollama service is running on 127.0.0.1:11434.');
      await loadModels();
    } catch (e) { toast(e.message || 'Unable to start Ollama service.', true); await loadModels(); }
    finally { setBusy('server', false); }
  }

  async function stopServer() {
    try {
      await api('/api/ollama/server/stop', { method: 'POST', body: {} });
      toast('Ollama service stopped.');
      await loadModels();
    } catch (e) { toast(e.message, true); }
  }

  async function pullModel(name, role) {
    name = String(name || '').trim();
    role = String(role || 'none');
    if (!name) { toast('Enter a model name such as phi4-mini:3.8b first.', true); return; }
    if (modelsState.busy['pull:' + name]) return;
    setBusy('pull:' + name, true);
    toast('Downloading ' + name + (role === 'none' ? '…' : ' for ' + role + ' advisory work…'));
    try {
      await api('/api/ollama/models/pull', { method: 'POST', body: { name: name, role: role } });
      await loadModels();
    } catch (e) {
      toast(e.message, true);
      await loadModels();
    } finally {
      setBusy('pull:' + name, false);
    }
  }

  async function activateModel(name, role) {
    name = String(name || '').trim();
    role = String(role || '').trim();
    if (!name || !role || modelsState.busy['activate:' + name]) return;
    setBusy('activate:' + name, true);
    try {
      var data = await api('/api/ollama/models/activate', { method: 'POST', body: { name: name, role: role } });
      var preference = data.preference || {};
      toast((preference.model || name) + ' is now active for ' + (preference.role || role) + ' advisory work.');
      await loadModels();
    } catch (e) {
      toast(e.message, true);
    } finally {
      setBusy('activate:' + name, false);
    }
  }

  async function cancelDownload(name) {
    name = String(name || '').trim();
    if (!name) return;
    try {
      await api('/api/ollama/models/cancel', { method: 'POST', body: { name: name } });
      toast('Cancelling ' + name + '…');
      await loadModels();
    } catch (e) { toast(e.message, true); }
  }

  async function removeModel(name) {
    name = String(name || '').trim();
    if (!name) return;
    if (modelsState.busy['remove:' + name]) return;
    setBusy('remove:' + name, true);
    try {
      await api('/api/ollama/models/remove', { method: 'POST', body: { name: name } });
      toast(name + ' removed.');
      await loadModels();
    } catch (e) {
      toast(e.message, true);
    } finally {
      setBusy('remove:' + name, false);
    }
  }

  function bindControls() {
    var refresh = $('refresh-models');
    if (refresh && !refresh._bound) {
      refresh._bound = true;
      refresh.addEventListener('click', function () { loadModels(); });
    }
    var pull = $('pull-custom-model');
    if (pull && !pull._bound) {
      pull._bound = true;
      pull.addEventListener('click', function () {
        pullModel(($('model-name-input') || {}).value || '', (($('model-role-input') || {}).value || 'primary'));
      });
    }
    var input = $('model-name-input');
    if (input && !input._bound) {
      input._bound = true;
      input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') pullModel(input.value, (($('model-role-input') || {}).value || 'primary'));
      });
    }
    [['add-local-model', 'local-model-file'], ['add-model-folder', 'local-model-folder']].forEach(function (pair) {
      var button = $(pair[0]);
      var chooser = $(pair[1]);
      if (button && chooser && !button._bound) {
        button._bound = true;
        button.addEventListener('click', function () { chooser.click(); });
        chooser.addEventListener('change', function () {
          importLocalModels(chooser.files);
          chooser.value = '';
        });
      }
    });
  }

  window.loadModels = loadModels;
  window.renderModels = renderModels;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      bindControls();
      loadModels();
    });
  } else {
    bindControls();
    loadModels();
  }
})();
