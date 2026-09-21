'use strict';

const MAX_ROUTE_LENGTH = 2048;
const SAFE_ID = '[A-Za-z0-9._:@-]+';

const GET_ROUTES = [
  /^\/api\/(?:doctor|tools|engagements|history|reports|sessions|dashboard|health|ollama|settings|setup|agents|conversations|tasks|memory|learning|findings|models|search|artifacts|capabilities|license)$/,
  /^\/api\/tools\/host$/,
  /^\/api\/system\/health$/,
  /^\/api\/audit\/verify$/,
  /^\/api\/assets\/graph$/,
  /^\/api\/models\/gguf$/,
  /^\/api\/llamafile$/,
  /^\/api\/reports\/system$/,
  /^\/api\/mobile\/apk$/,
  /^\/api\/desktop\/deb$/,
  /^\/api\/install\/commands$/,
  /^\/api\/agents\/upstream$/,
  /^\/api\/assist\/coverage$/,
  /^\/api\/dependencies(?:\/proposal)?$/,
  new RegExp(`^/api/operations/${SAFE_ID}$`),
  new RegExp(`^/api/sessions/${SAFE_ID}/events$`),
  new RegExp(`^/api/remote-desktop(?:/sessions)?$`),
  new RegExp(`^/api/remote-desktop/sessions/${SAFE_ID}$`),
  new RegExp(`^/api/agents/${SAFE_ID}/install$`),
  new RegExp(`^/api/conversations/${SAFE_ID}$`),
  new RegExp(`^/api/tasks/${SAFE_ID}$`),
  new RegExp(`^/api/tasks/${SAFE_ID}/events$`),
  new RegExp(`^/api/reports/assessment/${SAFE_ID}$`),
  new RegExp(`^/api/reports/${SAFE_ID}$`),
  new RegExp('^/api/agent/runs$'),
  new RegExp(`^/api/agent/runs/${SAFE_ID}$`),
  new RegExp(`^/api/agent/runs/${SAFE_ID}/stream$`)
];

const POST_ROUTES = [
  /^\/api\/(?:engagements|sessions|conversations|palette|settings|secrets|execute|assist|memory|plan)$/,
  /^\/api\/artifacts\/analyze$/,
  /^\/api\/(?:mobile\/apk|desktop\/deb|workspace\/turn|tools\/host\/rescan|control\/stop-all|setup\/complete|refresh|dependencies\/(?:plan|execute))$/,
  /^\/api\/ollama\/(?:install(?:\/cancel)?|server\/(?:start|stop)|models\/(?:pull|activate|cancel|remove))$/,
  /^\/api\/models\/gguf\/(?:activate|import)$/,
  /^\/api\/llamafile\/(?:install(?:\/cancel)?|import|server\/(?:start|stop)|models\/(?:activate|remove))$/,
  /^\/api\/agents\/upstream\/refresh$/,
  new RegExp(`^/api/engagements/${SAFE_ID}/close$`),
  new RegExp(`^/api/operations/${SAFE_ID}/(?:approve|cancel|complete-task)$`),
  new RegExp(`^/api/sessions/${SAFE_ID}/(?:input|kill|resize)$`),
  /^\/api\/remote-desktop\/(?:probe|sessions)$/,
  new RegExp(`^/api/remote-desktop/sessions/${SAFE_ID}/(?:approve|ticket|reconnect|disconnect|close|activity)$`),
  new RegExp(`^/api/conversations/${SAFE_ID}/(?:rename|archive|delete)$`),
  new RegExp(`^/api/conversations/${SAFE_ID}/messages/${SAFE_ID}/edit$`),
  new RegExp(`^/api/tasks/${SAFE_ID}/(?:restart|resume|delete|pause)$`),
  new RegExp(`^/api/reports/${SAFE_ID}/(?:delete|rename|edit)$`),
  new RegExp(`^/api/plans/${SAFE_ID}/reject$`),
  new RegExp('^/api/agent/runs$'),
  new RegExp(`^/api/agent/runs/${SAFE_ID}/(?:approve|stop)$`)
];

function parseRelativeRoute(route) {
  if (typeof route !== 'string' || route.length === 0 || route.length > MAX_ROUTE_LENGTH) return null;
  if (!route.startsWith('/api/') || /[\\\u0000-\u001f\u007f]/.test(route) || route.includes('#')) return null;
  let parsed;
  try {
    parsed = new URL(route, 'http://vortex.invalid');
  } catch (_) {
    return null;
  }
  if (parsed.origin !== 'http://vortex.invalid') return null;
  let pathname;
  try {
    pathname = decodeURIComponent(parsed.pathname);
  } catch (_) {
    return null;
  }
  if (pathname.includes('..') || /[\u0000-\u001f\u007f\\]/.test(pathname)) return null;
  return { pathname, search: parsed.search };
}

function isAllowedApiRequest(route, method = 'GET') {
  const parsed = parseRelativeRoute(route);
  const normalizedMethod = typeof method === 'string' ? method.toUpperCase() : '';
  if (!parsed || !['GET', 'POST'].includes(normalizedMethod)) return false;
  const routes = normalizedMethod === 'GET' ? GET_ROUTES : POST_ROUTES;
  return routes.some(pattern => pattern.test(parsed.pathname));
}

// WebSocket upgrades live on the same host and port as the HTTP sidecar. Treat
// ws/wss as the same authority as http/https so origin checks and the
// renderer's capability injection apply to the real desktop stream too.
function sidecarOrigin(rawUrl) {
  const parsed = new URL(rawUrl);
  const family = parsed.protocol === 'ws:' || parsed.protocol === 'http:' ? 'http:'
    : parsed.protocol === 'wss:' || parsed.protocol === 'https:' ? 'https:' : parsed.protocol;
  return `${family}//${parsed.host}`;
}

function sameSidecarUrl(rawUrl, sidecarUrl) {
  try {
    return sidecarOrigin(rawUrl) === sidecarOrigin(sidecarUrl);
  } catch (_) {
    return false;
  }
}

function isSidecarDownloadUrl(rawUrl, sidecarUrl) {
  if (!sameSidecarUrl(rawUrl, sidecarUrl)) return false;
  try {
    const pathname = decodeURIComponent(new URL(rawUrl).pathname);
    return /^\/api\/(?:mobile\/apk\/download|desktop\/deb\/download)$/.test(pathname) ||
      new RegExp(`^/api/reports/${SAFE_ID}/download$`).test(pathname) ||
      new RegExp(`^/api/reports/assessment/${SAFE_ID}$`).test(pathname) ||
      new RegExp(`^/api/conversations/${SAFE_ID}/export$`).test(pathname) ||
      pathname === '/api/reports/system';
  } catch (_) {
    return false;
  }
}

function isDirectRendererRequest(rawUrl, sidecarUrl, method = 'GET') {
  if (!sameSidecarUrl(rawUrl, sidecarUrl) || String(method).toUpperCase() !== 'GET') return false;
  try {
    const pathname = decodeURIComponent(new URL(rawUrl).pathname);
    return pathname === '/' || pathname === '/index.html' || pathname.startsWith('/assets/') ||
      pathname === '/api/aiops/stream' ||
      new RegExp(`^/api/operations/${SAFE_ID}/stream$`).test(pathname) ||
      new RegExp(`^/api/sessions/${SAFE_ID}/stream$`).test(pathname) ||
      new RegExp(`^/api/remote-desktop/sessions/${SAFE_ID}/stream$`).test(pathname) ||
      new RegExp(`^/api/agent/runs/${SAFE_ID}/stream$`).test(pathname) ||
      isSidecarDownloadUrl(rawUrl, sidecarUrl);
  } catch (_) {
    return false;
  }
}

function isExternalWebUrl(rawUrl) {
  try {
    return new URL(rawUrl).protocol === 'https:';
  } catch (_) {
    return false;
  }
}

function parseBootInfo(line) {
  if (typeof line !== 'string' || line.length > 4096) return null;
  try {
    const value = JSON.parse(line);
    if (value?.backend !== 'online' || !Number.isInteger(value.port) || value.port < 1 || value.port > 65535) return null;
    if (value.host !== '127.0.0.1' && value.host !== 'localhost') return null;
    return Object.freeze({ host: value.host, port: value.port, version: String(value.version || '') });
  } catch (_) {
    return null;
  }
}

module.exports = Object.freeze({
  MAX_ROUTE_LENGTH,
  isAllowedApiRequest,
  isDirectRendererRequest,
  isExternalWebUrl,
  isSidecarDownloadUrl,
  parseBootInfo,
  parseRelativeRoute,
  sameSidecarUrl,
  sidecarOrigin
});
