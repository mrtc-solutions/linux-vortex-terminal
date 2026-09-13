/* Vortex Terminal sidecar API client — the ONLY bridge between the React shell and reality.
   Every function below calls the loopback Python sidecar (127.0.0.1:8765);
   nothing here fabricates data. All failures surface honestly to the caller. */

export interface ApiErrorShape {
  status: number;
  code: string;
  message: string;
}

export class ApiError extends Error {
  status: number;
  code: string;
  constructor(shape: ApiErrorShape) {
    super(shape.message);
    this.name = 'ApiError';
    this.status = shape.status;
    this.code = shape.code;
  }
}

async function parseJson(response: Response): Promise<Record<string, unknown>> {
  const text = await response.text();
  if (!text) return {};
  try {
    const value: unknown = JSON.parse(text);
    return (value && typeof value === 'object' ? value : {}) as Record<string, unknown>;
  } catch {
    return { _raw: text };
  }
}

function toError(status: number, payload: Record<string, unknown>, fallback: string): ApiError {
  const err = (payload.error && typeof payload.error === 'object'
    ? payload.error as Record<string, unknown> : {}) as Record<string, unknown>;
  return new ApiError({
    status,
    code: String(err.code || (status === 0 ? 'network' : `http_${status}`)),
    message: String(err.message || fallback),
  });
}

export async function apiGet<T = Record<string, unknown>>(path: string, timeoutMs = 15000): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, { method: 'GET', signal: controller.signal });
    const payload = await parseJson(response);
    if (!response.ok) throw toError(response.status, payload, `GET ${path} failed (${response.status})`);
    return payload as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError({ status: 0, code: 'timeout', message: `Sidecar did not answer GET ${path} within ${Math.round(timeoutMs / 1000)}s. It may be busy (model loading, scan running) — retry the action.` });
    }
    throw new ApiError({ status: 0, code: 'network', message: `Sidecar unreachable at ${path}. Is Vortex Terminal running?` });
  } finally {
    window.clearTimeout(timer);
  }
}

export async function apiPost<T = Record<string, unknown>>(
  path: string, body: Record<string, unknown> = {}, timeoutMs = 60000,
): Promise<T> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    const payload = await parseJson(response);
    if (!response.ok) throw toError(response.status, payload, `POST ${path} failed (${response.status})`);
    return payload as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError({ status: 0, code: 'timeout', message: `Sidecar did not answer POST ${path} within ${Math.round(timeoutMs / 1000)}s. It may be busy (model loading, scan running) — retry the action.` });
    }
    throw new ApiError({ status: 0, code: 'network', message: `Sidecar unreachable at ${path}. Is Vortex Terminal running?` });
  } finally {
    window.clearTimeout(timer);
  }
}

export async function apiDownload(path: string, filename: string): Promise<void> {
  const response = await fetch(path, { method: 'GET' });
  if (!response.ok) throw new ApiError({ status: response.status, code: `http_${response.status}`, message: `Download failed (${response.status})` });
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 4000);
}

/* ---------------- Server-sent events with poll fallback ---------------- */

export interface StreamHandle {
  close: () => void;
}

export function openEventStream(
  path: string,
  onEvent: (data: Record<string, unknown>) => void,
  onError?: (err: Error) => void,
): StreamHandle {
  let closed = false;
  let source: EventSource | null = null;
  try {
    source = new EventSource(path);
  } catch (err) {
    onError?.(err instanceof Error ? err : new Error(String(err)));
    return { close: () => { closed = true; } };
  }
  source.onmessage = (event: MessageEvent) => {
    if (closed) return;
    try {
      onEvent(JSON.parse(String(event.data)) as Record<string, unknown>);
    } catch {
      onEvent({ _raw: String(event.data) });
    }
  };
  source.onerror = () => {
    if (closed) return;
    onError?.(new Error('Event stream interrupted'));
  };
  return {
    close: () => {
      closed = true;
      try { source?.close(); } catch { /* already closed */ }
    },
  };
}

/* ---------------- Shared payload shapes (loose by design) ---------------- */

export type JsonRecord = Record<string, unknown>;
export type TurnResult = JsonRecord;
export type PlanDocument = JsonRecord;
export type OperationDocument = JsonRecord;
export type TaskDocument = JsonRecord;
export type ConversationDocument = JsonRecord;
export type ArtifactDocument = JsonRecord;
export type FindingDocument = JsonRecord;
export type ToolDocument = JsonRecord;
export type EngagementDocument = JsonRecord;
export type ReportDocument = JsonRecord;

/* ---------------- Health / capabilities / settings ---------------- */

export const getHealth = () => apiGet<JsonRecord>('/api/health');
export const getSystemHealth = () => apiGet<JsonRecord>('/api/system/health');
export const getCapabilities = () => apiGet<JsonRecord>('/api/capabilities');
export const getSettings = () => apiGet<JsonRecord>('/api/settings');
export const saveSettings = (settings: JsonRecord) => apiPost<JsonRecord>('/api/settings', settings);
export const getSetup = () => apiGet<JsonRecord>('/api/setup');
export const completeSetup = () => apiPost<JsonRecord>('/api/setup/complete');
export const verifyAudit = () => apiGet<JsonRecord>('/api/audit/verify');
export const refreshAll = () => apiPost<JsonRecord>('/api/refresh', {}, 90000);
export const stopAll = () => apiPost<JsonRecord>('/api/control/stop-all');

/* ---------------- Orchestration: turn / plan / palette / operations ---------------- */

export interface TurnOptions {
  cwd?: string;
  engagement_id?: string;
  conversation_id?: string;
  confirm?: boolean;
  approval_token?: string;
  offline?: boolean;
}

export const runTurn = (request: string, options: TurnOptions = {}, timeoutMs = 120000) =>
  apiPost<TurnResult>('/api/workspace/turn', { request, ...options }, timeoutMs);

export const buildPlan = (request: string, options: TurnOptions = {}) =>
  apiPost<{ plan?: PlanDocument } & JsonRecord>('/api/plan', { request, ...options });

export const runPalette = (request: string) =>
  apiPost<JsonRecord>('/api/palette', { request });

export const requestAssist = (fnName: string, request: string) =>
  apiPost<JsonRecord>('/api/assist', { function: fnName, request });

export const getOperation = (id: string) =>
  apiGet<{ operation?: OperationDocument } & JsonRecord>(`/api/operations/${encodeURIComponent(id)}`);

export const approveOperation = (id: string) =>
  apiPost<JsonRecord>(`/api/operations/${encodeURIComponent(id)}/approve`, {}, 120000);

export const cancelOperation = (id: string) =>
  apiPost<JsonRecord>(`/api/operations/${encodeURIComponent(id)}/cancel`);

export const completeOperationTask = (id: string) =>
  apiPost<JsonRecord>(`/api/operations/${encodeURIComponent(id)}/complete-task`);

export const rejectPlan = (id: string) =>
  apiPost<JsonRecord>(`/api/plans/${encodeURIComponent(id)}/reject`);

export const streamOperation = (
  id: string, onEvent: (data: JsonRecord) => void, onError?: (err: Error) => void,
): StreamHandle => openEventStream(`/api/operations/${encodeURIComponent(id)}/stream`, onEvent, onError);

/* ---------------- Tasks ---------------- */

export const listTasks = () => apiGet<{ tasks?: TaskDocument[] } & JsonRecord>('/api/tasks');
export const getTask = (id: string) =>
  apiGet<{ task?: TaskDocument } & JsonRecord>(`/api/tasks/${encodeURIComponent(id)}`);
export const getTaskEvents = (id: string) =>
  apiGet<JsonRecord>(`/api/tasks/${encodeURIComponent(id)}/events`);
export const pauseTask = (id: string) => apiPost<JsonRecord>(`/api/tasks/${encodeURIComponent(id)}/pause`);
export const resumeTask = (id: string) => apiPost<JsonRecord>(`/api/tasks/${encodeURIComponent(id)}/resume`, {}, 120000);
export const restartTask = (id: string) => apiPost<JsonRecord>(`/api/tasks/${encodeURIComponent(id)}/restart`, {}, 120000);
export const deleteTask = (id: string) => apiPost<JsonRecord>(`/api/tasks/${encodeURIComponent(id)}/delete`);

/* ---------------- Conversations / memory / learning ---------------- */

export const listConversations = () => apiGet<JsonRecord>('/api/conversations');
export const getConversation = (id: string) =>
  apiGet<JsonRecord>(`/api/conversations/${encodeURIComponent(id)}`);
export const createConversation = (title: string) =>
  apiPost<JsonRecord>('/api/conversations', { title });
export const renameConversation = (id: string, title: string) =>
  apiPost<JsonRecord>(`/api/conversations/${encodeURIComponent(id)}/rename`, { title });
export const archiveConversation = (id: string) =>
  apiPost<JsonRecord>(`/api/conversations/${encodeURIComponent(id)}/archive`);
export const deleteConversation = (id: string) =>
  apiPost<JsonRecord>(`/api/conversations/${encodeURIComponent(id)}/delete`);
export const exportConversation = (id: string) =>
  apiDownload(`/api/conversations/${encodeURIComponent(id)}/export`, `conversation-${id.slice(0, 8)}.json`);
export const editMessage = (conversationId: string, messageId: string, content: string) =>
  apiPost<JsonRecord>(
    `/api/conversations/${encodeURIComponent(conversationId)}/messages/${encodeURIComponent(messageId)}/edit`,
    { content },
  );

export const listMemories = () => apiGet<JsonRecord>('/api/memory');
export const saveMemory = (title: string, body: string, kind = 'knowledge') =>
  apiPost<JsonRecord>('/api/memory', { title, body, kind });
export const listLearning = () => apiGet<JsonRecord>('/api/learning');

/* ---------------- Engagements (scope gate) ---------------- */

export interface EngagementDraft {
  name: string;
  authorization?: string;
  targets?: string[];
  classes?: string[];
  excluded_targets?: string[];
  owner?: string;
  environment?: string;
}

export const listEngagements = () => apiGet<JsonRecord>('/api/engagements');
export const createEngagement = (draft: EngagementDraft) =>
  apiPost<JsonRecord>('/api/engagements', { ...(draft as unknown as JsonRecord) });
export const closeEngagement = (id: string) =>
  apiPost<JsonRecord>(`/api/engagements/${encodeURIComponent(id)}/close`);

/* ---------------- Tools / host ---------------- */

export const listTools = () => apiGet<JsonRecord>('/api/tools');
export const listHostTools = () => apiGet<JsonRecord>('/api/tools/host');
export const rescanHostTools = () => apiPost<JsonRecord>('/api/tools/host/rescan', {}, 90000);
export const getDoctor = () => apiGet<JsonRecord>('/api/doctor');
export const getDashboard = () => apiGet<JsonRecord>('/api/dashboard');

/* ---------------- Local AI: llamafile / GGUF / Ollama ---------------- */

export const getModels = () => apiGet<JsonRecord>('/api/models');
export const getOllama = () => apiGet<JsonRecord>('/api/ollama');
export const getGguf = () => apiGet<JsonRecord>('/api/models/gguf');
export const getLlamafile = () => apiGet<JsonRecord>('/api/llamafile');
export const installLlamafile = (confirm = false) =>
  apiPost<JsonRecord>('/api/llamafile/install', { confirm });
export const cancelLlamafileInstall = () =>
  apiPost<JsonRecord>('/api/llamafile/install/cancel');
export const importLlamafileModel = (path: string) =>
  apiPost<JsonRecord>('/api/llamafile/import', { path });
export const startLlamafileServer = (model?: string) =>
  apiPost<JsonRecord>('/api/llamafile/server/start', model ? { model } : {}, 90000);
export const stopLlamafileServer = () => apiPost<JsonRecord>('/api/llamafile/server/stop');
export const activateLlamafileModel = (model: string) =>
  apiPost<JsonRecord>('/api/llamafile/models/activate', { model });
export const removeLlamafileModel = (model: string) =>
  apiPost<JsonRecord>('/api/llamafile/models/remove', { model });

export const activateGguf = (file: string, role: string) =>
  apiPost<JsonRecord>('/api/models/gguf/activate', { file, role });
export const importGguf = (path: string) =>
  apiPost<JsonRecord>('/api/models/gguf/import', { paths: [path] });
export const pullOllamaModel = (model: string) =>
  apiPost<JsonRecord>('/api/ollama/models/pull', { model });
export const activateOllamaModel = (model: string, role?: string) =>
  apiPost<JsonRecord>('/api/ollama/models/activate', role ? { model, role } : { model });
export const removeOllamaModel = (model: string) =>
  apiPost<JsonRecord>('/api/ollama/models/remove', { model });
export const startOllamaServer = () => apiPost<JsonRecord>('/api/ollama/server/start');
export const stopOllamaServer = () => apiPost<JsonRecord>('/api/ollama/server/stop');

/* ---------------- Artifacts / findings / assets / reports / search ---------------- */

export const listArtifacts = () => apiGet<JsonRecord>('/api/artifacts');
export const listHistory = () => apiGet<JsonRecord>('/api/history');
export const listFindings = () => apiGet<JsonRecord>('/api/findings');
export const getAssetGraph = () => apiGet<JsonRecord>('/api/assets/graph');
export const listReports = () => apiGet<JsonRecord>('/api/reports');
export const downloadReport = (id: string, format = 'md') =>
  apiDownload(`/api/reports/${encodeURIComponent(id)}/download?format=${encodeURIComponent(format)}`, `report-${id.slice(0, 8)}.${format}`);
export const deleteReport = (id: string) =>
  apiPost<JsonRecord>(`/api/reports/${encodeURIComponent(id)}/delete`);
export const searchAll = (query: string) =>
  apiGet<JsonRecord>(`/api/search?q=${encodeURIComponent(query)}`);
export const analyzeArtifact = (path: string, kind = 'auto') =>
  apiPost<JsonRecord>('/api/artifacts/analyze', { path, kind });

/* ---------------- License / installable packages ---------------- */

export const getLicense = () => apiGet<JsonRecord>('/api/license');
export const getApkStatus = () => apiGet<JsonRecord>('/api/mobile/apk');
export const syncApk = (sidecarUrl?: string) =>
  apiPost<JsonRecord>('/api/mobile/apk', sidecarUrl ? { sidecar_url: sidecarUrl } : {}, 300000);
export const downloadApk = () => apiDownload('/api/mobile/apk/download', 'vortex.apk');
export const getDebStatus = () => apiGet<JsonRecord>('/api/desktop/deb');
export const buildDeb = () => apiPost<JsonRecord>('/api/desktop/deb', {}, 300000);
export const downloadDeb = (filename: string) =>
  apiDownload('/api/desktop/deb/download', filename || 'vortex-terminal.deb');

/* ---------------- Real PTY sessions ---------------- */

export const listSessions = () => apiGet<JsonRecord>('/api/sessions');
export const openSession = (shell?: string) =>
  apiPost<JsonRecord>('/api/sessions', shell ? { shell } : {});
export const sendSessionInput = (id: string, data: string) =>
  apiPost<JsonRecord>(`/api/sessions/${encodeURIComponent(id)}/input`, { data });
export const killSession = (id: string) =>
  apiPost<JsonRecord>(`/api/sessions/${encodeURIComponent(id)}/kill`);
export const resizeSession = (id: string, cols: number, rows: number) =>
  apiPost<JsonRecord>(`/api/sessions/${encodeURIComponent(id)}/resize`, { cols, rows });
export const streamSession = (
  id: string, onEvent: (data: JsonRecord) => void, onError?: (err: Error) => void,
): StreamHandle => openEventStream(`/api/sessions/${encodeURIComponent(id)}/stream`, onEvent, onError);
