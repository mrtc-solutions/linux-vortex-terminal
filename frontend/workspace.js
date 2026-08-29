/* Conversation, task, agent, memory, health, and policy UI on the existing renderer. */
(function () {
  const origSetView = window.setView;
  const origRenderReports = (typeof renderReports === 'function') ? renderReports : null;
  const origRenderAnalysis = (typeof renderAnalysis === 'function') ? renderAnalysis : null;
  const origRenderPlan = (typeof renderPlan === 'function') ? renderPlan : null;

  // One continuous conversation per operator unless they explicitly start a
  // new one: the active thread survives page reloads via localStorage.
  function persistConversationId(id) { try { if (id) localStorage.setItem('vortex.conversationId', id); else localStorage.removeItem('vortex.conversationId'); } catch (_) { /* storage unavailable; continuity degrades to per-session */ } }
  function restoreConversationId() { try { const saved = localStorage.getItem('vortex.conversationId'); if (saved && !state.conversationId) state.conversationId = saved; } catch (_) {} }
  state.conversationId = null;
  restoreConversationId();
  state.settings = { profile: 'safe', privacy_mode: 'local', developer_mode: false, offline: false, lab_mode: false };
  let planning = false;

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
    el.querySelectorAll('[data-edit-message]').forEach(btn => btn.addEventListener('click', () => {
      // Inline editor: native prompt() is silently blocked in sandboxed
      // iframe previews and would read as a dead button.
      const msg = btn.closest('.chat-msg');
      const contentEl = msg ? msg.querySelector('p') : null;
      if (!contentEl || msg.querySelector('.edit-input')) return;
      const original = contentEl.textContent;
      contentEl.innerHTML = `<textarea class="edit-input" aria-label="Edit instruction" style="width:100%;min-height:64px;background:#0c0c10;border:1px solid var(--cyan);color:var(--text);padding:8px;font:12px/1.5 inherit;resize:vertical">${esc(original)}</textarea><div style="margin-top:6px"><button class="text-button" data-edit-save>SAVE &amp; BRANCH</button> <button class="text-button" data-edit-cancel>CANCEL</button></div>`;
      const area = contentEl.querySelector('.edit-input');
      area.focus();
      const restore = () => { contentEl.textContent = original; };
      const save = async () => {
        const content = area.value.trim();
        if (!content || !state.conversationId) return;
        try {
          const data = await api(`/api/conversations/${encodeURIComponent(state.conversationId)}/messages/${encodeURIComponent(btn.dataset.editMessage)}/edit`, { method: 'POST', body: { content } });
          state.conversationId = data.conversation.id;
          persistConversationId(state.conversationId);
          renderChat(data.messages || []);
          toast('Branched conversation. Original history is preserved.');
          await window.makePlan(content);
        } catch (e) { toast(e.message, true); restore(); }
      };
      contentEl.querySelector('[data-edit-save]').addEventListener('click', save);
      contentEl.querySelector('[data-edit-cancel]').addEventListener('click', restore);
      area.addEventListener('keydown', (e2) => {
        if (e2.key === 'Enter' && (e2.ctrlKey || e2.metaKey)) { e2.preventDefault(); save(); }
        if (e2.key === 'Escape') { e2.preventDefault(); restore(); }
      });
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
      ['REWARD', task?.result?.episode?.evaluation?.reward === 0 || task?.result?.episode?.evaluation?.reward ? String(task.result.episode.evaluation.reward) : '—'],
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
      if ($('host-tools-setting')) $('host-tools-setting').value = state.settings.host_tool_access ? 'on' : 'off';
      const offline = !!state.settings.offline;
      if ($('mode-label')) $('mode-label').textContent = offline ? 'OFFLINE' : (state.settings.lab_mode ? 'LAB MODE' : 'LOCAL-FIRST');
      if ($('privacy-chip')) $('privacy-chip').textContent = (state.settings.privacy_mode || 'local').toUpperCase() + ' CORE';
      if (offline && $('backend-label')) $('backend-label').textContent = 'OFFLINE MODE';
    } catch (e) { /* settings are optional on first boot */ }
  }

  function hideFirstRun() {
    const host = $('first-run');
    if (!host) return;
    if (window.VortexWindows?.closeSurface) {
      window.VortexWindows.closeSurface(host);
      return;
    }
    host.hidden = true;
  }

  async function loadSetup() {
    try {
      const data = await api('/api/setup');
      const setup = data.setup || {};
      if (setup.first_run_complete) return;
      const host = $('first-run');
      const steps = $('setup-steps');
      if (!host || !steps) return;
      steps.innerHTML = (setup.steps || []).map(step => {
        const badge = step.ok ? 'badge-green' : step.required ? 'badge-red' : 'badge-muted';
        const label = step.ok ? 'OK' : step.required ? 'FAILED' : 'OPTIONAL';
        return `<div class="setup-step"><div><strong>${esc(step.title)}</strong><small>${esc(step.detail || '')}</small></div><span class="badge ${badge}">${label}</span></div>`;
      }).join('');
      const go = $('complete-setup');
      if (go) go.disabled = !setup.ready;
      // Never let the first-run surface cover the request input while the host
      // is not ready to complete setup. It remains reachable from the Dependencies
      // button and can always be dismissed with SKIP.
      if (!setup.ready) return;
      if (window.VortexWindows?.showSurface) window.VortexWindows.showSurface(host);
      else host.hidden = false;
    } catch (e) { toast(e.message, true); }
  }

  async function loadHealth(refresh = false) {
    try {
      const data = await api(`/api/system/health${refresh ? '?fresh=1' : ''}`);
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

  async function loadAgents(refresh = false) {
    try {
      const data = await api(`/api/agents${refresh ? '?fresh=1' : ''}`);
      $('agent-grid').innerHTML = (data.agents || []).map(agent => {
        const healthy = !!agent.health?.healthy;
        return `<article class="tool-card ${healthy ? 'installed' : 'absent'}"><span class="badge ${healthy ? 'badge-green' : 'badge-muted'}">${esc((agent.status || 'missing').toUpperCase())}</span><h3>${esc(agent.name)}</h3><div class="tool-family">${esc(agent.trust_level)} · ${esc(agent.execution_mode)}</div><p>${esc(agent.health?.message || agent.notes || '')}<br><span class="tool-path">${esc(agent.source || 'no verified repository')}</span><br>${esc(agent.version || 'Version unavailable')}</p>${healthy ? '' : `<button class="text-button" data-agent-install="${esc(agent.id)}">INSTALL PROPOSAL</button>`}</article>`;
      }).join('');
      document.querySelectorAll('[data-agent-install]').forEach(btn => btn.addEventListener('click', async () => {
        const original = btn.textContent;
        btn.disabled = true;
        btn.textContent = 'OPENING…';
        try {
          if (typeof window.openDependency === 'function') {
            await window.openDependency(`agent:${btn.dataset.agentInstall}`);
          } else {
            const data = await api(`/api/agents/${encodeURIComponent(btn.dataset.agentInstall)}/install`);
            toast(data.install?.message || 'Install remains operator-controlled.');
          }
        } catch (e) { toast(e.message, true); }
        finally {
          btn.disabled = false;
          btn.textContent = original;
        }
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
      document.querySelectorAll('[data-rename-conversation]').forEach(btn => btn.addEventListener('click', (ev) => {
        ev.stopPropagation();
        // Inline editor, not a native prompt(): sandboxed iframe previews block
        // modal dialogs silently, which would read as a dead button.
        const card = btn.closest('.engagement-card');
        const heading = card ? card.querySelector('h3') : null;
        if (!heading || heading.querySelector('.rename-input')) return;
        const id = btn.dataset.renameConversation;
        const current = heading.textContent;
        heading.innerHTML = `<input class="rename-input" aria-label="Conversation title" value="${esc(current)}" style="background:#0c0c10;border:1px solid var(--cyan);color:var(--text);padding:7px 9px;font:inherit;font-size:12px;width:60%"> <button class="text-button" data-rename-save>SAVE</button> <button class="text-button" data-rename-cancel>CANCEL</button>`;
        const input = heading.querySelector('.rename-input');
        input.addEventListener('click', (e2) => e2.stopPropagation());
        const save = async () => {
          const title = input.value.trim();
          if (!title) { toast('Title is required.', true); return; }
          try { await api(`/api/conversations/${encodeURIComponent(id)}/rename`, { method: 'POST', body: { title } }); toast('Conversation renamed. Reports follow the new name.'); loadConversations(); }
          catch (e) { toast(e.message, true); loadConversations(); }
        };
        heading.querySelector('[data-rename-save]').addEventListener('click', (e2) => { e2.stopPropagation(); save(); });
        heading.querySelector('[data-rename-cancel]').addEventListener('click', (e2) => { e2.stopPropagation(); loadConversations(); });
        input.addEventListener('keydown', (e2) => {
          if (e2.key === 'Enter') { e2.preventDefault(); save(); }
          if (e2.key === 'Escape') { e2.preventDefault(); loadConversations(); }
        });
        input.focus(); input.select();
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
      renderList('task-list', data.tasks || [], 'No tasks recorded.', t => `<article class="activity-item"><span class="activity-icon ${t.state === 'COMPLETED' ? '' : t.state === 'FAILED' ? 'failed' : 'running'}"></span><div><div class="activity-title">${esc(t.id)} · ${esc(t.state)}</div><div class="activity-command">${esc(t.request)}</div></div><div class="activity-meta"><div>${esc(t.risk || '—')}</div><div>${esc(fmtDate(t.updated_at))}</div><div><button class="text-button" data-task-restart="${esc(t.id)}">RESTART</button> <button class="text-button" data-task-resume="${esc(t.id)}">RESUME</button> <button class="text-button" data-task-delete="${esc(t.id)}">DELETE</button></div></div></article>`);
      document.querySelectorAll('[data-task-restart]').forEach(btn => btn.addEventListener('click', async () => {
        try { await api(`/api/tasks/${encodeURIComponent(btn.dataset.taskRestart)}/restart`, { method: 'POST', body: { cwd: state.doctor?.cwd } }); toast('Task restarted with a fresh plan.'); loadTasks(); }
        catch (e) { toast(e.message, true); }
      }));
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
      el.innerHTML = reports.map(r => `<article class="report-card"><div class="panel-kicker">${esc((r.kind || 'task').toUpperCase())}</div><h3>${esc(r.title)}</h3><p>${esc(fmtDate(r.created_at))}<br>${esc(r.task_id || r.operation_id || '')}</p><p>${(r.formats || []).map(fmt => `<a class="report-dl" href="/api/reports/${encodeURIComponent(r.id)}/download?format=${encodeURIComponent(fmt)}">${esc(fmt.toUpperCase())}</a>`).join(' ')} <button class="text-button" data-report-preview="${esc(r.id)}">PREVIEW</button> <button class="text-button" data-report-delete="${esc(r.id)}">DELETE</button></p></article>`).join('');
      document.querySelectorAll('[data-report-preview]').forEach(btn => btn.addEventListener('click', () => previewReport(btn.dataset.reportPreview).catch(err => toast(err.message, true))));
      document.querySelectorAll('[data-report-delete]').forEach(btn => btn.addEventListener('click', async () => {
        try {
          await api(`/api/reports/${encodeURIComponent(btn.dataset.reportDelete)}/delete`, { method: 'POST', body: {} });
          toast('Report deleted. History and audit records are untouched.');
          loadReportsWorkspace();
        } catch (e) { toast(e.message, true); }
      }));
      return;
    }
    if (origRenderReports) origRenderReports();
  };

  async function previewReport(reportId) {
    const host = $('report-window');
    const body = $('report-preview-body');
    const title = $('report-preview-title');
    if (!host || !body) return;
    const record = (state.reports || []).find(r => r.id === reportId);
    if (title) title.textContent = (record && record.title) || 'Report';
    body.textContent = 'Loading report…';
    if (window.VortexWindows?.showSurface) window.VortexWindows.showSurface(host);
    else host.hidden = false;
    const response = await fetch(`/api/reports/${encodeURIComponent(reportId)}/download?format=md`);
    if (!response.ok) throw new Error(`Preview failed (${response.status})`);
    body.textContent = await response.text();
  }
  $('close-report-preview')?.addEventListener('click', () => {
    const host = $('report-window');
    if (!host) return;
    if (window.VortexWindows?.closeSurface) window.VortexWindows.closeSurface(host);
    else host.hidden = true;
  });

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
    const text = String(request || '').trim();
    if (!text) return;
    if (planning) { toast('A request is already in progress.'); return; }
    planning = true;
    const thread = $('chat-thread');
    if (thread) {
      const echo = document.createElement('article');
      echo.className = 'chat-msg user local-echo';
      echo.innerHTML = `<span class="role">YOU</span><p>${esc(text)}</p>`;
      thread.appendChild(echo);
      thread.scrollTop = thread.scrollHeight;
    }
    const input = $('request-input');
    if (input) input.value = '';
    setView('overview');
    const sendButton = $('plan-button');
    if (sendButton) sendButton.disabled = true;
    if (sendButton) sendButton.textContent = 'INSPECTING…';
    try {
      const payload = { request: text, cwd: state.doctor?.cwd || undefined, conversation_id: state.conversationId, offline: !!state.settings.offline };
      if (state.activeEngagementId) payload.engagement_id = state.activeEngagementId;
      const data = await api('/api/workspace/turn', { method: 'POST', body: payload });
      state.conversationId = data.conversation?.id || state.conversationId;
      persistConversationId(state.conversationId);
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
      planning = false;
      const sendButton = $('plan-button');
      if (sendButton) {
        sendButton.disabled = false;
        sendButton.innerHTML = '<span class="spark">✦</span> SEND';
      }
      if (input) {
        try { input.focus({ preventScroll: true }); } catch (_) { input.focus(); }
      }
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
    $('refresh-agents')?.addEventListener('click',()=>loadAgents(true));
    $('refresh-health')?.addEventListener('click',()=>loadHealth(true));
    $('new-conversation')?.addEventListener('click', async () => {
      try {
        const data = await api('/api/conversations', { method: 'POST', body: { title: 'New conversation' } });
        state.conversationId = data.conversation.id;
        persistConversationId(state.conversationId);
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
        toast('First-run checks recorded. Optional components remain unavailable until installed.');
      } catch (e) { toast(e.message, true); }
      finally { hideFirstRun(); }
    });
    $('skip-setup')?.addEventListener('click', () => {
      hideFirstRun();
      toast('First-run checks skipped. You can open them from MISSING DEPENDENCIES.');
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
    $('host-tools-setting')?.addEventListener('change', e => persist({ host_tool_access: e.target.value === 'on' }));
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
    async function loadDependencies() {
      const host = $('dep-window');
      const list = $('dep-list');
      const summary = $('dep-summary');
      if (!host || !list) return;
      if (window.VortexWindows?.showSurface) window.VortexWindows.showSurface(host);
      else host.hidden = false;
      if ($('dep-detail')) $('dep-detail').hidden = true;
      list.textContent = 'Probing this host…';
      try {
        const data = await api('/api/dependencies');
        const deps = data.dependencies || {};
        const missing = deps.missing || [];
        const counts = deps.counts || {};
        if (summary) summary.textContent = `${counts.installed || 0}/${counts.total || 0} present · ${counts.missing || 0} missing · auto_install=${deps.auto_install ? 'yes' : 'no'}`;
        if (!missing.length) {
          list.innerHTML = '<div class="empty-inline">No missing catalog items on this host.</div>';
          return;
        }
        list.innerHTML = missing.map(item => `<div class="dep-row"><div><strong>${esc(item.title)}</strong><small>${esc(item.kind)} · ${esc(item.method)} · ${esc(item.role || '')}</small></div><span class="badge ${item.required ? 'badge-red' : 'badge-muted'}">${item.required ? 'REQUIRED' : 'OPTIONAL'}</span><button class="text-button" data-dep-install="${esc(item.id)}" title="${item.method === 'apt' ? 'Open the reviewed install proposal' : 'No reviewed installer is mapped for this item; VORTEX shows operator instructions only and never auto-installs'}">${item.method === 'apt' ? 'INSTALL' : 'REVIEW'}</button></div>`).join('');
        list.querySelectorAll('[data-dep-install]').forEach(btn => btn.addEventListener('click', () => window.openDependency(btn.dataset.depInstall)));
      } catch (e) { toast(e.message, true); }
    }

    window.openDependencies = loadDependencies;
    window.openDependency = async function (itemId) {
      const host = $('dep-window');
      const detail = $('dep-detail');
      if (host && window.VortexWindows?.showSurface) window.VortexWindows.showSurface(host);
      else if (host) host.hidden = false;
      if (!detail) return;
      detail.hidden = false;
      detail.textContent = 'Loading proposal…';
      try {
        const data = await api('/api/dependencies/proposal?id=' + encodeURIComponent(itemId));
        const item = data.install || {};
        const commands = (item.commands || []).map(line => esc(line)).join('\n');
        const canPlan = item.method === 'apt' && item.plan_request && !item.installed;
        detail.innerHTML = `<strong>${esc(item.title || itemId)}</strong><p>${esc(item.message || '')}</p><p>Source: ${esc(item.source || 'n/a')} · License: ${esc(item.license || 'n/a')}</p><pre>${commands || 'No command is executed by VORTEX.'}</pre>${canPlan ? `<div class="form-foot"><button class="primary-button" id="dep-plan">CREATE APT PLAN</button></div>` : '<p class="form-note">This item is operator-installed. VORTEX will not download it.</p>'}`;
        $('dep-plan')?.addEventListener('click', async () => {
          try {
            const planned = await api('/api/dependencies/plan', { method: 'POST', body: { id: itemId, cwd: state.doctor?.cwd, conversation_id: state.conversationId } });
            if (planned.planned && planned.plan) {
              if (window.VortexWindows?.closeSurface) window.VortexWindows.closeSurface(host);
              else host.hidden = true;
              state.conversationId = planned.conversation?.id || state.conversationId;
              state.task = planned.task;
              state.plan = planned.plan;
              setView('overview');
              if (origRenderPlan) origRenderPlan(planned.plan);
              toast('Reviewed apt plan ready. Approve it only if you administer this host.');
            } else {
              toast(planned.install?.message || 'No automatic install is available.');
            }
          } catch (e) { toast(e.message, true); }
        });
      } catch (e) { toast(e.message, true); }
    };

    // ---- HELP WINDOW ----
    function openHelp(section) {
      const host = $('help-window');
      if (!host) return;
      if (window.VortexWindows?.showSurface) window.VortexWindows.showSurface(host);
      else host.hidden = false;
      if (section) switchHelpSection(section);
    }

    function switchHelpSection(sectionId) {
      const host = $('help-window');
      if (!host) return;
      host.querySelectorAll('.help-section').forEach(el => el.classList.toggle('active', el.id === `help-section-${sectionId}`));
      host.querySelectorAll('.help-nav-item').forEach(btn => btn.classList.toggle('active', btn.dataset.helpSection === sectionId));
    }

    $('open-help')?.addEventListener('click', () => openHelp('getting-started'));

    // Wire help nav buttons
    const helpHost = $('help-window');
    if (helpHost) {
      helpHost.querySelectorAll('[data-help-section]').forEach(btn => {
        btn.addEventListener('click', () => switchHelpSection(btn.dataset.helpSection));
      });
    }

    // "About → Authorized Use" link in About window opens Help at the warning section
    $('about-open-help-warning')?.addEventListener('click', (ev) => {
      ev.preventDefault();
      const aboutHost = $('about-window');
      if (aboutHost && window.VortexWindows?.closeSurface) window.VortexWindows.closeSurface(aboutHost);
      else if (aboutHost) aboutHost.hidden = true;
      openHelp('security-warning');
    });

    // ---- ABOUT WINDOW ----
    function openAbout() {
      const host = $('about-window');
      if (!host) return;
      // Populate system info from already-loaded doctor data
      const d = state.doctor;
      if (d) {
        const distroEl = $('about-distro');
        const kernelEl = $('about-kernel');
        const archEl = $('about-arch');
        const privEl = $('about-priv');
        if (distroEl) distroEl.textContent = d.distribution?.pretty_name || d.distribution?.id || '—';
        if (kernelEl) kernelEl.textContent = d.kernel || '—';
        if (archEl) archEl.textContent = d.architecture || '—';
        if (privEl) privEl.textContent = d.root ? 'UID 0 (root) — guarded' : (d.uid !== undefined ? `UID ${d.uid}` : '—');
      }
      if (window.VortexWindows?.showSurface) window.VortexWindows.showSurface(host);
      else host.hidden = false;
    }

    $('open-about')?.addEventListener('click', openAbout);

    window.openHelp = openHelp;
    window.openAbout = openAbout;

    $('open-deps')?.addEventListener('click', loadDependencies);
    $('open-deps-from-setup')?.addEventListener('click', loadDependencies);
    $('open-deps-from-tools')?.addEventListener('click', loadDependencies);
    $('close-deps')?.addEventListener('click', () => {
      const host = $('dep-window');
      if (!host) return;
      if (window.VortexWindows?.closeSurface) window.VortexWindows.closeSurface(host);
      else host.hidden = true;
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
