/* Conversations popup — resume, rename, archive, export, delete. */
import React, { useCallback, useEffect, useState } from 'react';
import { Download, History as HistoryIcon, Loader2, RefreshCw } from 'lucide-react';
import {
  JsonRecord, archiveConversation, createConversation, deleteConversation,
  exportConversation, listConversations, renameConversation,
} from '../../services/vortexApi';
import { DangerButton, EmptyLine, ErrorLine, GhostButton, PrimaryButton, Section, StateBadge, inputCls } from './common';

export const History: React.FC<{ onClose: () => void; onSelect: (id: string) => Promise<void> }> = ({ onClose, onSelect }) => {
  const [items, setItems] = useState<JsonRecord[]>([]);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameText, setRenameText] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setError('');
    try {
      const payload = await listConversations();
      setItems(Array.isArray(payload.conversations) ? payload.conversations as JsonRecord[] : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const run = async (label: string, action: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(label);
    setError('');
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('');
    }
  };

  const resume = async (id: string) => {
    await run(`resume-${id}`, async () => { await onSelect(id); onClose(); });
  };

  const startNew = async () => {
    if (busy) return;
    setBusy('new');
    setError('');
    try {
      const payload = await createConversation('New conversation');
      const created = (payload.conversation || {}) as JsonRecord;
      if (typeof created.id !== 'string') throw new Error('Server did not return a conversation ID.');
      await onSelect(created.id);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy('');
    }
  };

  const commitRename = async (id: string) => {
    const title = renameText.trim();
    if (!title) {
      setRenaming(null);
      return;
    }
    setRenaming(null);
    await run(`rename-${id}`, () => renameConversation(id, title));
  };

  return (
    <div className="p-4 space-y-4 text-stone-300">
      <div className="flex items-center gap-2">
        <HistoryIcon className="w-4 h-4 text-[var(--theme-primary)]" />
        <span className="text-[12px] font-bold text-stone-200">Conversations</span>
        <span className="flex-1" />
        <PrimaryButton onClick={() => void startNew()} disabled={!!busy}>
          {busy === 'new' ? <Loader2 className="w-3 h-3 animate-spin" /> : 'New'}
        </PrimaryButton>
        <GhostButton onClick={() => { setLoading(true); void refresh(); }} disabled={loading}>
          <span className="flex items-center gap-1"><RefreshCw className="w-3 h-3" />Refresh</span>
        </GhostButton>
      </div>

      <ErrorLine message={error} />

      <Section title={`Threads (${items.length})`}>
        {loading && <EmptyLine message="Reading conversations…" />}
        {!loading && items.length === 0 && <EmptyLine message="No conversations yet. Your next terminal turn starts one." />}
        <div className="space-y-1.5">
          {items.map((item) => {
            const id = String(item.id);
            return (
              <div key={id} className="p-2 rounded bg-black/50 border border-[var(--theme-border)] space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  {renaming === id ? (
                    <input
                      value={renameText}
                      onChange={(e) => setRenameText(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') void commitRename(id);
                        if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setRenaming(null); }
                      }}
                      autoFocus
                      spellCheck={false}
                      className={`${inputCls} !w-48`}
                    />
                  ) : (
                    <span className="font-bold text-[12px] text-stone-200">{String(item.title || 'Untitled')}</span>
                  )}
                  <StateBadge state={String(item.status || 'unknown')} />
                  <span className="text-[10px] text-stone-600 font-mono">
                    {String(item.updated_at || '').slice(0, 16).replace('T', ' ')}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 flex-wrap pt-0.5">
                  <PrimaryButton disabled={!!busy} onClick={() => void resume(id)}>Resume</PrimaryButton>
                  <GhostButton onClick={() => { setRenaming(id); setRenameText(String(item.title || '')); }}>Rename</GhostButton>
                  <GhostButton onClick={() => { void exportConversation(id).catch((err: unknown) => setError(err instanceof Error ? err.message : String(err))); }}>
                    <span className="flex items-center gap-1"><Download className="w-3 h-3" />Export</span>
                  </GhostButton>
                  <GhostButton onClick={() => void run(`archive-${id}`, () => archiveConversation(id))} disabled={!!busy}>
                    {busy === `archive-${id}` ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Archive'}
                  </GhostButton>
                  <DangerButton onClick={() => void run(`delete-${id}`, () => deleteConversation(id))} disabled={!!busy}>
                    {busy === `delete-${id}` ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Delete'}
                  </DangerButton>
                </div>
              </div>
            );
          })}
        </div>
      </Section>
    </div>
  );
};
