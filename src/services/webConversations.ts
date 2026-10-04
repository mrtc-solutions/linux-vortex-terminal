/* Web Mode conversation memory — stored in THIS browser only.
 *
 * The Vercel backend is stateless by design: it never stores chat
 * transcripts server-side, so one visitor can never read another
 * visitor's history (multi-user isolation by construction). The browser
 * owns its transcript, sends a bounded recent window with each turn, and
 * can offer its own past answers as historical candidates for real
 * server-side arbitration.
 *
 * Shapes mirror the sidecar's /api/conversations payloads so the existing
 * History UI works unchanged in Web Mode.
 */
import type { JsonRecord } from './vortexApi';

const STORE_KEY = 'vortex.web.conversations.v1';
const MAX_CONVERSATIONS = 40;
const MAX_MESSAGES = 120;

export interface WebMessage extends JsonRecord {
  id: string;
  role: 'user' | 'vortex';
  content: string;
  created_at: string;
  meta?: JsonRecord;
}

export interface WebConversation extends JsonRecord {
  id: string;
  title: string;
  status: 'active' | 'archived';
  storage: 'browser-local';
  created_at: string;
  updated_at: string;
  messages: WebMessage[];
}

interface StoreShape { conversations: WebConversation[] }

function readStore(): StoreShape {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (!raw) return { conversations: [] };
    const parsed = JSON.parse(raw) as StoreShape;
    if (parsed && Array.isArray(parsed.conversations)) return parsed;
  } catch { /* corrupted or unavailable storage: start clean */ }
  return { conversations: [] };
}

function writeStore(store: StoreShape): void {
  try {
    store.conversations = store.conversations.slice(0, MAX_CONVERSATIONS);
    localStorage.setItem(STORE_KEY, JSON.stringify(store));
  } catch { /* quota exceeded — history simply stops growing */ }
}

function nowIso(): string {
  return new Date().toISOString();
}

function newId(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

export function listWebConversations(query = ''): WebConversation[] {
  const needle = query.trim().toLowerCase();
  const items = readStore().conversations
    .sort((a, b) => (a.updated_at < b.updated_at ? 1 : -1));
  if (!needle) return items;
  return items.filter((c) => c.title.toLowerCase().includes(needle)
    || c.messages.some((m) => m.content.toLowerCase().includes(needle)));
}

export function getWebConversation(id: string): WebConversation | null {
  return readStore().conversations.find((c) => c.id === id) || null;
}

export function createWebConversation(title: string): WebConversation {
  const store = readStore();
  const conversation: WebConversation = {
    id: newId('web'),
    title: (title || 'New conversation').slice(0, 80),
    status: 'active',
    storage: 'browser-local',
    created_at: nowIso(),
    updated_at: nowIso(),
    messages: [],
  };
  store.conversations.unshift(conversation);
  writeStore(store);
  return conversation;
}

export function deleteWebConversation(id: string): void {
  const store = readStore();
  store.conversations = store.conversations.filter((c) => c.id !== id);
  writeStore(store);
}

export function archiveWebConversation(id: string): WebConversation | null {
  const store = readStore();
  const conversation = store.conversations.find((c) => c.id === id) || null;
  if (conversation) {
    conversation.status = 'archived';
    conversation.updated_at = nowIso();
    writeStore(store);
  }
  return conversation;
}

export function editWebMessage(conversationId: string, messageId: string, content: string): WebMessage | null {
  const store = readStore();
  const conversation = store.conversations.find((c) => c.id === conversationId);
  const message = conversation?.messages.find((m) => m.id === messageId) || null;
  if (conversation && message) {
    message.content = content.slice(0, 16000);
    conversation.updated_at = nowIso();
    writeStore(store);
  }
  return message;
}

export function renameWebConversation(id: string, title: string): WebConversation | null {
  const store = readStore();
  const conversation = store.conversations.find((c) => c.id === id) || null;
  if (conversation) {
    conversation.title = (title || conversation.title).slice(0, 80);
    conversation.updated_at = nowIso();
    writeStore(store);
  }
  return conversation;
}

export function appendWebMessage(
  conversationId: string, role: 'user' | 'vortex', content: string, meta?: JsonRecord,
): WebConversation {
  const store = readStore();
  let conversation = store.conversations.find((c) => c.id === conversationId);
  if (!conversation) {
    conversation = {
      id: conversationId || newId('web'),
      title: (role === 'user' ? content.slice(0, 60) : 'New conversation') || 'New conversation',
      status: 'active',
      storage: 'browser-local',
      created_at: nowIso(),
      updated_at: nowIso(),
      messages: [],
    };
    store.conversations.unshift(conversation);
  }
  conversation.messages.push({
    id: newId('msg'), role, content: content.slice(0, 16000), created_at: nowIso(), meta,
  });
  conversation.messages = conversation.messages.slice(-MAX_MESSAGES);
  if (conversation.title === 'New conversation' && role === 'user') {
    conversation.title = content.slice(0, 60);
  }
  conversation.updated_at = nowIso();
  writeStore(store);
  return conversation;
}

/** Bounded recent history window for the current conversation. */
export function recentHistory(conversationId: string | undefined, limit = 12): { role: string; content: string }[] {
  if (!conversationId) return [];
  const conversation = getWebConversation(conversationId);
  if (!conversation) return [];
  return conversation.messages.slice(-limit).map((m) => ({ role: m.role, content: m.content }));
}

/** Naive-but-real historical candidate retrieval over the browser's own
 *  past answers: token overlap between the new request and the user turn
 *  that produced each stored answer. Top matches are offered to the
 *  server-side arbitrator as candidates (data only, never instructions). */
export function retrieveHistoricalCandidates(request: string, limit = 3): JsonRecord[] {
  const tokens = new Set(request.toLowerCase().split(/[^a-z0-9]+/).filter((t) => t.length > 2));
  if (tokens.size === 0) return [];
  const scored: { score: number; candidate: JsonRecord }[] = [];
  for (const conversation of readStore().conversations) {
    const messages = conversation.messages;
    for (let i = 0; i < messages.length - 1; i += 1) {
      const user = messages[i];
      const answer = messages[i + 1];
      if (user.role !== 'user' || answer.role !== 'vortex' || !answer.content) continue;
      const theirTokens = user.content.toLowerCase().split(/[^a-z0-9]+/).filter((t) => t.length > 2);
      if (theirTokens.length === 0) continue;
      const overlap = theirTokens.filter((t) => tokens.has(t)).length;
      const score = overlap / Math.max(tokens.size, theirTokens.length);
      if (score >= 0.45 && overlap >= 2) {
        const meta = (answer.meta || {}) as JsonRecord;
        const ai = (meta.ai || {}) as JsonRecord;
        scored.push({
          score,
          candidate: {
            answer: answer.content,
            relevance: Math.min(1, score),
            provider: String(ai.provider || 'browser-history'),
            model: String(ai.model || 'previous-turn'),
            timestamp: answer.created_at,
            verified: false,
            user_accepted: true,
          },
        });
      }
    }
  }
  return scored.sort((a, b) => b.score - a.score).slice(0, limit).map((s) => s.candidate);
}
