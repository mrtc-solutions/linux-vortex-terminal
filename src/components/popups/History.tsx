/* Conversations popup — resume, rename, archive, export, delete. */
import React, { useCallback, useEffect, useState, useRef } from 'react';
import { Download, History as HistoryIcon, Loader2, RefreshCw } from 'lucide-react';
import {
  JsonRecord, archiveConversation, createConversation, deleteConversation,
  exportConversation, listConversations, renameConversation, getConversation, editMessage,
} from '../../services/vortexApi';
import { DangerButton, EmptyLine, ErrorLine, GhostButton, PrimaryButton, Section, StateBadge, inputCls } from './common';

export const History: React.FC<{ onClose: () => void; onSelect: (id: string) => Promise<void> }> = ({ onClose, onSelect }) => {
  const requestGeneration = useRef(0);
  const [query, setQuery] = useState('');
  const [thread, setThread] = useState<{ id: string; messages: JsonRecord[] } | null>(null);
  const [editing, setEditing] = useState<string | null>(null);
  const [editedText, setEditedText] = useState('');
  const [items, setItems] = useState<JsonRecord[]>([]);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameText, setRenameText] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const generation = ++requestGeneration.current;
    setError('');
    try {
      const payload = await listConversations(query.trim());
      if (generation !== requestGeneration.current) return;
      setItems(Array.isArray(payload.conversations) ? payload.conversations as JsonRecord[] : []);
    } catch (err) {
      if (generation === requestGeneration.current) setError(err instanceof Error ? err.message : String(err));
    } finally {
      if (generation === requestGeneration.current) setLoading(false);
    }
  }, [query]);

  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), query ? 200 : 0);
    return () => { window.clearTimeout(timer); requestGeneration.current += 1; };
  }, [refresh, query]);

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

  const inspect = (id: string) => run(`read-${id}`, async () => {
    const payload = await getConversation(id);
    setThread({ id, messages: Array.isArray(payload.messages) ? payload.messages as JsonRecord[] : [] });
    setEditing(null);
  });

  const branch = () => run('branch', async () => {
    if (!thread || !editing || !editedText.trim()) throw new Error('Enter a non-empty instruction.');
    const payload = await editMessage(thread.id, editing, editedText.trim());
    const conversation = payload.conversation as JsonRecord;
    if (typeof conversation?.id !== 'string') throw new Error('No branch returned.');
    // The backend preserves the original conversation. Selecting uses the same
    // busy/approval guard and transcript loader as Resume.
    await onSelect(conversation.id);
    onClose();
  });

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

      <input aria-label="Search conversations" placeholder="Search titles and saved messages…" value={query} onChange={e => setQuery(e.target.value)} className={inputCls} />
      {thread && <Section title="Saved messages — editing creates a new branch">
        {thread.messages.filter(m => !m.superseded_by).map(message => <div key={String(message.id)} className="border-b border-[var(--theme-border)] py-2 space-y-2">
          {editing === message.id ? <>
            <textarea aria-label="Edit instruction" className={inputCls} value={editedText} onChange={e => setEditedText(e.target.value)}
              onKeyDown={e => { if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setEditing(null); } }} />
            <PrimaryButton disabled={!!busy || !editedText.trim()} onClick={() => void branch()}>Save & Branch</PrimaryButton>
            <GhostButton disabled={!!busy} onClick={() => setEditing(null)}>Cancel edit</GhostButton>
          </> : <>
            <p className="whitespace-pre-wrap select-text">{String(message.content || '')}</p>
            {message.role === 'user' && <GhostButton disabled={!!busy} onClick={() => { setEditing(String(message.id)); setEditedText(String(message.content || '')); }}>Edit & Branch</GhostButton>}
          </>}
        </div>)}
      </Section>}
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
                      aria-label="Rename conversation"
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
                    <button
                      type="button"
                      disabled={!!busy}
                      onClick={() => void resume(id)}
                      title="Open this conversation in the terminal canvas"
                      className="font-bold text-[12px] text-stone-200 hover:text-[var(--theme-primary)] cursor-pointer text-left"
                    >
                      {String(item.title || 'Untitled')}
                    </button>
                  )}
                  <StateBadge state={String(item.status || 'unknown')} />
                  <span className="text-[10px] text-stone-600 font-mono">
                    {String(item.updated_at || '').slice(0, 16).replace('T', ' ')}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 flex-wrap pt-0.5">
                  <PrimaryButton disabled={!!busy} onClick={() => void resume(id)}>Resume</PrimaryButton>
                  <GhostButton disabled={!!busy} onClick={() => void inspect(id)}>Read messages</GhostButton>
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
