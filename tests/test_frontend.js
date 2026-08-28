'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');

const read = (p) => fs.readFileSync(path.join(__dirname, '..', p), 'utf8');
const index = read('frontend/index.html');
const workspace = read('frontend/workspace.js');
const app = read('frontend/app.js');
const backend = read('backend/vortex_backend.py');
const probeCache = read('backend/probe_cache.py');

// First-run surface must never auto-cover the chat bar unless setup is ready,
// and must always be dismissible.
assert.ok(index.includes('id="first-run"'), 'first-run surface exists');
assert.ok(index.includes('id="skip-setup"'), 'SKIP button exists');
assert.ok(workspace.includes('if (!setup.ready) return;'), 'not-ready setup never opens the modal');
assert.ok(workspace.includes('hideFirstRun()'), 'first-run close helper is wired');
assert.ok(workspace.includes('finally { hideFirstRun(); }') || workspace.includes('finally { hideFirstRun() }'), 'CONTINUE closes surface in finally');

// Chat bar must be focusable/labeled and submit must local-echo, reset, and
// re-enable the SEND button in a finally block.
assert.ok(index.includes('id="request-input"') && index.includes('aria-label="Ask VORTEX"'), 'request input is labeled');
assert.ok(index.includes('id="plan-button"') && index.includes('aria-label="Send"'), 'send button is labeled');
assert.ok(workspace.includes('local-echo'), 'chat submit local-echoes the user message');
assert.ok(workspace.includes("api('/api/workspace/turn'"), 'chat submit uses the workspace turn endpoint');
assert.ok(workspace.includes('auto_install=${deps.auto_install ? \'yes\' : \'no\'}'), 'dependency summary reports auto_install truthfully');
assert.ok(workspace.includes("input.focus({ preventScroll: true })") || workspace.includes('input.focus()'), 'chat submit refocuses the input');
assert.ok(app.includes("$('request-input').addEventListener('keydown'"), 'request input Enter is wired');
assert.ok(workspace.includes('sendButton.disabled = false'), 'SEND button is re-enabled on failure');
assert.ok(workspace.includes('if (planning)') && workspace.includes('planning = false'), 'chat submit is guarded against overlapping turns');

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
assert.ok(app.includes("link.href = '/api/mobile/apk/download'"), 'APK download follows a successful sync');
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
for (const source of [app, workspace]) {
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

console.log('frontend smoke tests: PASS');
