/* Turn execution helpers: run a turn, approve a plan, watch an operation.
   Mirrors the proven legacy flow: SSE first, then bounded polling. */
import {
  JsonRecord, TurnResult, OperationDocument,
  cancelOperation, getOperation, runTurn, apiPost, streamOperation,
} from './vortexApi';
import { isWeb } from './runtimeState';

export function conversationId(): string | undefined {
  try {
    return localStorage.getItem('vortex.conversationId') || undefined;
  } catch {
    return undefined;
  }
}

export function persistConversationId(id: string | undefined): void {
  if (!id) return;
  try {
    localStorage.setItem('vortex.conversationId', id);
  } catch {
    /* storage unavailable — turns still work */
  }
}

export async function executePlan(planId: string, approvalToken: string): Promise<OperationDocument> {
  const payload = await apiPost<{ operation?: OperationDocument } & JsonRecord>(
    '/api/execute', { plan_id: planId, approval_token: approvalToken, confirm: true }, 120000,
  );
  const operation = payload.operation as OperationDocument | undefined;
  if (!operation || typeof operation !== 'object' || !operation.id) {
    throw new Error('Sidecar did not return an operation.');
  }
  return operation;
}

export interface WatchOptions {
  onLive?: (operation: OperationDocument) => void;
  /** Extra seconds beyond the command budgets. Default 60, cap 3600 total. */
  slackSeconds?: number;
}

function isTerminal(status: unknown): boolean {
  return typeof status === 'string' && !['started', 'running'].includes(status);
}

function budgetsSeconds(operation: OperationDocument, turn?: TurnResult): number {
  const commands = (turn?.plan as JsonRecord | undefined)?.commands;
  const list = Array.isArray(commands) ? commands : [];
  const total = list.reduce((sum, item) => {
    const entry = (item && typeof item === 'object' ? item : {}) as JsonRecord;
    const seconds = Number(entry.timeout_seconds);
    return sum + (Number.isFinite(seconds) && seconds > 0 ? seconds : 30);
  }, 0);
  void operation;
  return total;
}

export async function watchOperation(
  operationId: string, turn?: TurnResult, options: WatchOptions = {},
): Promise<OperationDocument> {
  const slack = Math.max(30, Math.min(Number(options.slackSeconds || 60), 900));
  const budget = Math.min(3600, Math.max(90, budgetsSeconds({ id: operationId } as OperationDocument, turn) + slack));
  const deadline = Date.now() + budget * 1000;

  // 1. Server-sent events first (fast path with live output).
  if (typeof EventSource !== 'undefined') {
    try {
      const streamed = await new Promise<OperationDocument | null>((resolve) => {
        const handle = streamOperation(
          operationId,
          (data) => {
            const operation = (data.operation || data) as OperationDocument;
            if (operation && typeof operation === 'object') {
              if (isTerminal(operation.status)) {
                handle.close();
                resolve(operation);
              } else {
                options.onLive?.(operation);
              }
            }
          },
          () => {
            handle.close();
            resolve(null);
          },
        );
        window.setTimeout(() => {
          handle.close();
          resolve(null);
        }, 65000);
      });
      if (streamed) return streamed;
    } catch {
      /* fall through to polling */
    }
  }

  // 2. Bounded polling fallback.
  let last: OperationDocument = { id: operationId, status: 'running' } as OperationDocument;
  while (Date.now() < deadline) {
    await new Promise((resolve) => { window.setTimeout(resolve, 1000); });
    try {
      const payload = await getOperation(operationId);
      const operation = (payload.operation || {}) as OperationDocument;
      if (!operation || typeof operation !== 'object') continue;
      last = operation;
      if (isTerminal(operation.status)) return operation;
      options.onLive?.(operation);
    } catch (err) {
      throw err instanceof Error ? err : new Error(String(err));
    }
  }
  return last;
}

export async function approveMutation(
  operationId: string, approvalToken: string, preflightDigest: string,
): Promise<OperationDocument> {
  const result = await apiPost<{ operation?: OperationDocument } & JsonRecord>(
    `/api/operations/${encodeURIComponent(operationId)}/approve`,
    { confirm: true, approval_token: approvalToken, preflight_digest: preflightDigest },
    120000,
  );
  const operation = result.operation as OperationDocument | undefined;
  if (!operation || typeof operation !== 'object') throw new Error('Approval did not return an operation.');
  return operation;
}

export async function cancelRunningOperation(operationId: string): Promise<void> {
  await cancelOperation(operationId);
}

export async function startTurn(request: string, engagementId?: string): Promise<TurnResult> {
  if (isWeb()) {
    // WEB_CLOUD runtime: the Vercel backend is stateless, so the browser
    // supplies its own bounded history window plus any relevant past
    // answers it holds (real historical candidates for cloud arbitration),
    // then persists both sides of the exchange locally.
    const { recentHistory, retrieveHistoricalCandidates, appendWebMessage } = await import('./webConversations');
    const cid = conversationId();
    const turn = await runTurn(request, {
      conversation_id: cid,
      history: recentHistory(cid),
      historical_candidates: retrieveHistoricalCandidates(request),
    });
    const conversation = (turn.conversation || {}) as JsonRecord;
    const resolvedId = typeof conversation.id === 'string' && conversation.id ? conversation.id : cid;
    if (resolvedId) {
      persistConversationId(resolvedId);
      try {
        appendWebMessage(resolvedId, 'user', request);
        const reply = String(turn.reply || turn.explanation || '');
        if (reply) {
          const message = (turn.message || {}) as JsonRecord;
          appendWebMessage(resolvedId, 'vortex', reply, (message.meta || {}) as JsonRecord);
        }
      } catch { /* storage unavailable — the turn itself still succeeded */ }
    }
    return turn;
  }
  const turn = await runTurn(request, {
    engagement_id: engagementId,
    conversation_id: conversationId(),
  });
  const conversation = (turn.conversation || {}) as JsonRecord;
  if (typeof conversation.id === 'string') persistConversationId(conversation.id);
  return turn;
}
