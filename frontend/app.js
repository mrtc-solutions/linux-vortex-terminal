/* Vortex renderer. In Electron all requests go through the typed preload bridge;
   the relative fetch fallback keeps the local preview useful without Electron. */
const state = { currentView: 'overview', plan: null, doctor: null, tools: [], history: [], engagements: [], activeEngagementId: null, session: null, sessionSeq: 0, sessionTimer: null, matrix: 'medium', plain: false };
const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[c]));
const fmtDate = (value) => { if (!value) return '—'; try { return new Intl.DateTimeFormat(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}).format(new Date(value)); } catch { return value; } };
const api = async (path, options = {}) => {
  if (window.vortexApi?.request) return window.vortexApi.request(path, options);
  const response = await fetch(path, { headers: {'Content-Type':'application/json', ...(options.headers || {})}, ...options, body: options.body && typeof options.body !== 'string' ? JSON.stringify(options.body) : options.body });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error?.message || `Request failed (${response.status})`);
  return payload;
};
function toast(message, bad = false) { const el = $('toast'); el.textContent = message; el.style.borderColor = bad ? 'var(--red)' : 'var(--cyan)'; el.classList.add('show'); clearTimeout(window.toastTimer); window.toastTimer = setTimeout(() => el.classList.remove('show'), 4200); }
function setView(view) { state.currentView = view; document.querySelectorAll('.view').forEach(el => el.classList.toggle('active', el.id === `view-${view}`)); document.querySelectorAll('.nav-item').forEach(el => el.classList.toggle('active', el.dataset.view === view)); $('view-title').textContent = view.toUpperCase(); if (view === 'activity') loadHistory(); if (view === 'terminal') loadSessions(); if (view === 'tools') loadTools(); if (view === 'engagements') loadEngagements(); if (view === 'reports') loadHistory().then(renderReports); }
function statusClass(status) { return ['succeeded','success'].includes(status) ? 'badge-green' : ['failed','timed_out','interrupted'].includes(status) ? 'badge-red' : status === 'planned' ? 'badge-amber' : 'badge-muted'; }
function statusLabel(status) { return ({succeeded:'VERIFIED OK',failed:'FAILED',timed_out:'TIMED OUT',interrupted:'INTERRUPTED',unavailable:'TOOL MISSING',running:'RUNNING',started:'STARTED',planned:'CONFIRM REQUIRED',clarified:'PLAN ONLY',rejected:'BLOCKED',unknown_after_crash:'UNKNOWN AFTER CRASH'}[status] || String(status || 'STANDBY').toUpperCase()); }
async function loadDoctor() { try { const data = await api('/api/doctor'); state.doctor = data.doctor; renderDoctor(); } catch (e) { $('side-context').textContent = 'backend offline'; toast(e.message, true); } }
function renderDoctor() { const d = state.doctor; if (!d) return; $('side-context').textContent = `${d.distribution.pretty_name || d.distribution.id} · ${d.architecture}`; $('terminal-cwd').textContent = d.cwd; $('context-content').innerHTML = [
  ['DISTRIBUTION', d.distribution.pretty_name || d.distribution.id], ['SUPPORT TIER', d.support_tier], ['KERNEL', d.kernel], ['PID 1 / SYSTEMD', `${d.pid1 || 'unknown'} / ${d.systemd ? 'available' : 'unavailable'}`], ['CONTEXT', [d.container ? 'container' : 'host', d.ssh ? 'SSH' : 'local', d.tmux ? 'tmux' : 'direct'].join(' · ')], ['PRIVILEGE', d.root ? 'UID 0 — guarded' : `UID ${d.uid}`], ['MODEL', 'disabled by default']
].map(([a,b]) => `<div class="context-row"><label>${esc(a)}</label><span class="${String(b).includes('available') || String(b).includes('local') ? 'ok':''}">${esc(b)}</span></div>`).join(''); }
async function loadTools() { try { const data = await api('/api/tools'); state.tools = data.tools; renderTools(); } catch(e) { toast(e.message, true); } }
function renderTools() { $('tool-grid').innerHTML = state.tools.map(t => `<article class="tool-card ${esc(t.state)}"><span class="badge ${t.state === 'installed' ? 'badge-green' : t.state === 'blocked' ? 'badge-red' : 'badge-muted'}">${esc(t.state.replace('-', ' ').toUpperCase())}</span><h3>${esc(t.name)}</h3><div class="tool-family">${esc(t.family)}</div><p>${esc(t.role)}<br><span class="tool-path">${esc(t.path || 'No executable found')}</span><br>${t.version ? esc(t.version) : 'Version unavailable'}</p></article>`).join(''); }
async function loadEngagements() { try { const data = await api('/api/engagements'); state.engagements = data.engagements; if (!state.activeEngagementId && state.engagements[0]) state.activeEngagementId = state.engagements[0].id; renderEngagements(); } catch(e) { toast(e.message, true); } }
function renderEngagements() { const el = $('engagement-list'); if (!state.engagements.length) { el.innerHTML = `<div class="empty-state panel"><div class="empty-icon">◎</div><h3>No active engagements</h3><p>Active tools such as nmap stay unavailable until a scope and expiry are declared.</p></div>`; return; } el.innerHTML = state.engagements.map(e => `<article class="engagement-card"><header><div><h3>${esc(e.name)}</h3><p>${esc(e.authorization)}</p></div><span class="badge ${e.status === 'active' ? 'badge-green':'badge-muted'}">${esc(e.status.toUpperCase())}</span></header><div>${e.targets.map(t => `<span class="target-pill">${esc(t)}</span>`).join('')}</div><div class="engagement-details"><span>ID ${esc(e.id.slice(0,12))}…</span><span>EXPIRES ${esc(fmtDate(e.expires_at))}</span><span>${e.classes.map(esc).join(' · ')}</span></div></article>`).join(''); }
async function loadHistory() { try { const data = await api('/api/history'); state.history = data.history; renderActivity(); return state.history; } catch(e) { toast(e.message, true); return []; } }
function operationTitle(op) { const command = op.commands?.[0]?.display || 'No command executed'; return command.length > 67 ? command.slice(0,67) + '…' : command; }
function activityMarkup(op) { const s = op.status || 'unknown'; return `<article class="activity-item"><span class="activity-icon ${s === 'succeeded' ? '' : s === 'running' ? 'running':'failed'}"></span><div><div class="activity-title">${esc(statusLabel(s))} <span style="color:var(--dim)">· ${esc(fmtDate(op.ended_at || op.started_at))}</span></div><div class="activity-command">${esc(operationTitle(op))}</div></div><div class="activity-meta"><div class="activity-status ${s !== 'succeeded' ? s === 'running' ? 'running':'failed':''}">${esc(statusLabel(s))}</div><div>${op.commands?.length || 0} command${(op.commands?.length || 0) === 1 ? '':'s'}</div></div></article>`; }
function renderActivity() { const html = state.history.length ? state.history.map(activityMarkup).join('') : '<div class="empty-inline">No operations recorded. Plans remain private until you approve them.</div>'; $('recent-activity').innerHTML = html; $('activity-full').innerHTML = html; }
function renderReports() { const el = $('report-grid'); if (!state.history.length) { el.innerHTML = `<div class="empty-state panel"><div class="empty-icon">▤</div><h3>Reports appear after execution</h3><p>Run an approved plan to create a local analysis record.</p></div>`; return; } el.innerHTML = state.history.map(op => `<article class="report-card"><div class="panel-kicker">LOCAL REPORT</div><h3>${esc(statusLabel(op.status))}</h3><p>${esc(fmtDate(op.started_at))}<br>${esc(operationTitle(op))}</p><p>${op.artifacts?.length || 0} parsed artifact${(op.artifacts?.length || 0) === 1 ? '' : 's'} · raw evidence is not retained by default</p><code>evidence ${esc((op.output_digest || 'not-available').slice(0,24))}…</code></article>`).join(''); }
function renderPlan(plan) { state.plan = plan; const badge = $('plan-badge'); badge.textContent = statusLabel(plan.status); badge.className = `badge ${statusClass(plan.status)}`; let commands = plan.commands?.length ? plan.commands.map((c, i) => `<div class="command-spec"><code>${esc(c.display)}</code><div class="spec-meta"><span>${esc(c.required_tool)}: ${esc(c.tool_state_at_plan)}</span><span>RISK: ${esc(c.risk.toUpperCase())}</span><span>NETWORK: ${esc(c.network_class)}</span><span>TIMEOUT: ${esc(c.timeout_seconds)}s</span><span>PRIVILEGE: ${esc(c.privilege || 'user')}</span></div><p style="color:var(--muted);font-size:10px;line-height:1.5;margin:9px 0 0">${esc(c.explanation)}</p></div>`).join('') : '<div class="command-spec"><code>NO EXECUTION</code><p style="color:var(--dim);font-size:10px;margin:7px 0 0">This request produces explanation or clarification only.</p></div>';
 const notes = (plan.notes || []).map(n => `<li>${esc(n)}</li>`).join(''); const worker = (plan.workers || []).map(w => `<span>${esc(w.id)}: <strong>${esc(w.state)}</strong></span>`).join(' · ');
 $('plan-content').className = 'plan-card'; $('plan-content').innerHTML = `<div class="plan-summary"><div class="plan-objective"><span>OBJECTIVE / ${esc(plan.kind.replace('_',' '))}</span>${esc(plan.request)}</div><span class="badge ${statusClass(plan.status)}">${esc(statusLabel(plan.status))}</span></div><ul class="plan-notes">${notes}</ul>${commands}<div class="worker-row">WORKERS · ${worker}</div>${plan.approval_required && plan.status === 'planned' ? `<div class="approval"><small>⌁ ${esc(plan.approval_phrase)}</small><button class="approve-button" id="approve-plan">APPROVE &amp; EXECUTE</button></div>` : ''}`;
 $('approve-plan')?.addEventListener('click', approvePlan);
}
async function makePlan(request) { if (!request.trim()) return; setView('overview'); $('plan-button').disabled = true; $('plan-button').textContent = 'INSPECTING…'; try { const payload = {request, cwd: state.doctor?.cwd || undefined}; if (state.activeEngagementId) payload.engagement_id = state.activeEngagementId; const data = await api('/api/plan', {method:'POST', body:payload}); renderPlan(data.plan); toast(data.plan.status === 'planned' ? 'Typed plan ready — review before execution.' : statusLabel(data.plan.status), data.plan.status === 'rejected'); } catch(e) { toast(e.message, true); } finally { $('plan-button').disabled = false; $('plan-button').innerHTML = '<span class="spark">✦</span> PLAN REQUEST'; } }
async function approvePlan() { if (!state.plan) return; const button = $('approve-plan'); button.disabled = true; button.textContent = 'STARTING…'; try { const data = await api('/api/execute', {method:'POST', body:{plan_id:state.plan.id, approval_token:state.plan.approval_token, confirm:true}}); const op = data.operation; renderPlan({...state.plan, status:'started'}); toast('Operation started. Streaming real output from the local sidecar.'); await watchOperation(op.id); } catch(e) { button.disabled = false; button.textContent = 'APPROVE & EXECUTE'; toast(e.message, true); } }
async function watchOperation(id) { for (let i=0; i<120; i++) { await new Promise(r => setTimeout(r, 350)); try { const data = await api(`/api/operations/${encodeURIComponent(id)}`); const op = data.operation; if (!op) continue; if (!['started','running'].includes(op.status)) { renderAnalysis(op); await loadHistory(); return; } } catch(e) { toast(e.message, true); return; } } toast('Operation is still running; activity can be refreshed.', true); }
function renderAnalysis(op) { const a = op.analysis || {}; const timeline = (a.commands || op.commands || []).map(c => `<div class="timeline-command"><code>${esc(c.command || c.display || c.argv?.join(' '))}</code><small>${esc(statusLabel(c.status))} · ${esc(c.summary || `${c.observed_lines || 0} observed line(s)`)}</small></div>`).join(''); $('plan-badge').textContent = esc(a.lifecycle || statusLabel(op.status)); $('plan-badge').className = `badge ${statusClass(op.status)}`; $('plan-content').className = 'plan-card'; $('plan-content').innerHTML = `<div class="analysis-block"><h3>${esc(a.lifecycle || statusLabel(op.status))} · verified outcome</h3><p>${esc(a.fact || 'Observed execution record.')}</p></div><div class="analysis-block"><h3>Command timeline</h3>${timeline || '<p>No command was run.</p>'}</div><div class="analysis-block"><h3>Interpretation boundaries</h3><p><b style="color:var(--text)">Fact:</b> ${esc(a.fact || 'Observed output only.')}<br><b style="color:var(--text)">Inference:</b> ${esc(a.inference || '')}<br><b style="color:var(--text)">Unknown:</b> ${esc(a.unknown || '')}</p></div><div class="analysis-block"><h3>Adapter facts</h3><pre class="analysis-json">${esc(JSON.stringify(a.adapter_facts || {}, null, 2))}</pre></div><div class="worker-row">WORKER PARTICIPATION · ${(a.workers || []).map(w => `${esc(w.id)}: <strong>${esc(w.state)}</strong>`).join(' · ')}</div>`; }
async function createEngagement() { const name = $('eng-name').value.trim(), authorization = $('eng-auth').value.trim(), target = $('eng-target').value.trim(); if (!name || !authorization || !target) return toast('Name, authorization reference, and target are required.', true); try { const data = await api('/api/engagements',{method:'POST',body:{name,authorization,targets:[target],classes:['reconnaissance','defensive-analysis']}}); state.engagements.unshift(data.engagement); state.activeEngagementId = data.engagement.id; renderEngagements(); $('engagement-form').hidden=true; toast('Engagement scope created. Targets are rechecked at execution.'); } catch(e) { toast(e.message,true); } }
async function verifyAudit() { try { const data = await api('/api/audit/verify'); const el = $('audit-result'); el.className = `audit-strip ${data.audit.valid ? 'valid':'invalid'}`; el.innerHTML = `<span class="status-dot"></span> ${data.audit.valid ? `AUDIT CHAIN VERIFIED · ${data.audit.checked} event(s)` : `AUDIT CHAIN INVALID · ${esc(data.audit.error)}`}`; } catch(e) { toast(e.message,true); } }
function setupMatrix() { const canvas = $('matrix'), ctx = canvas.getContext('2d'); let columns = [], frame = 0; function resize(){canvas.width=innerWidth;canvas.height=innerHeight;columns=Array(Math.ceil(canvas.width/17)).fill(0).map(()=>Math.random()*-40)} function tick(){ if (state.matrix === 'off' || state.plain || matchMedia('(prefers-reduced-motion: reduce)').matches) { ctx.clearRect(0,0,canvas.width,canvas.height); return; } if ((frame++ % (state.matrix === 'high' ? 1 : state.matrix === 'low' ? 4 : 2)) !== 0) return; ctx.fillStyle='rgba(10,10,12,.09)';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.font='12px monospace';ctx.fillStyle='rgba(0,212,170,.54)';columns.forEach((y,i)=>{ctx.fillText(Math.random()>.5?'1':'0',i*17,y*17);if(y*17>canvas.height && Math.random()>.975)columns[i]=0;columns[i]++});} resize();addEventListener('resize',resize);(function loop(){tick();requestAnimationFrame(loop)})(); }
function renderSessionState() {
  const session = state.session;
  const running = session?.status === 'running';
  $('session-status').textContent = session ? statusLabel(session.status) : 'NO PTY SESSION';
  $('session-status').className = `session-status ${running ? 'live' : session ? 'ended' : ''}`;
  $('open-session').hidden = running;
  $('kill-session').hidden = !running;
  $('terminal-input').disabled = !running;
  $('terminal-input').placeholder = running ? 'Type into the active local PTY…' : 'Open a shell to type into the real PTY…';
  $('terminal-hint').textContent = running ? 'ENTER TO SEND · CTRL-C INTERRUPTS' : 'OPEN SESSION FIRST';
}
function appendTerminal(data) {
  if (!data) return;
  const output = $('terminal-output');
  output.textContent += data;
  output.scrollTop = output.scrollHeight;
}
async function loadSessions() {
  try {
    const data = await api('/api/sessions');
    if (!state.session) {
      const running = data.sessions.find(s => s.status === 'running');
      if (running) { state.session = running; state.sessionSeq = 0; $('terminal-output').textContent = ''; }
    }
    renderSessionState();
    if (state.session?.status === 'running') pollSession();
  } catch (e) { toast(e.message, true); }
}
async function pollSession() {
  if (state.sessionTimer || !state.session) return;
  const tick = async () => {
    state.sessionTimer = null;
    if (!state.session) return;
    try {
      const data = await api(`/api/sessions/${encodeURIComponent(state.session.id)}/events?since=${state.sessionSeq}`);
      (data.events || []).forEach(event => { appendTerminal(event.data); state.sessionSeq = Math.max(state.sessionSeq, event.seq); });
      if (data.session) state.session = data.session;
      renderSessionState();
      if (state.session?.status === 'running') state.sessionTimer = setTimeout(tick, 220);
    } catch (e) { toast(e.message, true); }
  };
  await tick();
}
async function openSession() {
  $('open-session').disabled = true;
  try {
    const data = await api('/api/sessions', {method:'POST', body:{name:'local shell', cwd:state.doctor?.cwd || undefined, cols:100, rows:30}});
    state.session = data.session; state.sessionSeq = 0; $('terminal-output').textContent = '';
    renderSessionState(); pollSession(); $('terminal-input').focus();
    toast('Real local PTY opened. Input stays inside the Python sidecar.');
  } catch (e) { toast(e.message, true); }
  finally { $('open-session').disabled = false; renderSessionState(); }
}
async function writeSession(data) {
  if (!state.session || state.session.status !== 'running') return toast('Open a local PTY session first.', true);
  try { await api(`/api/sessions/${encodeURIComponent(state.session.id)}/input`, {method:'POST', body:{data}}); }
  catch (e) { toast(e.message, true); }
}
async function killSession() {
  if (!state.session) return;
  try { await api(`/api/sessions/${encodeURIComponent(state.session.id)}/kill`, {method:'POST', body:{}}); toast('PTY group cancellation requested.'); }
  catch (e) { toast(e.message, true); }
}
async function resizeSession() {
  if (!state.session || state.session.status !== 'running') return;
  try { await api(`/api/sessions/${encodeURIComponent(state.session.id)}/resize`, {method:'POST', body:{cols:Math.max(40, Math.min(220, Math.floor(innerWidth / 8))), rows:30}}); }
  catch (_) { /* resize is best effort while a PTY is closing */ }
}

function init() { setupMatrix(); document.querySelectorAll('[data-view]').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.view))); document.querySelectorAll('[data-view-target]').forEach(b=>b.addEventListener('click',()=>setView(b.dataset.viewTarget))); document.querySelectorAll('[data-prompt]').forEach(b=>b.addEventListener('click',()=>{ $('request-input').value=b.dataset.prompt; makePlan(b.dataset.prompt); })); $('plan-button').addEventListener('click',()=>makePlan($('request-input').value)); $('request-input').addEventListener('keydown',e=>{if(e.key==='Enter')makePlan(e.target.value)}); $('terminal-input').addEventListener('keydown',e=>{if(e.ctrlKey && e.key.toLowerCase()==='c'){e.preventDefault();writeSession('\u0003');return;} if(e.key==='Enter'){e.preventDefault();const value=e.target.value;e.target.value='';writeSession(value+'\n'); }}); $('open-session').addEventListener('click',openSession); $('kill-session').addEventListener('click',killSession); addEventListener('resize',resizeSession); renderSessionState(); $('refresh-doctor').addEventListener('click',loadDoctor); $('refresh-tools').addEventListener('click',loadTools); $('theme-toggle').addEventListener('click',()=>{state.matrix=state.matrix==='off'?'medium':'off';toast(state.matrix==='off'?'Matrix rain paused.':'Matrix rain resumed.');}); $('matrix-setting').addEventListener('change',e=>{state.matrix=e.target.value;toast(`Matrix intensity: ${e.target.value}`)}); $('plain-theme').addEventListener('click',()=>{state.plain=!state.plain;document.body.classList.toggle('plain-mode',state.plain);toast(state.plain?'Plain high-contrast palette enabled.':'Vortex palette enabled.');}); $('new-engagement').addEventListener('click',()=>{$('engagement-form').hidden=false;setView('engagements')}); $('close-engagement').addEventListener('click',()=>{$('engagement-form').hidden=true}); $('save-engagement').addEventListener('click',createEngagement); $('verify-audit').addEventListener('click',verifyAudit); loadDoctor(); loadTools(); loadEngagements(); loadHistory(); }
addEventListener('DOMContentLoaded', init);
