/* Conversation, task, agent, memory, health, and policy UI on the existing renderer. */
(function () {
  const origSetView = window.setView;
  const origRenderReports = (typeof renderReports === 'function') ? renderReports : null;
  const origRenderAnalysis = (typeof renderAnalysis === 'function') ? renderAnalysis : null;
  const origRenderPlan = (typeof renderPlan === 'function') ? renderPlan : null;

  state.conversationId = null;
  state.settings = { profile: 'safe', privacy_mode: 'local', developer_mode: false, offline: false, lab_mode: false };

  function renderList(id, items, empty, mapper) {
    const el = $(id);
    if (!el) return;
    el.innerHTML = items.length ? items.map(mapper).join('') : `<div class="empty-inline">${empty}</div>`;
  }

  function renderChat(messages) {
    const el = $('chat-thread');
    if (!el) return;
    if (!messages || !messages.length) {
      el.innerHTML = '<div class="chat-empty">Ask VORTEX to inspect this host. You will see the plan, the real terminal evidence, and a natural-language explanation.</div>';
      return;
    }
    el.innerHTML = messages.map(m => {
      const report = m.meta?.report_id;
      const links = report ? `<p>${['pdf','html','md','json'].map(fmt => `<a class="report-dl" href="/api/reports/${encodeURIComponent(report)}/download?format=${fmt}">${fmt.toUpperCase()}</a>`).join(' ')}</p>` : '';
      const edit = m.role === 'user' ? `<button class="text-button" data-edit-message="${esc(m.id)}">EDIT &amp; BRANCH</button>` : '';
      return `<article class="chat-msg ${esc(m.role)}"><span class="role">${esc((m.role || '').toUpperCase())}</span><p>${esc(m.content)}</p>${links}${edit}</article>`;
    }).join('');
    el.scrollTop = el.scrollHeight;
    el.querySelectorAll('[data-edit-message]').forEach(btn => btn.addEventListener('click', async () => {
      const content = prompt('Edit this instruction (creates a conversation branch)');
      if (!content || !state.conversationId) return;
      try {
        const data = await api(`/api/conversations/${encodeURIComponent(state.conversationId)}/messages/${encodeURIComponent(btn.dataset.editMessage)}/edit`, { method: 'POST', body: { content } });
        state.conversationId = data.conversation.id;
        renderChat(data.messages || []);
        toast('Branched conversation. Original history is preserved.');
        await window.makePlan(content);
      } catch (e) { toast(e.message, true); }
    }));
  }

  function renderTaskContext(task, guardian, council, operation, findings) {
    const el = $('task-context');
    if (!el) return;
    const rows = [
      ['TASK', task?.id || '—'],
      ['STATE', task?.state || 'idle'],
      ['PLAN', task?.plan_id ? String(task.plan_id).slice(0, 12) + '…' : '—'],
      ['AGENTS', (council?.selected || []).join(', ') || 'none consulted'],
      ['RISK', guardian?.risk || task?.risk || '—'],
      ['GUARDIAN', guardian?.decision || '—'],
      ['EXECUTION', operation?.status || task?.state || 'idle'],
      ['FINDINGS', findings && findings.length ? String(findings.length) : 'none'],
    ];
    el.innerHTML = rows.map(([a, b]) => `<div class="context-row"><label>${esc(a)}</label><span>${esc(b)}</span></div>`).join('');
  }

  function renderLiveOutput(operation) {
    const el = $('live-output');
    if (!el) return;
    const commands = operation?.commands || [];
    if (!commands.length) {
      el.textContent = 'No command output yet. Approved commands stream observed stdout here.';
      return;
    }
    el.textContent = commands.map(c => `$ ${c.display || ''}\n${c.stdout || ''}${c.stderr ? '\n[stderr]\n' + c.stderr : ''}\n[exit ${c.exit_code} ${c.status}]`).join('\n\n');
  }

  window.renderLiveOutput = renderLiveOutput;

  async function refreshChat() {
    if (!state.conversationId) return;
    try {
      const data = await api(`/api/conversations/${encodeURIComponent(state.conversationId)}`);
      renderChat(data.messages || []);
    } catch (_) { /* conversation may not exist yet */ }
  }

  async function loadSettings() {
    try {
      const data = await api('/api/settings');
      state.settings = data.settings || state.settings;
      if ($('policy-setting')) $('policy-setting').value = state.settings.profile || 'safe';
      if ($('privacy-setting')) $('privacy-setting').value = state.settings.privacy_mode || 'local';
      if ($('dev-setting')) $('dev-setting').value = state.settings.developer_mode ? 'on' : 'off';
      if ($('offline-setting')) $('offline-setting').value = state.settings.offline ? 'on' : 'off';
      if ($('lab-setting')) $('lab-setting').value = state.settings.lab_mode ? 'on' : 'off';
      const offline = !!state.settings.offline;
      if ($('mode-label')) $('mode-label').textContent = offline ? 'OFFLINE' : (state.settings.lab_mode ? 'LAB MODE' : 'LOCAL-FIRST');
      if ($('privacy-chip')) $('privacy-chip').textContent = (state.settings.privacy_mode || 'local').toUpperCase() + ' CORE';
      if (offline && $('backend-label')) $('backend-label').textContent = 'OFFLINE MODE';
    } catch (e) { /* settings are optional on first boot */ }
  }

  async function loadSetup() {
    try {
      const data = await api('/api/setup');
      const setup = data.setup || {};
      if (setup.first_run_complete) return;
      const host = $('first-run');
      const steps = $('setup-steps');
      if (!host || !steps) return;
      host.hidden = false;
      steps.innerHTML = (setup.steps || []).map(step => {
        const badge = step.ok ? 'badge-green' : step.required ? 'badge-red' : 'badge-muted';
        const label = step.ok ? 'OK' : step.required ? 'FAILED' : 'OPTIONAL';
        return `<div class="setup-step"><div><strong>${esc(step.title)}</strong><small>${esc(step.detail || '')}</small></div><span class="badge ${badge}">${label}</span></div>`;
      }).join('');
      const go = $('complete-setup');
      if (go) go.disabled = !setup.ready;
    } catch (e) { toast(e.message, true); }
  }

  async function loadHealth() {
    try {
      const data = await api('/api/system/health');
      const components = data.health?.components || {};
      $('health-grid').innerHTML = Object.entries(components).map(([name, item]) => {
        const stateName = item.state || 'unknown';
        const badge = stateName === 'healthy' ? 'badge-green' : stateName === 'unavailable' || stateName === 'empty' ? 'badge-muted' : 'badge-amber';
        const detail = item.available || item.detected || item.used_percent || item.runtime || item.version || '';
        return `<article class="tool-card ${esc(stateName)}"><span class="badge ${badge}">${esc(String(stateName).toUpperCase())}</span><h3>${esc(name.replace(/_/g, ' '))}</h3><p>${esc(detail)}</p></article>`;
      }).join('');
      if (data.health?.offline && $('backend-label')) $('backend-label').textContent = 'OFFLINE MODE';
    } catch (e) { toast(e.message, true); }
  }

  async function loadAgents() {
    try {
      const data = await api('/api/agents');
      $('agent-grid').innerHTML = (data.agents || []).map(agent => {
        const healthy = !!agent.health?.healthy;
        return `<article class="tool-card ${healthy ? 'installed' : 'absent'}"><span class="badge ${healthy ? 'badge-green' : 'badge-muted'}">${esc((agent.status || 'missing').toUpperCase())}</span><h3>${esc(agent.name)}</h3><div class="tool-family">${esc(agent.trust_level)} · ${esc(agent.execution_mode)}</div><p>${esc(agent.health?.message || agent.notes || '')}<br><span class="tool-path">${esc(agent.source || 'no verified repository')}</span><br>${esc(agent.version || 'Version unavailable')}</p>${healthy ? '' : `<button class="text-button" data-agent-install="${esc(agent.id)}">INSTALL PROPOSAL</button>`}</article>`;
      }).join('');
      document.querySelectorAll('[data-agent-install]').forEach(btn => btn.addEventListener('click', async () => {
        try {
          const data = await api(`/api/agents/${encodeURIComponent(btn.dataset.agentInstall)}/install`);
          toast(data.install?.message || 'Install remains operator-controlled.');
        } catch (e) { toast(e.message, true); }
      }));
    } catch (e) { toast(e.message, true); }
  }

  async function openConversation(id) {
    const data = await api(`/api/conversations/${encodeURIComponent(id)}`);
    state.conversationId = id;
    renderChat(data.messages || []);
    setView('overview');
  }

  async function loadConversations() {
    try {
      const q = $('conversation-search')?.value?.trim();
      const data = await api('/api/conversations' + (q ? `?q=${encodeURIComponent(q)}` : ''));
      renderList('conversation-list', data.conversations || [], 'No conversations yet.', c => `<article class="engagement-card"><header><div><h3 data-open-conversation="${esc(c.id)}">${esc(c.title)}</h3><p>v${esc(c.version)} · ${esc(c.status)}</p></div><span class="badge ${c.status === 'active' ? 'badge-green' : 'badge-muted'}">${esc(c.status.toUpperCase())}</span></header><div class="engagement-details"><span>ID ${esc(c.id.slice(0,12))}…</span><span>${esc(fmtDate(c.updated_at))}</span><a class="report-dl" href="/api/conversations/${encodeURIComponent(c.id)}/export">EXPORT</a> <button class="text-button" data-rename-conversation="${esc(c.id)}">RENAME</button> <button class="text-button" data-archive-conversation="${esc(c.id)}">ARCHIVE</button> <button class="text-button" data-delete-conversation="${esc(c.id)}">DELETE</button></div></article>`);
      document.querySelectorAll('[data-open-conversation]').forEach(el => el.addEventListener('click', () => openConversation(el.dataset.openConversation).catch(err => toast(err.message, true))));
      document.querySelectorAll('[data-rename-conversation]').forEach(btn => btn.addEventListener('click', async (ev) => {
        ev.stopPropagation();
        const title = prompt('Rename conversation');
        if (!title) return;
        try { await api(`/api/conversations/${encodeURIComponent(btn.dataset.renameConversation)}/rename`, { method: 'POST', body: { title } }); loadConversations(); }
        catch (e) { toast(e.message, true); }
      }));
      document.querySelectorAll('[data-archive-conversation]').forEach(btn => btn.addEventListener('click', async (ev) => {
        ev.stopPropagation();
        try { await api(`/api/conversations/${encodeURIComponent(btn.dataset.archiveConversation)}/archive`, { method: 'POST', body: {} }); loadConversations(); }
        catch (e) { toast(e.message, true); }
      }));
      document.querySelectorAll('[data-delete-conversation]').forEach(btn => btn.addEventListener('click', async (ev) => {
        ev.stopPropagation();
        try { await api(`/api/conversations/${encodeURIComponent(btn.dataset.deleteConversation)}/delete`, { method: 'POST', body: {} }); loadConversations(); }
        catch (e) { toast(e.message, true); }
      }));
    } catch (e) { toast(e.message, true); }
  }

  async function loadTasks() {
    try {
      const data = await api('/api/tasks');
      const interrupted = data.interrupted || [];
      $('interrupted-tasks').textContent = interrupted.length ? `Resume available: ${interrupted.map(t => t.id).join(', ')}` : 'No interrupted tasks.';
      renderList('task-list', data.tasks || [], 'No tasks recorded.', t => `<article class="activity-item"><span class="activity-icon ${t.state === 'COMPLETED' ? '' : t.state === 'FAILED' ? 'failed' : 'running'}"></span><div><div class="activity-title">${esc(t.id)} · ${esc(t.state)}</div><div class="activity-command">${esc(t.request)}</div></div><div class="activity-meta"><div>${esc(t.risk || '—')}</div><div>${esc(fmtDate(t.updated_at))}</div><div><button class="text-button" data-task-resume="${esc(t.id)}">RESUME</button> <button class="text-button" data-task-delete="${esc(t.id)}">DELETE</button></div></div></article>`);
      document.querySelectorAll('[data-task-resume]').forEach(btn => btn.addEventListener('click', async () => {
        try { await api(`/api/tasks/${encodeURIComponent(btn.dataset.taskResume)}/resume`, { method: 'POST', body: { cwd: state.doctor?.cwd } }); toast('Task resumed with a fresh plan.'); loadTasks(); }
        catch (e) { toast(e.message, true); }
      }));
      document.querySelectorAll('[data-task-delete]').forEach(btn => btn.addEventListener('click', async () => {
        try { await api(`/api/tasks/${encodeURIComponent(btn.dataset.taskDelete)}/delete`, { method: 'POST', body: {} }); loadTasks(); }
        catch (e) { toast(e.message, true); }
      }));
    } catch (e) { toast(e.message, true); }
  }

  async function loadMemory() {
    try {
      const data = await api('/api/memory');
      renderList('memory-list', data.memories || [], 'Memory is empty until a task completes.', m => `<article class="activity-item"><span class="activity-icon"></span><div><div class="activity-title">${esc(m.kind)} · ${esc(m.title)}</div><div class="activity-command">${esc(m.body)}</div></div><div class="activity-meta">${esc(fmtDate(m.created_at))}</div></article>`);
    } catch (e) { toast(e.message, true); }
  }

  async function loadLearning() {
    try {
      const data = await api('/api/learning');
      renderList('procedure-list', data.procedures || [], 'No validated procedures yet.', p => `<article class="activity-item"><span class="activity-icon"></span><div><div class="activity-title">${esc(p.name)}</div><div class="activity-command">${(p.steps || []).length} observed step(s) · used ${esc(p.uses)}</div></div></article>`);
      renderList('experience-list', data.experiences || [], 'No experiences recorded.', e => `<article class="activity-item"><span class="activity-icon ${e.outcome === 'succeeded' ? '' : 'failed'}"></span><div><div class="activity-title">${esc(e.kind)} · ${esc(e.outcome)}</div><div class="activity-command">${esc(e.task_id || '')} ${e.validated ? 'validated' : 'unvalidated'}</div></div></article>`);
    } catch (e) { toast(e.message, true); }
  }

  window.renderReports = function () {
    const el = $('report-grid');
    if (!el) return;
    const reports = state.reports;
    if (reports && reports.length) {
      el.innerHTML = reports.map(r => `<article class="report-card"><div class="panel-kicker">${esc((r.kind || 'task').toUpperCase())}</div><h3>${esc(r.title)}</h3><p>${esc(fmtDate(r.created_at))}<br>${esc(r.task_id || r.operation_id || '')}</p><p>${(r.formats || []).map(fmt => `<a class="report-dl" href="/api/reports/${encodeURIComponent(r.id)}/download?format=${encodeURIComponent(fmt)}">${esc(fmt.toUpperCase())}</a>`).join(' ')}</p></article>`).join('');
      return;
    }
    if (origRenderReports) origRenderReports();
  };

  async function loadReportsWorkspace() {
    try {
      const data = await api('/api/reports');
      state.reports = data.reports || [];
      window.renderReports();
    } catch (e) {
      await loadHistory();
      if (origRenderReports) origRenderReports();
    }
  }

  window.setView = function (view) {
    origSetView(view);
    if (view === 'conversations') loadConversations();
    if (view === 'tasks') loadTasks();
    if (view === 'agents') loadAgents();
    if (view === 'memory') loadMemory();
    if (view === 'learning') loadLearning();
    if (view === 'system') loadHealth();
    if (view === 'reports') loadReportsWorkspace();
    if (view === 'settings') loadSettings();
  };

  if (origRenderAnalysis) {
    window.renderAnalysis = function (op) {
      origRenderAnalysis(op);
      renderLiveOutput(op);
      refreshChat();
    };
  }

  window.makePlan = async function (request) {
    if (!request || !request.trim()) return;
    setView('overview');
    $('plan-button').disabled = true;
    $('plan-button').textContent = 'INSPECTING…';
    try {
      const payload = { request, cwd: state.doctor?.cwd || undefined, conversation_id: state.conversationId, offline: !!state.settings.offline };
      if (state.activeEngagementId) payload.engagement_id = state.activeEngagementId;
      const data = await api('/api/workspace/turn', { method: 'POST', body: payload });
      state.conversationId = data.conversation?.id || state.conversationId;
      state.task = data.task;
      state.plan = data.plan;
      let findings = [];
      try { findings = (await api('/api/findings')).findings || []; } catch (_) { findings = []; }
      if (data.task?.id) findings = findings.filter(item => item.task_id === data.task.id);
      renderTaskContext(data.task, data.guardian, data.council, data.operation, findings);
      if (data.plan && origRenderPlan) origRenderPlan(data.plan);
      else if (data.plan) renderPlan(data.plan);
      await refreshChat();
      if (state.settings.developer_mode && data.guardian) {
        const extra = document.createElement('div');
        extra.className = 'worker-row';
        extra.textContent = `GUARDIAN · ${data.guardian.decision} · ${data.guardian.risk} · task ${data.task?.id || ''} · critic ${data.council?.critic?.verdict || ''}`;
        $('plan-content')?.appendChild(extra);
      }
      if (data.auto_executed && data.operation?.id) {
        toast('Guardian auto-authorized a low-risk command. Streaming real output.');
        await watchOperation(data.operation.id);
        await refreshChat();
      } else {
        toast(data.explanation || statusLabel(data.plan?.status), data.plan?.status === 'rejected');
      }
    } catch (e) {
      toast(e.message, true);
    } finally {
      $('plan-button').disabled = false;
      $('plan-button').innerHTML = '<span class="spark">✦</span> SEND';
    }
  };

  document.addEventListener('DOMContentLoaded', () => {
    loadSettings();
    loadSetup();
    api('/api/health').then(data => {
      const items = data.interrupted_tasks || [];
      const banner = $('resume-banner');
      if (banner && items.length) {
        banner.hidden = false;
        banner.textContent = `Resume available: ${items.map(t => t.id).join(', ')}`;
        banner.onclick = () => setView('tasks');
      }
    }).catch(() => {});
    $('refresh-agents')?.addEventListener('click', loadAgents);
    $('refresh-health')?.addEventListener('click', loadHealth);
    $('new-conversation')?.addEventListener('click', async () => {
      try {
        const data = await api('/api/conversations', { method: 'POST', body: { title: 'New conversation' } });
        state.conversationId = data.conversation.id;
        renderChat([]);
        toast('Conversation created.');
        loadConversations();
        setView('overview');
      } catch (e) { toast(e.message, true); }
    });
    $('stop-all')?.addEventListener('click', async () => {
      try {
        const data = await api('/api/control/stop-all', { method: 'POST', body: {} });
        toast(`STOP ALL · ops ${data.stop?.operations_cancelled || 0} · sessions ${data.stop?.sessions_killed || 0}`);
      } catch (e) { toast(e.message, true); }
    });
    $('complete-setup')?.addEventListener('click', async () => {
      try {
        await api('/api/setup/complete', { method: 'POST', body: {} });
        $('first-run').hidden = true;
        toast('First-run checks recorded. Optional components remain unavailable until installed.');
      } catch (e) { toast(e.message, true); }
    });
    const persist = async (body) => {
      try { const data = await api('/api/settings', { method: 'POST', body }); state.settings = data.settings; toast('Settings saved.'); loadSettings(); }
      catch (e) { toast(e.message, true); }
    };
    $('policy-setting')?.addEventListener('change', e => persist({ profile: e.target.value, auto_low_risk: e.target.value !== 'safe' }));
    $('privacy-setting')?.addEventListener('change', e => persist({ privacy_mode: e.target.value }));
    $('dev-setting')?.addEventListener('change', e => persist({ developer_mode: e.target.value === 'on' }));
    $('offline-setting')?.addEventListener('change', e => persist({ offline: e.target.value === 'on' }));
    $('lab-setting')?.addEventListener('change', e => persist({ lab_mode: e.target.value === 'on' }));
    $('conversation-search')?.addEventListener('input', () => loadConversations());
    $('reject-plan')?.addEventListener('click', async () => {
      if (!state.plan?.id) return toast('No plan to reject.', true);
      try {
        const data = await api(`/api/plans/${encodeURIComponent(state.plan.id)}/reject`, { method: 'POST', body: { task_id: state.task?.id } });
        state.plan = { ...state.plan, status: 'rejected' };
        if (origRenderPlan) origRenderPlan(state.plan);
        if (data.task) state.task = data.task;
        renderTaskContext(state.task, null, null, null);
        toast('Plan rejected. Nothing further will execute.');
      } catch (e) { toast(e.message, true); }
    });
    $('pause-task')?.addEventListener('click', async () => {
      const id = state.task?.id;
      if (!id) return toast('No running task.', true);
      try {
        const data = await api(`/api/tasks/${encodeURIComponent(id)}/pause`, { method: 'POST', body: {} });
        state.task = data.task;
        renderTaskContext(state.task, null, null, null);
        toast('Task paused. STOP ALL remains available.');
      } catch (e) { toast(e.message, true); }
    });
    $('save-secrets')?.addEventListener('click', async () => {
      try {
        const slots = [['ollama_token', 'secret-ollama'], ['openai_api_key', 'secret-openai'], ['anthropic_api_key', 'secret-anthropic']];
        for (const [slot, id] of slots) {
          const value = $(id)?.value;
          if (value) await api('/api/secrets', { method: 'POST', body: { slot, value } });
        }
        toast('Secret slots saved. Values are never returned by the API.');
        ['secret-ollama', 'secret-openai', 'secret-anthropic'].forEach(id => { if ($(id)) $(id).value = ''; });
      } catch (e) { toast(e.message, true); }
    });
    api('/api/models').then(data => {
      const local = data.model?.local || {};
      if ($('model-badge')) {
        $('model-badge').textContent = (local.state || 'DISABLED').toUpperCase();
        $('model-badge').className = `badge ${local.state === 'healthy' ? 'badge-green' : 'badge-muted'}`;
      }
    }).catch(() => {});
  });
})();
