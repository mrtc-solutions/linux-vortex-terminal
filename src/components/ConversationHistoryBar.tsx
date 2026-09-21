/* Always-visible conversation history strip. Clicking a thread resumes it
   in the terminal canvas — this is not decoration; it calls the sidecar. */
import React, { useCallback, useEffect, useState } from 'react';
import { History as HistoryIcon, Plus } from 'lucide-react';
import { JsonRecord, createConversation, listConversations } from '../services/vortexApi';
import { sound } from '../services/soundEffects';

interface ConversationHistoryBarProps {
  onSelect: (id: string) => Promise<void>;
  onOpenHistory: () => void;
}

export const ConversationHistoryBar: React.FC<ConversationHistoryBarProps> = ({ onSelect, onOpenHistory }) => {
  const [items, setItems] = useState<JsonRecord[]>([]);
  const [activeId, setActiveId] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const payload = await listConversations();
      const list = Array.isArray(payload.conversations) ? payload.conversations as JsonRecord[] : [];
      setItems(list.filter((item) => String(item.status || '') !== 'deleted').slice(0, 24));
      try {
        setActiveId(localStorage.getItem('vortex.conversationId') || '');
      } catch {
        setActiveId('');
      }
      setError('');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 8000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const pick = async (id: string) => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await onSelect(id);
      setActiveId(id);
      sound.playKeypress();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const startNew = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const payload = await createConversation('New conversation');
      const created = (payload.conversation || {}) as JsonRecord;
      if (typeof created.id !== 'string') throw new Error('Server did not return a conversation ID.');
      await onSelect(created.id);
      await refresh();
      sound.playKeypress();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="border-b border-[var(--theme-border)] bg-[var(--theme-surface)]/80 px-2 py-1.5 z-20">
      <div className="flex items-center gap-1.5 overflow-x-auto">
        <button
          type="button"
          onClick={onOpenHistory}
          title="Open full conversation history"
          aria-label="Open conversation history"
          className="flex items-center gap-1 px-2 py-0.5 rounded border border-[var(--theme-border)] text-stone-200 hover:text-[var(--theme-primary)] cursor-pointer text-[10px] font-bold shrink-0"
        >
          <HistoryIcon className="w-3 h-3" />
          <span>History</span>
        </button>
        <button
          type="button"
          onClick={() => void startNew()}
          disabled={busy}
          title="Start a new conversation"
          aria-label="New conversation"
          className="flex items-center gap-1 px-2 py-0.5 rounded border border-[var(--theme-border)] text-stone-200 hover:text-[var(--theme-primary)] disabled:opacity-40 cursor-pointer text-[10px] font-bold shrink-0"
        >
          <Plus className="w-3 h-3" />
          <span>New</span>
        </button>
        {items.length === 0 && (
          <span className="text-[10px] text-stone-500 px-1">No saved conversations yet.</span>
        )}
        {items.map((item) => {
          const id = String(item.id);
          const selected = id === activeId;
          return (
            <button
              key={id}
              type="button"
              disabled={busy}
              onClick={() => void pick(id)}
              title={`Resume ${String(item.title || 'Untitled')}`}
              className={`max-w-[10rem] truncate px-2 py-0.5 rounded border text-[10px] cursor-pointer shrink-0 ${
                selected
                  ? 'bg-[var(--theme-primary)] text-black border-[var(--theme-primary)] font-bold'
                  : 'bg-black/40 text-stone-300 border-[var(--theme-border)] hover:text-[var(--theme-primary)]'
              }`}
            >
              {String(item.title || 'Untitled')}
            </button>
          );
        })}
      </div>
      {error ? <div className="text-[10px] text-rose-400 px-1 pt-1">{error}</div> : null}
    </div>
  );
};
