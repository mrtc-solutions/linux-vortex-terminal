/* Memory popup — durable operator + task knowledge (7 real kinds). */
import React, { useCallback, useEffect, useState } from 'react';
import { Database, Loader2, RefreshCw } from 'lucide-react';
import { JsonRecord, listMemories, saveMemory } from '../../services/vortexApi';
import { EmptyLine, ErrorLine, GhostButton, PrimaryButton, Section, inputCls } from './common';

const KINDS = ['conversation', 'task', 'knowledge', 'tool', 'agent', 'experience', 'procedure'];

export const Memory: React.FC = () => {
  const [items, setItems] = useState<JsonRecord[]>([]);
  const [title, setTitle] = useState('');
  const [body, setBody] = useState('');
  const [kind, setKind] = useState('knowledge');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setError('');
    try {
      const payload = await listMemories();
      setItems(Array.isArray(payload.memories) ? payload.memories as JsonRecord[] : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const save = async () => {
    if (busy) return;
    if (!title.trim() || !body.trim()) {
      setError('A memory needs both a title and a body.');
      return;
    }
    setBusy(true);
    setError('');
    try {
      await saveMemory(title.trim(), body.trim(), kind);
      setTitle('');
      setBody('');
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-4 space-y-4 text-stone-300">
      <div className="flex items-center gap-2">
        <Database className="w-4 h-4 text-[var(--theme-primary)]" />
        <span className="text-[12px] font-bold text-stone-200">Memory</span>
        <span className="flex-1" />
        <GhostButton onClick={() => { setLoading(true); void refresh(); }} disabled={loading}>
          <span className="flex items-center gap-1"><RefreshCw className="w-3 h-3" />Refresh</span>
        </GhostButton>
      </div>

      <ErrorLine message={error} />

      <Section title={`Stored (${items.length})`}>
        {loading && <EmptyLine message="Reading memory…" />}
        {!loading && items.length === 0 && <EmptyLine message="Nothing stored yet. Completed tasks record themselves here automatically." />}
        <div className="space-y-1.5 max-h-72 overflow-y-auto pr-1">
          {items.map((item) => (
            <div key={String(item.id)} className="p-2 rounded bg-black/50 border border-[var(--theme-border)] space-y-0.5">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-bold text-[12px] text-stone-200">{String(item.title || 'Untitled')}</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded border border-[var(--theme-border)] text-[var(--theme-primary)]">
                  {String(item.kind || '?')}
                </span>
                <span className="text-[10px] text-stone-600 font-mono">
                  {String(item.created_at || '').slice(0, 16).replace('T', ' ')}
                </span>
              </div>
              <div className="text-[11px] text-stone-400 whitespace-pre-wrap break-words">
                {String(item.body || '').slice(0, 600)}
              </div>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Save a memory">
        <div className="space-y-1.5">
          <div className="flex gap-1.5">
            <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Title" spellCheck={false} className={inputCls} />
            <select value={kind} onChange={(e) => setKind(e.target.value)} className={`${inputCls} !w-36 shrink-0`}>
              {KINDS.map((entry) => <option key={entry} value={entry}>{entry}</option>)}
            </select>
          </div>
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            placeholder="What should VORTEX remember? Facts, preferences, runbooks…"
            rows={3}
            spellCheck={false}
            className={`${inputCls} resize-y`}
          />
          <PrimaryButton onClick={() => void save()} disabled={busy}>
            {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Save memory'}
          </PrimaryButton>
        </div>
      </Section>
    </div>
  );
};
