/* Runtime detection — the UI must always know WHICH runtime it is in.
 *
 *   LOCAL_LINUX : Electron app or browser talking to the loopback Python
 *                 sidecar. Real adapters, Guardian, PTY, local Qwen.
 *   WEB_CLOUD   : the Vercel deployment. The backend is the serverless
 *                 web API; there is NO access to the visitor's Linux
 *                 machine and NO local Ollama (the browser must never
 *                 try localhost:11434).
 *   UNKNOWN     : nothing answered — e.g. local dev with the sidecar off.
 *
 * Detection is honest: Electron bridge ⇒ LOCAL. Otherwise we ask the
 * backend itself (`/api/health` carries a `runtime` field in both
 * runtimes). We never guess "local" just because a button exists.
 */
import { apiGet, JsonRecord } from './vortexApi';
import { setCurrentRuntime, VortexRuntime } from './runtimeState';

export type { VortexRuntime } from './runtimeState';

export interface RuntimeInfo {
  runtime: VortexRuntime;
  label: string;
  version: string;
  freeOnly: boolean | null;
  capabilities: JsonRecord;
  localAgent: { connected: boolean; status: string } | null;
}

const UNKNOWN_INFO: RuntimeInfo = {
  runtime: 'UNKNOWN',
  label: 'runtime unknown — backend unreachable',
  version: '',
  freeOnly: null,
  capabilities: {},
  localAgent: null,
};

let current: RuntimeInfo = UNKNOWN_INFO;
let pending: Promise<RuntimeInfo> | null = null;
const listeners = new Set<(info: RuntimeInfo) => void>();

function hasElectronBridge(): boolean {
  try {
    const bridge = (window as unknown as { vortexApi?: { request?: unknown } }).vortexApi;
    return !!bridge && typeof bridge.request === 'function';
  } catch {
    return false;
  }
}

function notify(): void {
  listeners.forEach((listener) => {
    try { listener(current); } catch { /* listener errors never break detection */ }
  });
}

async function probe(): Promise<RuntimeInfo> {
  try {
    const payload = await apiGet<JsonRecord>('/api/health', 12000);
    const declared = String(payload.runtime || '');
    const runtime: VortexRuntime = declared === 'WEB_CLOUD'
      ? 'WEB_CLOUD'
      : 'LOCAL_LINUX'; // sidecar (declares LOCAL_LINUX; older builds omit it)
    const agent = (payload.local_agent && typeof payload.local_agent === 'object'
      ? payload.local_agent : null) as JsonRecord | null;
    current = {
      runtime,
      label: String(payload.runtime_label || (runtime === 'WEB_CLOUD' ? '☁ WEB — Vercel' : '● LOCAL — Linux')),
      version: String(payload.version || ''),
      freeOnly: payload.free_only === undefined ? null : payload.free_only !== false,
      capabilities: (payload.capabilities || {}) as JsonRecord,
      localAgent: agent
        ? { connected: agent.connected === true, status: String(agent.status || '') }
        : (runtime === 'WEB_CLOUD' ? { connected: false, status: 'LOCAL MACHINE: NOT CONNECTED' } : null),
    };
  } catch {
    current = hasElectronBridge()
      ? { ...UNKNOWN_INFO, runtime: 'LOCAL_LINUX', label: '● LOCAL — Linux (sidecar starting…)' }
      : UNKNOWN_INFO;
  }
  setCurrentRuntime(current.runtime as VortexRuntime);
  notify();
  return current;
}

/** Detect (or re-detect) the runtime. Concurrent callers share one probe. */
export function detectRuntime(force = false): Promise<RuntimeInfo> {
  if (hasElectronBridge() && current.runtime !== 'LOCAL_LINUX') {
    current = { ...current, runtime: 'LOCAL_LINUX', label: '● LOCAL — Linux' };
    setCurrentRuntime('LOCAL_LINUX');
  }
  if (!force && current.runtime !== 'UNKNOWN' && current.version) {
    return Promise.resolve(current);
  }
  if (!pending) {
    pending = probe().finally(() => { pending = null; });
  }
  return pending;
}

/** Last detected runtime (synchronous — 'UNKNOWN' until a probe lands). */
export function runtimeInfo(): RuntimeInfo {
  return current;
}

export function isWebRuntime(): boolean {
  return current.runtime === 'WEB_CLOUD';
}

export function onRuntimeChange(listener: (info: RuntimeInfo) => void): () => void {
  listeners.add(listener);
  if (current !== UNKNOWN_INFO) listener(current);
  return () => listeners.delete(listener);
}
