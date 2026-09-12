'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const read = (p) => fs.readFileSync(path.join(__dirname, '..', p), 'utf8');
const index = read('frontend/index.html');
const workspace = read('frontend/workspace.js');
const app = read('frontend/app.js');
const models = read('frontend/models.js');
const styles = read('frontend/styles.css');
const backend = read('backend/vortex_backend.py');
const probeCache = read('backend/probe_cache.py');

// First-run surface must never auto-cover the chat bar unless setup is ready,
// and must always be dismissible.
assert.ok(index.includes('id="first-run"'), 'first-run surface exists');
assert.ok(index.includes('id="skip-setup"'), 'SKIP button exists');
assert.ok(workspace.includes('if (!setup.ready) return;'), 'not-ready setup never opens the modal');
assert.ok(workspace.includes('hideFirstRun()'), 'first-run close helper is wired');
assert.ok(workspace.includes('finally { hideFirstRun(); }') || workspace.includes('finally { hideFirstRun() }'), 'CONTINUE closes surface in finally');

// Keyboard and assistive-technology basics: bypass navigation, named static
// controls, current-view state, assertive errors, and readable secondary text.
assert.ok(index.includes('class="skip-link" href="#main-content"') && index.includes('id="main-content" tabindex="-1"'), 'keyboard users can bypass repeated navigation');
for (const label of ['Terminal input', 'Search conversations', 'Execution policy', 'Privacy mode', 'Developer mode', 'Offline mode', 'Lab mode', 'Host tool access']) {
  assert.ok(index.includes(`aria-label="${label}"`), `${label} control is named`);
}
assert.ok(index.includes('aria-label="Close engagement form"'), 'symbol-only close control has an accessible name');
assert.ok(app.includes("setAttribute('aria-current', 'page')"), 'active SPA navigation exposes aria-current');
assert.ok(app.includes("setAttribute('aria-hidden', String(!active))"), 'inactive SPA views expose their hidden state');
assert.ok(app.includes("bad ? 'alert' : 'status'") && app.includes("bad ? 'assertive' : 'polite'"), 'error toasts are announced assertively');
// The visual navigation redesign groups the existing destinations by intent,
// but it must never remove or duplicate a route/control while doing so.
for (const zone of ['OPERATIONS', 'INVESTIGATE', 'INTELLIGENCE', 'CONTROL']) {
  assert.ok(index.includes(`>${zone}</div>`), `${zone} navigation zone is labeled`);
}
const viewButtons = [...index.matchAll(/<button class="nav-item[^>]*data-view="([^"]+)"/g)].map(match => match[1]);
assert.strictEqual(new Set(viewButtons).size, viewButtons.length, 'each routed navigation destination appears exactly once');
for (const view of ['overview', 'terminal', 'tasks', 'engagements', 'conversations', 'reports', 'activity', 'assets', 'agents', 'tools', 'memory', 'learning', 'models', 'system', 'settings']) {
  assert.ok(viewButtons.includes(view), `${view} remains reachable from the reorganized navigation`);
}
assert.ok(styles.includes('body.plain-mode::before, body.plain-mode::after { display: none; }'), 'plain theme disables decorative backgrounds');
assert.ok(styles.includes('body::before, body::after { display: none; }'), 'reduced motion disables decorative backgrounds');
const hexLuminance = value => {
  const channels = value.match(/[0-9a-f]{2}/gi).map(channel => parseInt(channel, 16) / 255)
    .map(channel => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
};
const contrast = (left, right) => {
  const values = [hexLuminance(left), hexLuminance(right)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
};
const dimColor = styles.match(/--dim:\s*(#[0-9a-f]{6})/i)[1];
const lightestSurface = styles.match(/--surface-3:\s*(#[0-9a-f]{6})/i)[1];
assert.ok(contrast(dimColor, lightestSurface) >= 4.5, 'small secondary text meets WCAG AA contrast on the lightest surface');

// Chat bar must be focusable/labeled and submit must local-echo, reset, and
// re-enable the SEND button in a finally block.
assert.ok(index.includes('id="request-input"') && index.includes('aria-label="Ask VORTEX"'), 'request input is labeled');
assert.ok(index.includes('id="plan-button"') && index.includes('aria-label="Send"'), 'send button is labeled');
assert.ok(workspace.includes('local-echo'), 'chat submit local-echoes the user message');
assert.ok(workspace.includes("api('/api/workspace/turn'"), 'chat submit uses the workspace turn endpoint');
assert.ok(workspace.includes('auto_install=${deps.auto_install ? \'yes\' : \'no\'}'), 'dependency summary reports auto_install truthfully');
assert.ok(workspace.includes("item.method === 'apt' ? 'INSTALL' : 'REVIEW'"), 'dep rows promise INSTALL only where a reviewed installer exists; unmapped items say REVIEW');
assert.ok(index.includes('id="custom-dependency-form"') && index.includes('id="custom-dependency-name"'), 'Dependencies has an accessible manual text-entry workflow');
assert.ok(index.includes('<option value="package">') && index.includes('<option value="ollama">') && index.includes('<option value="model">'), 'manual workflow explicitly classifies package, runtime, and model requests');
assert.ok(workspace.includes("body: { package: name") && workspace.includes("body: { name, role }"), 'manual input routes to typed package planning or model management rather than a shell');
assert.ok(app.includes("api('/api/dependencies/execute'") && app.includes('OPEN INSTALL TERMINAL'), 'root package plans launch the exact reviewed CLI handoff in an in-app PTY');
assert.ok(app.includes('VORTEX never reads your password'), 'root package plan explains narrow OS-owned authentication');

// Reports view is fully interactive: downloads, PREVIEW, DELETE; renaming a
// conversation renames its reports; next steps are one-click follow-ups; a
// canvas failure can never kill app wiring.
assert.ok(workspace.includes('data-report-preview') && workspace.includes('data-report-delete'), 'report cards carry PREVIEW and DELETE actions');
assert.ok(workspace.includes("api(`/api/reports/${encodeURIComponent(btn.dataset.reportDelete)}/delete`"), 'report DELETE posts to the real route');
assert.ok(workspace.includes('async function previewReport') && workspace.includes("download?format=md"), 'report preview loads the real markdown');
assert.ok(backend.includes('delete_report'), 'report delete route is served');
const workspacePy = read('backend/workspace.py');
assert.ok(workspacePy.includes('UPDATE reports SET title=? WHERE task_id IN (SELECT id FROM tasks WHERE conversation_id=?)'), 'renaming a conversation renames its reports');
assert.ok(app.includes('data-next-step'), 'analysis next steps render as clickable chips');
// The falling-rain background must be gone entirely: no canvas, no renderer,
// no CSS keyframe/surface, and no config default to re-enable it.
assert.ok(!index.includes('id="matrix"') && !index.includes('class="noise"'), 'matrix canvas/noise surfaces are removed');
assert.ok(!app.includes('setupMatrix'), 'matrix renderer is removed from app wiring');
assert.ok(!styles.includes('#matrix') && !styles.includes('.noise'), 'matrix/noise CSS rules are removed');
assert.ok(!backend.includes('"matrix": "medium"'), 'matrix settings default is removed');
// The Local AI / Models view exists and is wired to the Ollama management API.
assert.ok(index.includes('id="view-models"') && index.includes('data-view="models"'), 'Models view and nav entry exist');
assert.ok(index.includes('assets/models.js'), 'Models view loads its dedicated module');
assert.ok(models.includes("api(fresh ? '/api/ollama?fresh=1' : '/api/ollama')"), 'models module loads runtime + catalog status, fresh-scanning on demand');
assert.ok(models.includes('loadModels(true)'), 'models view forces a fresh GGUF scan');
assert.ok(models.includes('/api/ollama/install'), 'models module can install Ollama');
assert.ok(models.includes('/api/ollama/install/cancel'), 'models module can cancel an in-flight runtime install');
assert.ok(models.includes('/api/ollama/models/pull'), 'models module can pull a model');
assert.ok(models.includes('/api/ollama/models/activate'), 'models module can activate an installed model role');
assert.ok(models.includes('/api/ollama/models/cancel'), 'models module can cancel a download');
assert.ok(models.includes('/api/ollama/models/remove'), 'models module can remove a model');
assert.ok(index.includes('id="add-local-model"') && index.includes('id="add-model-folder"'), 'Models view exposes local file and folder selection');
assert.ok(models.includes('window.vortexApi && window.vortexApi.localFilePath'), 'local model selection resolves Electron File paths through preload');
assert.ok(models.includes("api('/api/models/gguf/import'"), 'local model selection posts only through the GGUF import route');
// The Agents view must surface the local AI runtime + model pool (Ollama and
// the local LLMs) with real actions, not just the external agent council, so
// the operator can install Ollama and download models without hunting for the
// Models view. The agent council itself stays advisory-only and non-fabricated.
assert.ok(index.includes('id="agents-local-ai"'), 'Agents view surfaces the local AI panel');
assert.ok(index.includes('id="view-agents"') && index.includes('data-view-target="models"'), 'Agents view links to the full Models view');
assert.ok(models.includes('renderAgentsLocalAi'), 'models module renders the Agents local-AI panel');
assert.ok(models.includes('>INSTALL OLLAMA<'), 'Agents panel offers the real Ollama install action');
assert.ok(models.includes('install &amp; start Ollama first'), 'model downloads gate on an installed+started runtime');
assert.ok(models.includes("data-local-ai-pull"), 'Agents panel wires per-model DOWNLOAD actions');
// Failure/status text is escaped exactly once: values are interpolated raw and
// the whole line is escaped at the final interpolation. Double-escaping made
// TLS/URL errors render as literal `&lt;...&gt;` instead of real text.
assert.ok(models.includes("job.error ? ': ' + job.error"), 'install failure text is escaped exactly once');
assert.ok(models.includes("'<p>' + esc(line) + '</p>'"), 'install line is escaped at the final interpolation');
assert.ok(models.includes("(job.last_status || job.status)"), 'download status text is escaped exactly once');
assert.ok(models.includes("'<div class=\"model-meta\">' + esc(statusLine)"), 'download status is escaped at the final interpolation');
// Analysis is verdict-first and quantitative; one conversation spans reloads.
assert.ok(app.includes('VERDICT · '), 'analysis renders an explicit verdict header');
assert.ok(app.includes('${esc(verdict.passed ?? 0)}/${esc(verdict.total_commands ?? 0)} commands passed'), 'verdict shows pass counts');
assert.ok(app.includes('${esc(verdict.total_duration_ms ?? 0)} ms wall execution'), 'verdict shows wall execution time');
assert.ok(app.includes('exit ${esc(c.exit_code ?? ' + "'—'" + ')}'), 'per-command timeline shows exit codes');
assert.ok(workspace.includes("localStorage.getItem('vortex.conversationId')"), 'active conversation survives page reloads');
assert.ok(workspace.includes('persistConversationId(state.conversationId);'), 'conversation id is persisted after every turn');
// Rename and edit&branch use inline editors: native prompt() is silently
// blocked in sandboxed iframe previews and reads as a dead button.
assert.ok(!workspace.includes("prompt('Rename conversation')") && !workspace.includes("prompt('Edit this instruction"), 'no native prompt dialogs remain');
assert.ok(workspace.includes('rename-input') && workspace.includes('data-rename-save'), 'conversation rename is an inline editor with SAVE');
assert.ok(workspace.includes('edit-input') && workspace.includes('data-edit-save'), 'message edit & branch is an inline editor with SAVE');
assert.ok(workspace.includes("api(`/api/conversations/${encodeURIComponent(id)}/rename`"), 'inline rename posts to the real route');
assert.ok(workspace.includes("input.focus({ preventScroll: true })") || workspace.includes('input.focus()'), 'chat submit refocuses the input');
assert.ok(app.includes("$('request-input').addEventListener('keydown'"), 'request input Enter is wired');
assert.ok(workspace.includes('sendButton.disabled = false'), 'SEND button is re-enabled on failure');
assert.ok(workspace.includes('if (planning)') && workspace.includes('planning = false'), 'chat submit is guarded against overlapping turns');
// Long operations remain observable for the sum of command budgets, and an SSE
// terminal event is finalized exactly once rather than rendered again after a
// redundant fetch. PTY stream reconnects resume from the last sequence.
assert.ok(app.includes('commandBudget + 60') && app.includes('while (Date.now() < deadline)'), 'operation watcher honors long command budgets');
assert.ok(app.includes('if (streamed) { await finish(streamed); return; }'), 'terminal SSE result finalizes once');
assert.ok(app.includes('/stream?since=${since}') && app.includes('Number.isSafeInteger(seq)'), 'PTY reconnect resumes and rejects duplicate/invalid sequence events');
assert.ok(app.includes('sessionStreamRetryAt[sessionId] = Date.now() + 2000'), 'PTY stream reconnects are backoff-limited');

// Unclear requests render clickable suggestion hints, local capability
// retrieval, and completed operations render verification plus next_steps.
assert.ok(app.includes('data-suggestion'), 'plan suggestion chips are rendered');
assert.ok(app.includes('TRY ONE OF THESE'), 'plan suggestion headings are rendered');
assert.ok(app.includes('LOCAL CAPABILITIES'), 'local capability retrieval is rendered');
assert.ok(app.includes('Verification'), 'analysis verification section is rendered');
assert.ok(app.includes('Next steps'), 'analysis next-steps section is rendered');
assert.ok(backend.includes('"suggestions": suggestion_hints'), 'backend plan carries suggestion hints');
assert.ok(backend.includes('"knowledge": knowledge_retrieve'), 'backend plan carries local capability retrieval');
assert.ok(backend.includes('"verification":'), 'backend analysis carries verification summary');
assert.ok(backend.includes('analysis_next_steps(plan, op)'), 'backend operation carries concrete next steps');

// Tasks view exposes the already-existing RESTART route.
assert.ok(workspace.includes('data-task-restart'), 'Tasks RESTART button is rendered');
assert.ok(workspace.includes('/restart'), 'Tasks RESTART route is wired');

// Agents install button must open a real operator-controlled proposal surface,
// not silently do nothing.
assert.ok(workspace.includes('data-agent-install'), 'Agents missing rows include an install action');
assert.ok(workspace.includes("openDependency(`agent:"), 'Agents install opens the dependency proposal surface');
assert.ok(workspace.includes('btn.disabled = false'), 'Agents install button is restored after the action');

// Host-tool access, APK sync-then-download, and MIT license are operator-facing.
assert.ok(index.includes('id="download-apk"') && index.includes('id="download-apk-settings"'), 'DOWNLOAD APK buttons exist');
assert.ok(index.includes('id="host-tools-setting"') && index.includes('id="rescan-host-tools"'), 'host-tool access and PATH rescan exist');
assert.ok(index.includes('id="license-badge"') && index.includes('MIT'), 'MIT license badge exists');
assert.ok(app.includes("api('/api/mobile/apk'"), 'APK button posts a live sync before download');
assert.ok(app.includes("const url = '/api/mobile/apk/download'") && app.includes("triggerDownload(url, 'vortex.apk')"), 'APK download follows a successful sync via the layered trigger');
// Both package downloads must survive sandboxed iframe previews: a top-level
// tab trigger first, the classic anchor click as fallback, and a real manual
// link in the completion toast for contexts that block both.
assert.ok(app.includes('function triggerDownload(url, filename)'), 'layered download trigger exists');
assert.ok(app.includes("window.open(url, '_blank')"), 'layered trigger opens a top-level tab when embedded');
assert.ok(app.includes('window.vortexApi?.request'), 'layered trigger keeps the Electron anchor path');
assert.ok(app.includes('link.download = filename'), 'layered trigger falls back to a real anchor download');
assert.ok(app.includes("manual.target = '_blank'"), 'completion toast carries a top-level manual link');
// Desktop .deb button: live build before download, settings card placement.
assert.ok(index.includes('id="download-deb-settings"'), 'DOWNLOAD .DEB settings card exists');
assert.ok(index.includes('Desktop app</h2>'), 'desktop app card is titled');
assert.ok(app.includes("api('/api/desktop/deb'"), 'desktop button posts a live build before download');
assert.ok(app.includes("triggerDownload(url, filename)"), 'desktop download uses the layered trigger');
assert.ok(app.includes("$('download-deb-settings')?.addEventListener('click', downloadDeb)"), 'desktop settings card button is wired');
// Topbar overflow fix: HELP/ABOUT launch from the sidebar nav, the topbar
// wraps instead of clipping controls, and DOWNLOAD APK stays in the topbar.
assert.ok(index.includes('class="nav-item" id="open-help"') && index.includes('class="nav-item" id="open-about"'), 'HELP and ABOUT launchers live in the sidebar nav');
assert.ok(!index.includes('class="secondary-button" id="open-help"') && !index.includes('class="secondary-button" id="open-about"'), 'topbar no longer carries HELP/ABOUT');
assert.ok(/\.topbar ?\{[^}]*flex-wrap:wrap/.test(styles), 'topbar wraps instead of clipping its controls');
assert.ok(/\.top-actions ?\{[^}]*flex-wrap:wrap/.test(styles), 'top actions wrap instead of overflowing');
assert.ok(app.includes("api('/api/tools/host/rescan'"), 'PATH rescan posts to the host-tools endpoint');
assert.ok(workspace.includes('host_tool_access'), 'host-tool access setting is persisted');
assert.ok(backend.includes('"/api/mobile/apk/download"') || backend.includes("'/api/mobile/apk/download'") || backend.includes('path == "/api/mobile/apk/download"') || backend.includes("endswith(\"/api/mobile/apk/download\")") || backend.includes('apk/download'), 'APK download route is served');

// Refresh buttons must force a fresh probe rather than silently using the cache.
assert.ok(app.includes("loadDoctor(true)"), 'Refresh DOCTOR forces a fresh host probe');
assert.ok(app.includes("loadTools(true)"), 'Refresh TOOLS forces a fresh host probe');
assert.ok(workspace.includes("loadAgents(true)"), 'Refresh AGENTS forces a fresh host probe');
assert.ok(workspace.includes("loadHealth(true)"), 'Refresh HEALTH forces a fresh host probe');
assert.ok(backend.includes("_query_flag(query, \"fresh\")"), 'backend honors ?fresh=1 to bypass cached probes');

// "install podman" must never fall into container inspection, and a
// "container <name>" service query must not capture generic container requests.
assert.ok(/not parse_package_request\(lower\)\[0\] and not parse_service\(lower\) and any\(word in lower for word in \([\s\S]*?\"docker\".*\"podman\".*\"container\"[\s\S]*?\)\)/.test(backend), 'container branches yield to package installs');

// Every static `/api/...` literal used by the renderer must be served by a
// matching backend route. Dynamic segments are reduced to their literal prefix,
// so `/api/operations/${id}/approve` is checked against `path.startswith(...)`.
const frontendMatches = [];
for (const source of [app, workspace, models]) {
  for (const match of source.matchAll(/api\(\s*`([^`]+)`/g)) frontendMatches.push(match[1]);
  for (const match of source.matchAll(/api\(\s*'([^']+)'/g)) frontendMatches.push(match[1]);
}
const frontendBaseRoutes = [...new Set(frontendMatches)]
  .map(route => route.split('${')[0].split("'")[0])
  .filter(route => route.startsWith('/api/'))
  .map(route => route.includes('?') ? route.split('?')[0] : route)
  .filter((route, index, all) => all.indexOf(route) === index);
for (const frontendRoute of frontendBaseRoutes) {
  const quoted = JSON.stringify(frontendRoute);
  const served = backend.includes(quoted)
    || backend.includes(`path.startswith(${quoted})`)
    || backend.includes(`path.endswith(${quoted})`);
  assert.ok(served, `frontend route ${frontendRoute} is served by the backend`);
}

// Backend aggregate probe endpoints are cached and probe lookups are shared.
assert.ok(probeCache.includes('class TTLCache'), 'TTL probe cache module exists');
assert.ok(backend.includes('_CAPABILITIES_CACHE'), 'capabilities cache is declared');
assert.ok(backend.includes('_DEPENDENCIES_CACHE'), 'dependencies cache is declared');
assert.ok(backend.includes('_DOCTOR_CACHE'), 'doctor context cache is declared');
assert.ok(backend.includes('_TOOLS_REGISTRY_CACHE'), 'tools registry cache is declared');

// Dropped clients must not crash the sidecar, and HEAD assets must be served.
assert.ok(backend.includes('BrokenPipeError'), 'broken-pipe handling is present');
assert.ok(backend.includes('def do_HEAD'), 'HEAD support is present');
assert.ok(backend.includes('adapter_id = None'), 'scanner adapter_id is defensively initialized');

// Intelligent command palette: a leading "/" routes to the reviewed palette
// route. Plan commands reuse the existing reviewed planner (Guardian/approval
// apply); query commands are read-only local lookups.
assert.ok(workspace.includes("api('/api/palette'"), 'palette posts to the reviewed palette route');
assert.ok(workspace.includes('submitPalette'), 'palette handler is defined');
assert.ok(workspace.includes("text.startsWith('/')"), 'slash commands route to the palette');
assert.ok(workspace.includes('renderPaletteResult'), 'palette query results render into the plan view');
assert.ok(workspace.includes('submitPalette(command)'), 'palette request is passed as one string');

// Asset graph view is reachable and loads the store-derived graph endpoint.
assert.ok(index.includes('id="view-assets"'), 'asset graph view exists');
assert.ok(index.includes('data-view="assets"'), 'asset graph nav entry exists');
assert.ok(workspace.includes("api('/api/assets/graph'"), 'asset graph loads the real endpoint');
assert.ok(workspace.includes('loadAssets'), 'asset graph renderer is defined');
assert.ok(workspace.includes("if (view === 'assets') loadAssets()"), 'setView loads the asset graph');

// Results popup actions: contextual VERIFY / REPORT / EXPORT reuse existing
// endpoints and are offered only for a result that has observed output.
assert.ok(app.includes('data-result-action="verify"'), 'results actions render VERIFY');
assert.ok(app.includes('data-result-action="report"'), 'results actions render REPORT');
assert.ok(app.includes('data-result-action="export"'), 'results actions render EXPORT');
assert.ok(app.includes("api('/api/audit/verify'"), 'VERIFY re-checks the audit chain');
assert.ok(app.includes("api('/api/reports'"), 'REPORT looks up the real operation report');
assert.ok(app.includes('/api/conversations/${encodeURIComponent(state.conversationId)}/export'), 'EXPORT uses the conversation export route');

console.log('frontend smoke tests: PASS');
