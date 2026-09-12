/* VORTEX renderer. In Electron all requests go through the typed preload bridge;
   the relative fetch fallback keeps the local preview useful without Electron. */
const state = { currentView: 'overview', plan: null, doctor: null, tools: [], history: [], engagements: [], activeEngagementId: null, sessions: [], activeSessionId: null, paneIds: [], sessionSeqs: {}, sessionStreams: {}, sessionStreamRetryAt: {}, sessionTimer: null, plain: false };
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
const fmtDate = (value) => { if (!value) return '—'; try { return new Intl.DateTimeFormat(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(value)); } catch { return value; } };
let browserCapability = '';
let browserSessionPromise = null;
let capabilityFragmentPresent = false;
try {
  const fragment = new URLSearchParams(location.hash.replace(/^#/, ''));
  capabilityFragmentPresent = fragment.has('vortex-token');
  if (capabilityFragmentPresent) {
    const supplied = String(fragment.get('vortex-token') || '').trim();
    if (supplied && supplied.length <= 256 && !/[\x00-\x1f\x7f]/.test(supplied)) {
      browserCapability = supplied;
      try { sessionStorage.setItem('vortex-capability', supplied); } catch (_) { /* in-memory exchange still works */ }
    } else {
      try { sessionStorage.removeItem('vortex-capability'); } catch (_) { /* storage may be disabled */ }
    }
  } else {
    try { browserCapability = sessionStorage.getItem('vortex-capability') || ''; } catch (_) { browserCapability = ''; }
  }
} catch (_) { browserCapability = ''; }
if (capabilityFragmentPresent) {
  try { history.replaceState(null, '', location.pathname + location.search); } catch (_) { /* constrained WebViews may deny history mutation */ }
}
function showCapabilityDialog(message = '') {
  if (window.vortexApi?.request) return;
  const dialog = $('capability-dialog');
  if (!dialog) return;
  const error = $('capability-error');
  if (error) error.textContent = message;
  if (!dialog.open) dialog.showModal();
  setTimeout(() => $('capability-input')?.focus(), 0);
}
async function establishBrowserSession() {
  if (!browserCapability || window.vortexApi?.request) return;
  if (!browserSessionPromise) {
    browserSessionPromise = fetch('/api/auth/session', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Vortex-Token': browserCapability},
      body: '{}'
    }).then(async response => {
      if (!response.ok) {
        let message = 'The sidecar capability was rejected.';
        try { message = (await response.json()).error?.message || message; } catch (_) { /* use bounded fallback */ }
        throw new Error(message);
      }
      try { sessionStorage.removeItem('vortex-capability'); } catch (_) { /* storage may be disabled */ }
      browserCapability = '';
    }).catch(error => {
      browserSessionPromise = null;
      try { sessionStorage.removeItem('vortex-capability'); } catch (_) { /* storage may be disabled */ }
      browserCapability = '';
      showCapabilityDialog(error.message);
      throw error;
    });
  }
  return browserSessionPromise;
}
const api = async (path, options = {}) => {
  if (window.vortexApi?.request) return window.vortexApi.request(path, options);
  if (browserCapability) await establishBrowserSession();
  const response = await fetch(path, { headers: {'Content-Type':'application/json', ...(browserCapability ? {'X-Vortex-Token': browserCapability} : {}), ...(options.headers || {})}, ...options, body: options.body && typeof options.body !== 'string' ? JSON.stringify(options.body) : options.body });
  let payload;
  try { payload = await response.json(); } catch (_) { throw new Error(`Sidecar returned an invalid response (${response.status})`); }
  if (!response.ok) {
    if (response.status === 401) showCapabilityDialog('Enter the capability printed by the remote VORTEX sidecar.');
    throw new Error(payload.error?.message || `Request failed (${response.status})`);
  }
  return payload;
};
function toast(message, bad = false) { const el = $('toast'); el.setAttribute('role', bad ? 'alert' : 'status'); el.setAttribute('aria-live', bad ? 'assertive' : 'polite'); el.textContent = message; el.style.borderColor = bad ? 'var(--red)' : 'var(--cyan)'; el.classList.add('show'); clearTimeout(window.toastTimer); window.toastTimer = setTimeout(() => el.classList.remove('show'), 4200); }
function setView(view) { state.currentView = view; document.querySelectorAll('.view').forEach(el => { const active = el.id === `view-${view}`; el.classList.toggle('active', active); el.setAttribute('aria-hidden', String(!active)); }); document.querySelectorAll('.nav-item').forEach(el => { const active = el.dataset.view === view; el.classList.toggle('active', active); if (active) el.setAttribute('aria-current', 'page'); else el.removeAttribute('aria-current'); }); $('view-title').textContent = view.toUpperCase(); document.title = `${view.replace(/(^|-)([a-z])/g, (_, prefix, letter) => `${prefix ? ' ' : ''}${letter.toUpperCase()}`)} — VORTEX`; if (view === 'activity') loadHistory(); if (view === 'terminal') loadSessions().then(() => focusPtySurface()); if (view === 'tools') loadTools(); if (view === 'engagements') loadEngagements(); if (view === 'reports') loadHistory().then(renderReports); if (view === 'models' && typeof window.loadModels === 'function') window.loadModels(true); }
function statusClass(status) { return ['succeeded','success'].includes(status) ? 'badge-green' : ['failed','timed_out','interrupted'].includes(status) ? 'badge-red' : status === 'planned' || status === 'awaiting_confirmation' ? 'badge-amber' : 'badge-muted'; }
function statusLabel(status) { return ({succeeded:'VERIFIED OK',failed:'FAILED',timed_out:'TIMED OUT',interrupted:'INTERRUPTED',unavailable:'TOOL MISSING',running:'RUNNING',started:'STARTED',planned:'CONFIRM REQUIRED',awaiting_confirmation:'PREFLIGHT COMPLETE',clarified:'PLAN ONLY',rejected:'BLOCKED',unknown_after_crash:'UNKNOWN AFTER CRASH'}[status] || String(status || 'STANDBY').toUpperCase()); }

/* ---- clipboard + terminal handoff for install commands ---- */
async function copyText(text, label = 'Copied to clipboard.') {
  const value = String(text || '');
  try {
    if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(value); toast(label); return true; }
  } catch (_) { /* fall through to the legacy path */ }
  try {
    const area = document.createElement('textarea');
    area.value = value;
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    const ok = document.execCommand('copy');
    area.remove();
    toast(ok ? label : 'Copy failed — select the commands manually.', !ok);
    return ok;
  } catch (_) { toast('Copy failed — select the commands manually.', true); return false; }
}
window.copyText = copyText;

async function openInTerminal(lines, label = 'commands') {
  const text = String(lines || '').trim();
  if (!text) return;
  setView('terminal');
  const session = activeSession();
  if (!session || session.status !== 'running') {
    $('open-session')?.click();
    await new Promise(resolve => setTimeout(resolve, 400));
  }
  await copyText(text, `${label} copied — click the terminal pane and paste (Ctrl+Shift+V).`);
  focusPtySurface();
}
window.openInTerminal = openInTerminal;

async function loadDoctor(refresh = false) { try { const data = await api(`/api/doctor${refresh ? '?fresh=1' : ''}`); state.doctor = data.doctor; renderDoctor(); } catch (e) { $('side-context').textContent = 'backend offline'; toast(e.message, true); } }
function renderDoctor() { const d = state.doctor; if (!d) return; $('side-context').textContent = `${d.distribution.pretty_name || d.distribution.id} · ${d.architecture}`; $('terminal-cwd').textContent = d.cwd; $('context-content').innerHTML = [
  ['DISTRIBUTION', d.distribution.pretty_name || d.distribution.id], ['SUPPORT TIER', d.support_tier], ['KERNEL', d.kernel], ['PID 1 / SYSTEMD', `${d.pid1 || 'unknown'} / ${d.systemd ? 'available' : 'unavailable'}`], ['CONTEXT', [d.container ? 'container' : 'host', d.ssh ? 'SSH' : 'local', d.tmux ? 'tmux' : 'direct'].join(' · ')], ['PRIVILEGE', d.root ? 'UID 0 — guarded' : `UID ${d.uid}`], ['MODEL', 'disabled by default']
].map(([a,b]) => `<div class="context-row"><label>${esc(a)}</label><span class="${String(b).includes('available') || String(b).includes('local') ? 'ok':''}">${esc(b)}</span></div>`).join(''); }
async function loadTools(refresh = false) { try { const data = await api(`/api/tools${refresh ? '?fresh=1' : ''}`); state.tools = data.tools; renderTools(); await loadHostTools(refresh); } catch(e) { toast(e.message, true); } }
function renderTools() {
  $('tool-grid').innerHTML = state.tools.map(t => `<article class="tool-card ${esc(t.state)}"><span class="badge ${t.state === 'installed' ? 'badge-green' : t.state === 'blocked' ? 'badge-red' : 'badge-muted'}">${esc(t.state.replace('-', ' ').toUpperCase())}</span><h3>${esc(t.name)}</h3><div class="tool-family">${esc(t.family)}</div><p>${esc(t.role)}<br><span class="tool-path">${esc(t.path || 'No executable found')}</span><br>${t.version ? esc(t.version) : 'Version unavailable'}</p>${t.state === 'installed' ? '' : `<p><button class="text-button" data-tool-install="tool:${esc(t.name)}">INSTALL</button></p>`}</article>`).join('');
  document.querySelectorAll('[data-tool-install]').forEach(btn => btn.addEventListener('click', () => {
    if (typeof window.openDependency === 'function') window.openDependency(btn.dataset.toolInstall);
  }));
}
async function loadHostTools(refresh = false) {
  const grid = $('host-tool-grid');
  const strip = $('host-tools-strip');
  if (!grid) return;
  try {
    const data = refresh
      ? await api('/api/tools/host/rescan', { method: 'POST', body: {} })
      : await api('/api/tools/host');
    const scan = data.host_tools || {};
    const tools = scan.tools || [];
    const counts = scan.counts || {};
    const neu = scan.new_since_last_scan || [];
    if (strip) {
      strip.className = 'audit-strip' + (neu.length ? ' valid' : '');
      strip.textContent = `PATH ${counts.path_executables || 0} executables · Kali known ${counts.kali_known_installed || 0} installed / ${counts.kali_known_absent || 0} absent · ${counts.discovered || 0} outside builtin catalog · ${neu.length} new since last scan · host_tool_access=${data.host_tool_access ? 'on' : 'off'}`;
    }
    const extra = tools.filter(t => !t.in_builtin_catalog).slice(0, 120);
    grid.innerHTML = extra.length ? extra.map(t => `<article class="tool-card ${esc(t.state)}${t.new_since_last_scan ? ' new-tool' : ''}"><span class="badge ${t.new_since_last_scan ? 'badge-amber' : 'badge-green'}">${t.new_since_last_scan ? 'NEW' : 'PATH'}</span><h3>${esc(t.name)}</h3><div class="tool-family">${esc(t.family || '')} · ${esc(t.source || '')}</div><p>${esc(t.role || '')}<br><span class="tool-path">${esc(t.path || '')}</span><br>risk ${esc(t.risk_level || '')} · ${t.requires_network ? 'network' : 'local'}</p></article>`).join('') : '<div class="empty-inline">No extra PATH tools beyond the builtin catalog.</div>';
  } catch (e) { toast(e.message, true); }
}

/* ---- global refresh: one forced re-probe of every subsystem ---- */
async function refreshAll() {
  const button = $('refresh-all');
  if (button?.disabled) return;
  if (button) { button.disabled = true; button.textContent = 'REFRESHING…'; }
  try {
    const data = await api('/api/refresh', { method: 'POST', body: {} });
    const r = data.refresh || {};
    const bits = [];
    if (r.agents?.total != null) bits.push(`agents ${r.agents.available}/${r.agents.total}`);
    if (r.tools?.catalog != null) bits.push(`tools ${r.tools.installed}/${r.tools.catalog}`);
    if (r.gguf?.files != null) bits.push(`models ${r.gguf.valid} valid GGUF`);
    if (r.ollama?.api_state != null) bits.push(`ollama ${r.ollama.installed ? 'installed' : 'absent'}`);
    if (r.dependencies?.missing != null) bits.push(`deps ${r.dependencies.missing} missing`);
    toast(`Re-probed host in ${r.elapsed_ms ?? '…'} ms · ${bits.join(' · ')}`);
    await Promise.allSettled([loadDoctor(true), loadTools(true), loadEngagements(), loadHistory(), window.loadModels?.(true), window.loadAiOps?.(true)]);
    if (typeof window.refreshHud === 'function') await window.refreshHud();
    if (state.currentView === 'agents' && typeof window.loadAgents === 'function') window.loadAgents(true);
    if (state.currentView === 'system' && typeof window.loadHealth === 'function') window.loadHealth(true);
    if (typeof window.renderAgentsLocalAi === 'function') window.renderAgentsLocalAi();
  } catch (e) { toast(e.message, true); }
  finally { if (button) { button.disabled = false; button.textContent = 'REFRESH ALL ↻'; } }
}
window.refreshAll = refreshAll;

async function downloadApk() {
  toast('Syncing the live workbench into the Android APK…');
  try {
    const data = await api('/api/mobile/apk', { method: 'POST', body: {} });
    if (!data.apk || !data.apk.ok) { toast((data.apk && data.apk.message) || 'APK build failed.', true); return; }
    const url = '/api/mobile/apk/download';
    triggerDownload(url, 'vortex.apk');
    showDownloadToast(`APK synced from the live workbench (${data.apk.size_bytes} bytes, MIT) — `, url, 'vortex.apk', 'DOWNLOAD vortex.apk');
  } catch (e) { toast(e.message, true); }
}
async function downloadDeb() {
  toast('Building the live workbench into a Linux desktop package…');
  try {
    const data = await api('/api/desktop/deb', { method: 'POST', body: {} });
    if (!data.deb || !data.deb.ok) { toast((data.deb && data.deb.message) || 'Desktop package build failed.', true); return; }
    const url = '/api/desktop/deb/download';
    const filename = data.deb.filename || 'vortex.deb';
    triggerDownload(url, filename);
    showDownloadToast(`Desktop .deb built from the live workbench (${data.deb.size_bytes} bytes, unsigned — review before install) — `, url, filename, `DOWNLOAD ${filename}`);
  } catch (e) { toast(e.message, true); }
}
function triggerDownload(url, filename) {
  if (!window.vortexApi?.request) {
    try { if (window.open(url, '_blank')) return; } catch (_) { /* popup blocked — fall through */ }
  }
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
}
function showDownloadToast(prefix, url, filename, label) {
  const el = $('toast');
  el.textContent = prefix;
  const manual = document.createElement('a');
  manual.href = url;
  manual.download = filename;
  manual.target = '_blank';
  manual.rel = 'noopener';
  manual.className = 'report-dl';
  manual.textContent = label;
  el.appendChild(manual);
  el.style.borderColor = 'var(--cyan)';
  el.classList.add('show');
  clearTimeout(window.toastTimer);
  window.toastTimer = setTimeout(() => el.classList.remove('show'), 10000);
}
window.downloadApk = downloadApk;
window.downloadDeb = downloadDeb;
function engagementLive(item) {
  if (!item || item.status !== 'active' || item.expired || item.effective_status === 'expired') return false;
  const expires = Date.parse(item.expires_at);
  if (!Number.isNaN(expires) && expires <= Date.now()) return false;
  return true;
}
async function loadEngagements() { try { const data = await api('/api/engagements'); state.engagements = data.engagements; const current = state.engagements.find(e => e.id === state.activeEngagementId); if (!engagementLive(current)) state.activeEngagementId = (state.engagements.find(engagementLive) || {}).id || null; renderEngagements(); } catch(e) { toast(e.message, true); } }
function renderEngagements() { const el = $('engagement-list'); if (!state.engagements.length) { el.innerHTML = `<div class="empty-state panel"><div class="empty-icon">◎</div><h3>No active engagements</h3><p>Active tools such as nmap stay unavailable until a scope and expiry are declared.</p></div>`; return; } el.innerHTML = state.engagements.map(e => `<article class="engagement-card"><header><div><h3>${esc(e.name)}</h3><p>${esc(e.authorization)}</p></div><span class="badge ${e.status === 'active' ? 'badge-green':'badge-muted'}">${esc(e.status.toUpperCase())}</span></header><div>${e.targets.map(t => `<span class="target-pill">${esc(t)}</span>`).join('')}</div><div class="engagement-details"><span>ID ${esc(e.id.slice(0,12))}…</span><span>EXPIRES ${esc(fmtDate(e.expires_at))}</span><span>${e.classes.map(esc).join(' · ')}</span>${(e.excluded_targets||[]).length ? `<span>EXCL ${(e.excluded_targets||[]).map(esc).join(', ')}</span>` : ''}<a class="report-dl" href="/api/reports/assessment/${encodeURIComponent(e.id)}">ASSESSMENT</a>${e.status === 'active' ? ` <button class="text-button" data-close-engagement="${esc(e.id)}">CLOSE</button>` : ''}</div></article>`).join('');
  document.querySelectorAll('[data-close-engagement]').forEach(btn => btn.addEventListener('click', async () => {
    try { await api(`/api/engagements/${encodeURIComponent(btn.dataset.closeEngagement)}/close`, {method:'POST', body:{}}); toast('Engagement closed.'); loadEngagements(); }
    catch (e) { toast(e.message, true); }
  }));
}
async function loadHistory() { try { const data = await api('/api/history'); state.history = data.history; renderActivity(); return state.history; } catch(e) { toast(e.message, true); return []; } }
function operationTitle(op) { const command = op.commands?.[0]?.display || 'No command executed'; return command.length > 67 ? command.slice(0,67) + '…' : command; }
function activityMarkup(op) { const s = op.status || 'unknown'; return `<article class="activity-item"><span class="activity-icon ${s === 'succeeded' ? '' : s === 'running' ? 'running':'failed'}"></span><div><div class="activity-title">${esc(statusLabel(s))} <span style="color:var(--dim)">· ${esc(fmtDate(op.ended_at || op.started_at))}</span></div><div class="activity-command">${esc(operationTitle(op))}</div></div><div class="activity-meta"><div class="activity-status ${s !== 'succeeded' ? s === 'running' ? 'running':'failed':''}">${esc(statusLabel(s))}</div><div>${op.commands?.length || 0} command${(op.commands?.length || 0) === 1 ? '':'s'}</div></div></article>`; }
function renderActivity() { const html = state.history.length ? state.history.map(activityMarkup).join('') : '<div class="empty-inline">No operations recorded. Plans remain private until you approve them.</div>'; $('activity-full').innerHTML = html; }
function renderReports() { const el = $('report-grid'); if (!state.history.length) { el.innerHTML = `<div class="empty-state panel"><div class="empty-icon">▤</div><h3>Reports appear after execution</h3><p>Run an approved plan to create a local analysis record.</p></div>`; return; } el.innerHTML = state.history.map(op => `<article class="report-card"><div class="panel-kicker">LOCAL REPORT</div><h3>${esc(statusLabel(op.status))}</h3><p>${esc(fmtDate(op.started_at))}<br>${esc(operationTitle(op))}</p><p>${op.artifacts?.length || 0} parsed artifact${(op.artifacts?.length || 0) === 1 ? '' : 's'} · raw evidence is not retained by default</p><code>evidence ${esc((op.output_digest || 'not-available').slice(0,24))}…</code></article>`).join(''); }
function renderPlan(plan) { state.plan = plan; const badge = $('plan-badge'); badge.textContent = statusLabel(plan.status); badge.className = `badge ${statusClass(plan.status)}`; let commands = plan.commands?.length ? plan.commands.map((c, i) => `<div class="command-spec"><code>${esc(c.display)}</code><div class="spec-meta"><span>${esc(c.required_tool)}: ${esc(c.tool_state_at_plan)}</span><span>RISK: ${esc(c.risk.toUpperCase())}</span><span>NETWORK: ${esc(c.network_class)}</span><span>TIMEOUT: ${esc(c.timeout_seconds)}s</span><span>PRIVILEGE: ${esc(c.privilege || 'user')}</span></div><p style="color:var(--muted);font-size:10px;line-height:1.5;margin:9px 0 0">${esc(c.explanation)}</p></div>`).join('') : '<div class="command-spec"><code>NO EXECUTION</code><p style="color:var(--dim);font-size:10px;margin:7px 0 0">This request produces explanation or clarification only.</p></div>';
 const notes = (plan.notes || []).map(n => `<li>${esc(n)}</li>`).join(''); const worker = (plan.workers || []).map(w => `<span>${esc(w.id)}: <strong>${esc(w.state)}</strong></span>`).join(' · ');
 const suggestions = (plan.suggestions || []).map(s => `<button class="suggestion-chip" data-suggestion="${esc(s)}">${esc(s)}</button>`).join('');
 const knowledge = (plan.knowledge || []).map(k => `<article class="knowledge-item"><span>${esc(k.label)}</span><code>${esc((k.examples || []).slice(0,2).join(' · '))}</code></article>`).join('');
 const rootRequired = (plan.commands || []).some(c => c.privilege === 'root-required');
 const aptDependency = plan.kind === 'package_operation' && (plan.commands || []).some(c => c.adapter_id === 'linux.packages.apt' && c.privilege === 'root-required');
 const installAction = aptDependency ? '<button class="approve-button" id="launch-dependency-install">OPEN INSTALL TERMINAL</button>' : '';
 const rootHint = rootRequired ? `<div class="approval root-approval"><small>OS AUTHENTICATION REQUIRED · VORTEX never reads your password. ${aptDependency ? 'Open the installation terminal here, type APPROVE after reviewing the plan, then respond directly to the operating system prompt.' : `In a terminal, run <code>vortex run ${esc(plan.id)}</code>.`} A fresh preflight and second approval protect the final mutation.</small>${installAction}</div>` : '';
 $('plan-content').className = 'plan-card'; $('plan-content').innerHTML = `<div class="plan-summary"><div class="plan-objective"><span>OBJECTIVE / ${esc(plan.kind.replace('_',' '))}</span>${esc(plan.request)}</div><span class="badge ${statusClass(plan.status)}">${esc(statusLabel(plan.status))}</span></div><ul class="plan-notes">${notes}</ul>${suggestions ? `<div class="suggestion-row"><small>TRY ONE OF THESE</small>${suggestions}</div>` : ''}${knowledge ? `<div class="knowledge-row"><small>LOCAL CAPABILITIES</small>${knowledge}</div>` : ''}${commands}${rootHint}<div class="worker-row">WORKERS · ${worker}</div>${plan.approval_required && plan.status === 'planned' && !rootRequired ? `<div class="approval"><small>⌁ ${esc(plan.approval_phrase)}</small><button class="approve-button" id="approve-plan">APPROVE &amp; EXECUTE</button></div>` : ''}`;
 $('approve-plan')?.addEventListener('click', approvePlan);
 $('launch-dependency-install')?.addEventListener('click', () => launchDependencyInstall(plan));
 document.querySelectorAll('[data-suggestion]').forEach(btn => btn.addEventListener('click', () => { if (typeof window.makePlan === 'function') window.makePlan(btn.dataset.suggestion); }));
 if (typeof window.updateAiOpsHud === 'function') window.updateAiOpsHud({ plan });
}
async function approvePlan() { if (!state.plan) return; const button = $('approve-plan'); button.disabled = true; button.textContent = 'STARTING…'; try { const data = await api('/api/execute', {method:'POST', body:{plan_id:state.plan.id, approval_token:state.plan.approval_token, confirm:true}}); const op = data.operation; renderPlan({...state.plan, status:'started'}); toast('Operation started. Streaming real output from the local sidecar.'); await watchOperation(op.id); } catch(e) { button.disabled = false; button.textContent = 'APPROVE & EXECUTE'; toast(e.message, true); } }
async function launchDependencyInstall(plan) {
  const button = $('launch-dependency-install');
  if (!plan?.id || button?.disabled) return;
  if (button) { button.disabled = true; button.textContent = 'OPENING…'; }
  try {
    const size = terminalMetrics();
    const data = await api('/api/dependencies/execute', {method:'POST', body:{plan_id:plan.id, cols:size.cols, rows:size.rows}});
    setView('terminal');
    adoptSession(data.session);
    toast('Secure install terminal opened. Review and type APPROVE there; any password goes only to the operating system.');
  } catch (e) {
    if (button) { button.disabled = false; button.textContent = 'OPEN INSTALL TERMINAL'; }
    toast(e.message, true);
  }
}
async function watchOperation(id) {
  const finish = async (op) => { renderAnalysis(op); await loadHistory(); };
  const commandBudget = (state.plan?.commands || []).reduce((total, command) => total + Number(command.timeout_seconds || 30), 0);
  const deadline = Date.now() + Math.min(3600, Math.max(90, commandBudget + 60)) * 1000;
  if (window.EventSource) {
    try {
      const streamed = await new Promise((resolve) => {
        const es = new EventSource(`/api/operations/${encodeURIComponent(id)}/stream`);
        const timer = setTimeout(() => { es.close(); resolve(null); }, 65000);
        es.onmessage = (ev) => {
          try {
            const op = JSON.parse(ev.data).operation;
            if (op && !['started', 'running'].includes(op.status)) {
              clearTimeout(timer); es.close(); resolve(op);
            } else if (op) { renderLiveIfPresent(op); }
          } catch (_) { /* keep listening */ }
        };
        es.onerror = () => { clearTimeout(timer); es.close(); resolve(null); };
      });
      if (streamed) { await finish(streamed); return; }
    } catch (_) { /* fall through to poll */ }
  }
  while (Date.now() < deadline) {
    await new Promise(r => setTimeout(r, 1000));
    try {
      const data = await api(`/api/operations/${encodeURIComponent(id)}`);
      const op = data.operation;
      if (!op) continue;
      if (!['started', 'running'].includes(op.status)) { await finish(op); return; }
      renderLiveIfPresent(op);
    } catch (e) { toast(e.message, true); return; }
  }
  toast('Operation exceeded its display deadline; its final state remains available in Activity.', true);
}
function renderLiveIfPresent(op) {
  if (typeof renderLiveOutput === 'function') renderLiveOutput(op);
}
async function approveMutation(op) {
  const button = $('approve-mutation');
  if (button) { button.disabled = true; button.textContent = 'APPROVING…'; }
  try {
    const data = await api(`/api/operations/${encodeURIComponent(op.id)}/approve`, {method:'POST', body:{confirm:true, approval_token:state.plan?.approval_token, preflight_digest:op.preflight_digest}});
    toast('Fresh preflight approved. The exact mutation is starting.');
    await watchOperation(data.operation.id);
  } catch (e) {
    if (button) { button.disabled = false; button.textContent = 'APPROVE MUTATION'; }
    toast(e.message, true);
  }
}
function renderAnalysis(op) {
  const a = op.analysis || {};
  const verdict = a.verdict || {};
  const verdictColor = verdict.outcome === 'PASS' ? 'var(--green)' : verdict.outcome === 'FAIL' ? 'var(--red)' : 'var(--amber)';
  const timeline = (a.commands || op.commands || []).map(c => `<div class="timeline-command"><code>${esc(c.command || c.display || c.argv?.join(' '))}</code><small><b style="color:${c.verdict === 'PASS' ? 'var(--green)' : c.verdict === 'FAIL' ? 'var(--red)' : 'var(--amber)'}">${esc(c.verdict || statusLabel(c.status))}</b> · exit ${esc(c.exit_code ?? '—')} · ${esc(c.duration_ms ?? '—')} ms · ${esc(c.observed_lines || 0)} line(s) · ${esc(c.output_bytes || 0)} B · ${esc(c.summary || `${c.observed_lines || 0} observed line(s)`)}</small></div>`).join('');
  const awaiting = op.status === 'awaiting_confirmation';
  const confirmation = awaiting ? `<div class="approval"><small>Fresh facts are complete. Review the adapter facts and approve only this exact mutation.</small><button class="approve-button" id="approve-mutation">APPROVE MUTATION</button></div>` : '';
  const steps = (a.next_steps || []).map(step => `<button class="suggestion-chip" data-next-step="${esc(step.text)}"><code>${esc(step.label)}</code>&nbsp; ${esc(step.text)}</button>`).join('');
  const verification = a.verification ? `<div class="analysis-block"><h3>Verification</h3><p><b style="color:var(--text)">${esc(a.verification.state)}</b> · ${esc(a.verification.observed_commands || 0)}/${esc(a.verification.total_commands || 0)} command(s) produced observed output</p><p style="color:var(--dim);font-size:10px">${esc(a.verification.note || '')}</p></div>` : '';
  const localAi = a.local_ai || {};
  const localAiRoute = (localAi.route?.selected || []).map(item => `${esc(item.role)}=${esc(item.model)}`).join(' · ');
  const localAiFallback = localAi.fallback?.used ? ` · FALLBACK: ${esc(localAi.fallback.reason || 'alternate advisory used')}${localAi.fallback.effective_model ? ` → ${esc(localAi.fallback.effective_model)}` : ''}` : '';
  const localAiBlock = localAi.state ? `<div class="analysis-block"><h3>Local AI interpretation</h3><p><b style="color:var(--text)">${esc((localAi.fuzzy && localAi.fuzzy.confidence) || localAi.state)}</b> · ${esc(localAiRoute || 'no routed model')} · ${esc((localAi.fuzzy && localAi.fuzzy.evidence_basis) || 'plan-only')}${localAiFallback}</p><p>${esc(localAi.synthesis?.fact_summary || localAi.message || 'No local AI interpretation was available.')}</p><p style="color:var(--dim);font-size:10px">${esc(localAi.synthesis?.meaning || localAi.synthesis?.unknowns || '')}</p></div>` : '';
  $('plan-badge').textContent = a.lifecycle || statusLabel(op.status);
  $('plan-badge').className = `badge ${statusClass(op.status)}`;
  const actionRow = (op.commands && op.commands.length) ? `<div class="analysis-block results-actions"><h3>Results actions</h3><div><button class="text-button" data-result-action="verify">VERIFY</button> <button class="text-button" data-result-action="report">REPORT</button> <button class="text-button" data-result-action="export">EXPORT</button></div><p style="color:var(--dim);font-size:10px;margin-top:7px">Verify re-checks the audit hash chain. Report and Export act on real stored data; only appropriate actions are offered for a result with observed output.</p></div>` : '';
  $('plan-content').className = 'plan-card';
  $('plan-content').innerHTML = `<div class="analysis-block"><h3>${esc(a.lifecycle || statusLabel(op.status))} · verified outcome</h3><p>${esc(a.fact || 'Observed execution record.')}</p></div><div class="analysis-block" style="border:1px solid ${verdictColor};background:rgba(0,0,0,.25)"><h3 style="color:${verdictColor}">VERDICT · ${esc(verdict.outcome || 'NOT RUN')}</h3><p><b style="color:${verdictColor}">${esc(verdict.passed ?? 0)}/${esc(verdict.total_commands ?? 0)} commands passed</b> · ${esc(verdict.failed ?? 0)} failed · ${esc(verdict.total_duration_ms ?? 0)} ms wall execution · ${esc(verdict.total_observed_lines ?? 0)} output line(s) · ${esc(verdict.total_output_bytes ?? 0)} bytes of evidence</p><p style="color:var(--dim);font-size:10px;margin-top:7px">${esc(verdict.note || '')}</p></div><div class="analysis-block"><h3>Command timeline</h3>${timeline || '<p>No command was run.</p>'}</div><div class="analysis-block"><h3>Interpretation boundaries</h3><p><b style="color:var(--text)">Fact:</b> ${esc(a.fact || 'Observed output only.')}<br><b style="color:var(--text)">Inference:</b> ${esc(a.inference || '')}<br><b style="color:var(--text)">Unknown:</b> ${esc(a.unknown || '')}</p></div>${verification}${localAiBlock}${steps ? `<div class="analysis-block"><h3>Next steps — click to run the reviewed follow-up</h3>${steps}</div>` : ''}<div class="analysis-block"><h3>Adapter facts</h3><pre class="analysis-json">${esc(JSON.stringify(a.adapter_facts || {}, null, 2))}</pre></div>${confirmation}${actionRow}<div class="worker-row">WORKER PARTICIPATION · ${(a.workers || []).map(w => `${esc(w.id)}: <strong>${esc(w.state)}</strong>`).join(' · ')}</div>`;
  document.querySelectorAll('[data-next-step]').forEach(btn => btn.addEventListener('click', () => { if (typeof window.makePlan === 'function') window.makePlan(btn.dataset.nextStep); }));
  $('approve-mutation')?.addEventListener('click', () => approveMutation(op));
  document.querySelectorAll('[data-result-action]').forEach(btn => btn.addEventListener('click', async () => {
    const action = btn.dataset.resultAction;
    try {
      if (action === 'verify') {
        const data = await api('/api/audit/verify');
        const audit = data.audit || {};
        toast('Audit chain ' + (audit.valid ? 'INTACT' : 'BROKEN') + ' · ' + String(audit.checked || 0) + ' event(s)');
      } else if (action === 'report') {
        const data = await api('/api/reports');
        const report = (data.reports || []).find(r => r.operation_id === op.id);
        if (!report) { toast('No report for this operation yet — it is generated when the task completes.', true); return; }
        window.open(`/api/reports/${encodeURIComponent(report.id)}/download?format=md`, '_blank');
      } else if (action === 'export') {
        if (!state.conversationId) { toast('No active conversation to export.', true); return; }
        window.open(`/api/conversations/${encodeURIComponent(state.conversationId)}/export`, '_blank');
      }
    } catch (e) { toast(e.message, true); }
  }));
  if (typeof window.updateAiOpsHud === 'function') window.updateAiOpsHud({ operation: op });
}

async function createEngagement() {
  const name = $('eng-name').value.trim(), authorization = $('eng-auth').value.trim(), target = $('eng-target').value.trim();
  if (!name || !authorization || !target) return toast('Name, authorization reference, and target are required.', true);
  const excluded = ($('eng-excluded')?.value || '').split(',').map(s => s.trim()).filter(Boolean);
  const body = {name, authorization, targets:[target], classes:['reconnaissance','defensive-analysis'], excluded_targets: excluded, owner: $('eng-owner')?.value || '', environment: $('eng-env')?.value || ''};
  try { const data = await api('/api/engagements',{method:'POST',body}); state.engagements.unshift(data.engagement); state.activeEngagementId = data.engagement.id; renderEngagements(); $('engagement-form').hidden=true; toast('Engagement scope created. Targets are rechecked at execution.'); } catch(e) { toast(e.message,true); }
}
async function verifyAudit() { try { const data = await api('/api/audit/verify'); const el = $('audit-result'); el.className = `audit-strip ${data.audit.valid ? 'valid':'invalid'}`; el.innerHTML = `<span class="status-dot"></span> ${data.audit.valid ? `AUDIT CHAIN VERIFIED · ${data.audit.checked} event(s)` : `AUDIT CHAIN INVALID · ${esc(data.audit.error)}`}`; } catch(e) { toast(e.message,true); } }
function terminalMetrics() {
  const host = $('terminal-panes');
  const width = (host && host.clientWidth) || Math.max(640, innerWidth - 280);
  const height = (host && Math.max(host.clientHeight, 370)) || 420;
  const cols = Math.max(40, Math.min(220, Math.floor((width - 36) / 8.2)));
  const rows = Math.max(12, Math.min(60, Math.floor((height - 16) / 21)));
  return { cols, rows };
}
function focusPtySurface() {
  const pane = sessionOutput(state.activeSessionId) || document.querySelector('#terminal-panes [data-session-output]:not([hidden])') || $('terminal-output');
  if (pane) pane.focus({ preventScroll: true });
}
function ptyKey(e) {
  if (e.metaKey) return;
  if (e.ctrlKey && e.shiftKey && (e.key === 'C' || e.key === 'c' || e.key === 'V' || e.key === 'v')) return;
  if (e.ctrlKey && !e.altKey && e.key.length === 1) {
    e.preventDefault();
    writeSession(String.fromCharCode(e.key.toLowerCase().charCodeAt(0) - 96), true);
    return;
  }
  const keys = { Enter: '\n', Backspace: '\x7f', Tab: '\t', ArrowUp: '\x1b[A', ArrowDown: '\x1b[B', ArrowRight: '\x1b[C', ArrowLeft: '\x1b[D', Home: '\x1b[H', End: '\x1b[F', Delete: '\x1b[3~', Escape: '\x1b', PageUp: '\x1b[5~', PageDown: '\x1b[6~' };
  if (keys[e.key]) { e.preventDefault(); writeSession(keys[e.key], true); }
  else if (e.key.length === 1 && !e.altKey) { e.preventDefault(); writeSession(e.key, true); }
}
function bindPtySurface(element) {
  if (!element || element._ptyBound) return;
  element._ptyBound = true;
  element.tabIndex = 0;
  element.setAttribute('role', 'application');
  element.setAttribute('aria-label', 'VORTEX Linux PTY');
  element.addEventListener('click', () => {
    const session = activeSession();
    if (!session || session.status !== 'running') openSession();
    else element.focus({ preventScroll: true });
  });
  element.addEventListener('keydown', ptyKey);
  element.addEventListener('paste', (e) => {
    e.preventDefault();
    const text = ((e.clipboardData || window.clipboardData).getData('text') || '').replace(/\x00/g, '').slice(0, 65536);
    if (text) writeSession(text, true);
  });
}
function activeSession() { return state.sessions.find(session => session.id === state.activeSessionId) || null; }
function sessionOutput(sessionId) { return Array.from(document.querySelectorAll('[data-session-output]')).find(element => element.dataset.sessionOutput === sessionId) || null; }
function appendAnsi(element, data) {
  if (!element._vortexTerminal) element._vortexTerminal = new window.VortexTerminal(100, 30, 5000);
  element._vortexTerminal.feed(data);
  if (element._renderScheduled) return;
  element._renderScheduled = true;
  const flush = () => {
    element._renderScheduled = false;
    if (element._vortexTerminal) element._vortexTerminal.render(element);
  };
  if (typeof requestAnimationFrame === 'function') requestAnimationFrame(flush);
  else setTimeout(flush, 0);
}
function ensureSessionPane(sessionId) {
  const host = $('terminal-panes');
  let output = sessionOutput(sessionId);
  if (output) return output;
  const old = $('terminal-output');
  if (old && !old.dataset.sessionOutput && old.parentElement === host) host.innerHTML = '';
  output = document.createElement('pre');
  output.className = 'terminal-body'; output.dataset.sessionOutput = sessionId;
  output.setAttribute('role', 'application'); output.setAttribute('aria-live', 'polite');
  output.textContent = `[PTY ${sessionId.slice(0, 8)}] attaching to this host…\n`;
  bindPtySurface(output);
  host.appendChild(output);
  return output;
}
function renderSessionTabs() {
  const host = $('terminal-tabs');
  const controls = '<button class="terminal-button" id="new-session">＋ NEW</button><button class="terminal-button" id="split-session">SPLIT VIEW</button>';
  host.innerHTML = state.sessions.length ? state.sessions.map((session, index) => `<button class="terminal-tab-button ${session.id === state.activeSessionId ? 'active':''}" data-session-tab="${esc(session.id)}"><span class="tab-led ${session.status === 'running' ? 'live':''}"></span>${esc(session.name || `session ${index + 1}`)} <small>${esc(session.status)}</small></button>`).join('') + controls : `<span class="tab-empty">NO PTY SESSIONS</span>${controls}`;
  host.querySelectorAll('[data-session-tab]').forEach(button => button.addEventListener('click', () => selectSession(button.dataset.sessionTab)));
  $('new-session')?.addEventListener('click', openSession);
  $('split-session')?.addEventListener('click', splitSession);
}
function renderSessionPanes() {
  const host = $('terminal-panes');
  if (!state.sessions.length) { host.style.gridTemplateColumns = '1fr'; return; }
  state.paneIds.forEach(ensureSessionPane);
  Array.from(host.querySelectorAll('[data-session-output]')).forEach(output => { output.hidden = !state.paneIds.includes(output.dataset.sessionOutput); });
  host.style.gridTemplateColumns = state.paneIds.length > 1 ? 'repeat(2,minmax(0,1fr))' : '1fr';
}
function renderSessionState() {
  const session = activeSession();
  const running = session?.status === 'running';
  $('session-status').textContent = session ? statusLabel(session.status) : 'NO PTY SESSION';
  $('session-status').className = `session-status ${running ? 'live' : session ? 'ended' : ''}`;
  $('open-session').hidden = running;
  $('kill-session').hidden = !running;
  $('terminal-input').disabled = !running;
  $('terminal-input').placeholder = running ? 'Or type here — keys also go to the PTY surface' : 'Click the black pane or OPEN LOCAL SHELL';
  $('terminal-hint').textContent = running ? 'CLICK PANE · TYPE · PASTE · CTRL-C' : 'OPEN A REAL LINUX PTY';
  $('terminal-cwd').textContent = session?.cwd || state.doctor?.cwd || '—';
}
function selectSession(sessionId) {
  if (!state.sessions.some(session => session.id === sessionId)) return;
  state.activeSessionId = sessionId; state.session = activeSession();
  if (!state.paneIds.includes(sessionId)) { if (state.paneIds.length >= 2) state.paneIds.shift(); state.paneIds.push(sessionId); }
  renderSessionTabs(); renderSessionPanes(); renderSessionState();
  if (activeSession()?.status === 'running') pollSessions();
  focusPtySurface();
}
async function loadSessions() {
  try {
    const data = await api('/api/sessions');
    state.sessions = data.sessions || [];
    if (!state.activeSessionId || !state.sessions.some(session => session.id === state.activeSessionId)) state.activeSessionId = state.sessions.find(session => session.status === 'running')?.id || state.sessions[0]?.id || null;
    state.session = activeSession();
    if (state.activeSessionId && !state.paneIds.includes(state.activeSessionId)) state.paneIds = [state.activeSessionId];
    renderSessionTabs(); renderSessionPanes(); renderSessionState();
    if (state.sessions.some(session => session.status === 'running')) pollSessions();
  } catch (e) { toast(e.message, true); }
}
function applySessionPayload(sessionId, data) {
  const output = ensureSessionPane(sessionId);
  (data.events || []).forEach(event => {
    const seq = Number(event.seq);
    if (!Number.isSafeInteger(seq) || seq <= (state.sessionSeqs[sessionId] || 0)) return;
    appendAnsi(output, event.data);
    state.sessionSeqs[sessionId] = seq;
  });
  const index = state.sessions.findIndex(item => item.id === sessionId);
  if (index >= 0 && data.session) state.sessions[index] = data.session;
}

function streamSession(sessionId) {
  if (!window.EventSource || state.sessionStreams[sessionId] || Date.now() < (state.sessionStreamRetryAt[sessionId] || 0)) return false;
  try {
    const since = state.sessionSeqs[sessionId] || 0;
    const es = new EventSource(`/api/sessions/${encodeURIComponent(sessionId)}/stream?since=${since}`);
    state.sessionStreams[sessionId] = es;
    es.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        const before = state.session?.status;
        applySessionPayload(sessionId, data);
        state.session = activeSession();
        renderSessionState();
        const status = data.session?.status;
        const changed = before !== status;
        if (changed) { renderSessionTabs(); renderSessionPanes(); }
        if (!data.session || !['starting', 'running'].includes(status)) { es.close(); delete state.sessionStreams[sessionId]; delete state.sessionStreamRetryAt[sessionId]; }
      } catch (_) { /* keep listening */ }
    };
    es.onerror = () => {
      es.close();
      delete state.sessionStreams[sessionId];
      state.sessionStreamRetryAt[sessionId] = Date.now() + 2000;
    };
    return true;
  } catch (_) { return false; }
}

async function pollSessions() {
  const running = state.sessions.filter(session => session.status === 'running');
  running.forEach(session => streamSession(session.id));
  if (state.sessionTimer) return;
  const tick = async () => {
    state.sessionTimer = null;
    state.sessions.filter(session => session.status === 'running').forEach(session => streamSession(session.id));
    const live = state.sessions.filter(session => session.status === 'running' && !state.sessionStreams[session.id]);
    let dirty = false;
    for (const session of live) {
      try {
        const data = await api(`/api/sessions/${encodeURIComponent(session.id)}/events?since=${state.sessionSeqs[session.id] || 0}`);
        const before = session.status;
        applySessionPayload(session.id, data);
        if (before !== session.status || (data.events || []).length) dirty = true;
      } catch (e) { toast(e.message, true); }
    }
    state.session = activeSession();
    renderSessionState();
    if (dirty) { renderSessionTabs(); renderSessionPanes(); }
    if (state.sessions.some(session => session.status === 'running')) state.sessionTimer = setTimeout(tick, 500);
  };
  await tick();
}
function adoptSession(session) {
  const index = state.sessions.findIndex(item => item.id === session.id);
  if (index >= 0) state.sessions[index] = session;
  else state.sessions.push(session);
  state.activeSessionId = session.id; state.session = session; state.sessionSeqs[session.id] = 0;
  if (state.paneIds.length >= 2) state.paneIds.shift();
  if (!state.paneIds.includes(session.id)) state.paneIds.push(session.id);
  renderSessionTabs(); renderSessionPanes(); renderSessionState(); pollSessions(); focusPtySurface();
}
async function openSession() {
  $('open-session').disabled = true;
  try {
    const size = terminalMetrics();
    const data = await api('/api/sessions', {method:'POST', body:{name:`linux pty ${state.sessions.length + 1}`, cwd:state.doctor?.cwd || undefined, cols:size.cols, rows:size.rows}});
    adoptSession(data.session);
    toast('Real Linux PTY opened on this host. Type in the black pane.');
  } catch (e) { toast(e.message, true); }
  finally { $('open-session').disabled = false; renderSessionState(); }
}
async function splitSession() {
  if (!state.sessions.length) return openSession();
  if (state.paneIds.length < 2) {
    const next = state.sessions.find(session => session.id !== state.activeSessionId && session.status === 'running');
    if (next) { state.paneIds.push(next.id); selectSession(next.id); return; }
    return openSession();
  }
  toast('Split view already has two panes.');
}
async function writeSession(data, quiet = false) {
  const session = activeSession();
  if (!session || session.status !== 'running') {
    if (!quiet) toast('Open a local PTY session first.', true);
    return;
  }
  try { await api(`/api/sessions/${encodeURIComponent(session.id)}/input`, {method:'POST', body:{data}}); }
  catch (e) { toast(e.message, true); }
}
async function killSession() {
  const session = activeSession();
  if (!session) return;
  try { await api(`/api/sessions/${encodeURIComponent(session.id)}/kill`, {method:'POST', body:{}}); toast('PTY group cancellation requested.'); }
  catch (e) { toast(e.message, true); }
}
let resizeTimer = null;
function resizeSession() {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(resizeSessionNow, 160);
}
async function resizeSessionNow() {
  const session = activeSession();
  if (!session || session.status !== 'running') return;
  try { const cols = Math.max(40, Math.min(220, Math.floor(innerWidth / 8))); await api(`/api/sessions/${encodeURIComponent(session.id)}/resize`, {method:'POST', body:{cols, rows:30}}); const output = sessionOutput(session.id); if (output?._vortexTerminal) { output._vortexTerminal.resize(cols, 30); output._vortexTerminal.render(output); } }
  catch (_) { /* resize is best effort while a PTY is closing */ }
}

function bindCapabilityForm() {
  const form = $('capability-form');
  if (!form) return;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const input = $('capability-input');
    const value = String(input?.value || '').trim();
    if (!value || value.length > 256 || /[\x00-\x1f\x7f]/.test(value)) {
      showCapabilityDialog('Enter a valid sidecar capability (maximum 256 characters).');
      return;
    }
    browserCapability = value;
    browserSessionPromise = null;
    try { sessionStorage.setItem('vortex-capability', value); } catch (_) { /* continue in memory */ }
    try {
      await establishBrowserSession();
      location.reload();
    } catch (_) { if (input) input.value = ''; }
  });
}
function openSurfaceWindow(id) {
  if (window.VortexWindows?.showSurface) window.VortexWindows.showSurface(id);
  else { const el = $(id); if (el) el.hidden = false; }
}
function init() {
  bindCapabilityForm();
  document.querySelectorAll('.nav-item').forEach(item => { if (!item.title) item.title = item.textContent.trim(); });
  setView(state.currentView);
  document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.view)));
  document.querySelectorAll('[data-view-target]').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.viewTarget)));
  document.querySelectorAll('[data-prompt]').forEach(b=>b.addEventListener('click',()=>{ $('request-input').value=b.dataset.prompt; window.makePlan(b.dataset.prompt); }));
  $('plan-button').addEventListener('click',()=>window.makePlan($('request-input').value));
  $('request-input').addEventListener('keydown',e=>{if(e.key==='Enter')window.makePlan(e.target.value)});
  $('terminal-input').addEventListener('keydown', ptyKey);
  bindPtySurface($('terminal-output'));
  $('open-session').addEventListener('click',openSession);
  $('kill-session').addEventListener('click',killSession);
  addEventListener('resize',resizeSession);
  renderSessionState();
  $('refresh-doctor').addEventListener('click',()=>loadDoctor(true));
  $('refresh-tools').addEventListener('click',()=>loadTools(true));
  $('rescan-host-tools')?.addEventListener('click',()=>loadHostTools(true));
  $('download-apk')?.addEventListener('click', downloadApk);
  $('download-apk-settings')?.addEventListener('click', downloadApk);
  $('download-deb')?.addEventListener('click', downloadDeb);
  $('download-deb-settings')?.addEventListener('click', downloadDeb);
  $('plain-theme')?.addEventListener('click',()=>{state.plain=!state.plain;document.body.classList.toggle('plain-mode',state.plain);toast(state.plain?'Plain high-contrast palette enabled.':'Vortex palette enabled.');});
  $('new-engagement').addEventListener('click',()=>{$('engagement-form').hidden=false;setView('engagements')});
  $('close-engagement').addEventListener('click',()=>{$('engagement-form').hidden=true});
  $('save-engagement').addEventListener('click',createEngagement);
  $('verify-audit').addEventListener('click',verifyAudit);
  $('open-ai-ops')?.addEventListener('click', () => { openSurfaceWindow('ai-ops-window'); if (typeof window.loadAiOps === 'function') window.loadAiOps(); });
  $('open-system')?.addEventListener('click', () => { openSurfaceWindow('system-window'); if (typeof window.refreshHud === 'function') window.refreshHud(); loadDoctor(true); });
  $('open-task-state')?.addEventListener('click', () => openSurfaceWindow('task-window'));
  $('refresh-all')?.addEventListener('click', refreshAll);
  loadDoctor(); loadTools(); loadEngagements(); loadHistory();
}
addEventListener('DOMContentLoaded', init);
