/* Dependency proposals never execute directly: execution uses Guardian review. */
import { useEffect, useState } from 'react';
import { apiGet, apiPost, JsonRecord } from '../../services/vortexApi';
import { conversationId } from '../../services/turnRunner';
import { asRecord, ErrorLine, GhostButton, PrimaryButton, Section } from './common';

export function Dependencies({ onOpenPopup }: { onOpenPopup: (kind: string, props?: JsonRecord) => void }) {
  const [items, setItems] = useState<JsonRecord[]>([]);
  const [proposal, setProposal] = useState<JsonRecord | null>(null);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [notice, setNotice] = useState('');
  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError(''); setNotice('');
    try { await action(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  };
  const refresh = () => run(async () => {
    const data = await apiGet<JsonRecord>('/api/dependencies');
    const missing = asRecord(data.dependencies).missing;
    if (!Array.isArray(missing)) throw new Error('Invalid dependency inventory response.');
    setItems(missing.map(asRecord)); setLoaded(true); setProposal(null);
  });
  useEffect(() => { void refresh(); }, []);
  const review = (id: string) => run(async () => {
    setProposal(null);
    const data = await apiGet<JsonRecord>(`/api/dependencies/proposal?id=${encodeURIComponent(id)}`);
    setSelected(id); setProposal(asRecord(data.install));
  });
  const plan = () => run(async () => {
    const data = await apiPost<JsonRecord>('/api/dependencies/plan', { id: selected, conversation_id: conversationId() });
    if (!data.planned || !asRecord(data.plan).id) throw new Error(String(asRecord(data.install).message || 'No reviewed install plan is available.'));
    onOpenPopup('approvals', { plan: data.plan, guardian: data.guardian,
      onApproved: (op: JsonRecord) => { setNotice(`Installation operation: ${String(op.status || 'unknown')}. Refresh to rescan.`); },
      onRejected: () => setNotice('Installation rejected. Nothing was executed.'),
    });
  });
  return <div className="p-4 space-y-3 text-stone-300">
    <GhostButton disabled={busy} onClick={() => void refresh()}>Refresh dependencies</GhostButton>
    <ErrorLine message={error} />
    {busy && <p role="status">Loading dependency data…</p>}
    {notice && <p role="status">{notice}</p>}
    {loaded && !items.length && <p>No missing catalog items on this host.</p>}
    {items.map(item => <div key={String(item.id)} className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--theme-border)] py-2">
      <span>{String(item.title || item.id)} · {String(item.method || '')}</span>
      <GhostButton disabled={busy} onClick={() => void review(String(item.id))}>Review {String(item.title || item.id)}</GhostButton>
    </div>)}
    {proposal && <Section title={String(proposal.title || selected)}>
      <p>{String(proposal.message || '')}</p>
      <p className="break-all">Source: {String(proposal.source || 'Not supplied')} · License: {String(proposal.license || 'Not supplied')}</p>
      <pre className="whitespace-pre-wrap break-all">{Array.isArray(proposal.commands) ? proposal.commands.map(String).join('\n') : 'No commands supplied.'}</pre>
      {proposal.method === 'apt' && !!proposal.plan_request && !proposal.installed
        ? <PrimaryButton disabled={busy} onClick={() => void plan()}>Create reviewed install plan</PrimaryButton>
        : <p>Operator-installed item. Vortex will not download or execute these instructions.</p>}
    </Section>}
  </div>;
}
