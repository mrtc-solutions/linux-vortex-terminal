/* Scope popup — engagement authorizations that gate assessment planning. */
import React, { useCallback, useEffect, useState } from 'react';
import { Crosshair, Loader2, RefreshCw } from 'lucide-react';
import { JsonRecord, closeEngagement, createEngagement, listEngagements } from '../../services/vortexApi';
import { DangerButton, EmptyLine, ErrorLine, GhostButton, PrimaryButton, Section, StateBadge, inputCls } from './common';

export const Scope: React.FC<{ onEngagementChange?: () => void }> = ({ onEngagementChange }) => {
  const [items, setItems] = useState<JsonRecord[]>([]);
  const [name, setName] = useState('');
  const [authorization, setAuthorization] = useState('');
  const [targets, setTargets] = useState('');
  const [classes, setClasses] = useState('reconnaissance');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setError('');
    try {
      const payload = await listEngagements();
      setItems(Array.isArray(payload.engagements) ? payload.engagements as JsonRecord[] : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const create = async () => {
    if (busy) return;
    const targetList = targets.split('\n').map((line) => line.trim()).filter(Boolean);
    if (targetList.length === 0) {
      setError('Add at least one target (one per line).');
      return;
    }
    setBusy('create');
    setError('');
    try {
      await createEngagement({
        name: name.trim() || 'Authorized assessment',
        authorization: authorization.trim() || undefined,
        targets: targetList,
        classes: classes.split(',').map((entry) => entry.trim()).filter(Boolean),
      });
      setName('');
      setAuthorization('');
      setTargets('');
      await refresh();
      onEngagementChange?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('');
    }
  };

  const close = async (id: string) => {
    if (busy) return;
    setBusy(`close-${id}`);
    setError('');
    try {
      await closeEngagement(id);
      await refresh();
      onEngagementChange?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="p-4 space-y-4 text-stone-300">
      <div className="flex items-center gap-2">
        <Crosshair className="w-4 h-4 text-[var(--theme-primary)]" />
        <span className="text-[12px] font-bold text-stone-200">Engagement scope</span>
        <span className="flex-1" />
        <GhostButton onClick={() => { setLoading(true); void refresh(); }} disabled={loading}>
          <span className="flex items-center gap-1"><RefreshCw className="w-3 h-3" />Refresh</span>
        </GhostButton>
      </div>

      <ErrorLine message={error} />

      <Section title={`Authorizations (${items.length})`}>
        {loading && <EmptyLine message="Reading engagements…" />}
        {!loading && items.length === 0 && <EmptyLine message="No engagements. Assessment-class plans stay blocked until you authorize targets here." />}
        <div className="space-y-1.5">
          {items.map((item) => (
            <div key={String(item.id)} className="p-2 rounded bg-black/50 border border-[var(--theme-border)] space-y-1">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-bold text-[12px] text-stone-200">{String(item.name || 'Untitled')}</span>
                <StateBadge state={String(item.status || 'unknown')} />
                <span className="text-[10px] text-stone-500 font-mono">expires {String(item.expires_at || '?').slice(0, 16).replace('T', ' ')}</span>
              </div>
              <div className="text-[11px] text-stone-400 break-words">
                {(Array.isArray(item.targets) ? item.targets as unknown[] : []).map(String).join(', ') || '(no targets)'}
              </div>
              <div className="text-[10px] text-stone-600">
                classes: {(Array.isArray(item.classes) ? item.classes as unknown[] : []).map(String).join(', ') || '—'}
                {item.authorization ? ` · auth: ${String(item.authorization).slice(0, 120)}` : ''}
              </div>
              {String(item.status || '') === 'active' && (
                <DangerButton onClick={() => void close(String(item.id))} disabled={!!busy}>
                  {busy === `close-${String(item.id)}` ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Close engagement'}
                </DangerButton>
              )}
            </div>
          ))}
        </div>
      </Section>

      <Section title="New authorization">
        <div className="space-y-1.5">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name (e.g. Home lab assessment)" spellCheck={false} className={inputCls} />
          <textarea
            value={targets}
            onChange={(e) => setTargets(e.target.value)}
            placeholder={'Targets — one per line (e.g. 192.168.1.0/24) — ONLY systems you own or are authorized to test'}
            rows={3}
            spellCheck={false}
            className={`${inputCls} font-mono resize-y`}
          />
          <input value={classes} onChange={(e) => setClasses(e.target.value)} placeholder="Classes, comma-separated (e.g. reconnaissance, vulnerability-scan)" spellCheck={false} className={inputCls} />
          <input value={authorization} onChange={(e) => setAuthorization(e.target.value)} placeholder="Authorization reference (optional — ticket, contract, owner)" spellCheck={false} className={inputCls} />
          <PrimaryButton onClick={() => void create()} disabled={!!busy}>
            {busy === 'create' ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Authorize engagement'}
          </PrimaryButton>
          <div className="text-[10px] text-stone-600">
            Expires automatically after 24h. Only listed targets may be planned against; everything else stays blocked.
          </div>
        </div>
      </Section>
    </div>
  );
};
