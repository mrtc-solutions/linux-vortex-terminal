/* Host dependency inventory: present AND missing. Never silent-installs. */
import { useEffect, useMemo, useState } from 'react';
import { apiGet, apiPost, JsonRecord, refreshAll } from '../../services/vortexApi';
import { conversationId } from '../../services/turnRunner';
import { asRecord, ErrorLine, GhostButton, PrimaryButton, Section, StateBadge } from './common';

export function Dependencies({
  onOpenPopup,
  onDismissStartup,
}: {
  onOpenPopup: (kind: string, props?: JsonRecord) => void;
  onDismissStartup?: () => void;
}) {
  const [items, setItems] = useState<JsonRecord[]>([]);
  const [counts, setCounts] = useState<JsonRecord>({});
  const [proposal, setProposal] = useState<JsonRecord | null>(null);
  const [selected, setSelected] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [loaded, setLoaded] = useState(false);
  const [notice, setNotice] = useState('');
  const [filter, setFilter] = useState<'all' | 'present' | 'missing'>('all');
  const [packageName, setPackageName] = useState('');
  const [hideStartup, setHideStartup] = useState(false);

  const run = async (action: () => Promise<void>) => {
    setBusy(true); setError(''); setNotice('');
    try { await action(); } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { setBusy(false); }
  };

  const refresh = (rescanHost = false) => run(async () => {
    if (rescanHost) await refreshAll();
    const data = await apiGet<JsonRecord>('/api/dependencies');
    const deps = asRecord(data.dependencies);
    const catalog = Array.isArray(deps.items) ? deps.items.map(asRecord) : [];
    if (!catalog.length && !Array.isArray(deps.missing)) {
      throw new Error('Invalid dependency inventory response.');
    }
    const missing = Array.isArray(deps.missing) ? deps.missing.map(asRecord) : catalog.filter((row) => !row.installed);
    const present = Array.isArray(deps.present) ? deps.present.map(asRecord) : catalog.filter((row) => row.installed);
    const merged = catalog.length ? catalog : [...present, ...missing];
    setItems(merged);
    setCounts(asRecord(deps.counts));
    setLoaded(true);
    setProposal(null);
    setNotice(rescanHost ? 'Host rescan finished. Inventory is from this machine, not cache decoration.' : '');
  });

  useEffect(() => { void refresh(); }, []);

  const visible = useMemo(() => {
    if (filter === 'present') return items.filter((item) => item.installed);
    if (filter === 'missing') return items.filter((item) => !item.installed);
    return items;
  }, [items, filter]);

  const review = (id: string) => run(async () => {
    setProposal(null);
    const data = await apiGet<JsonRecord>(`/api/dependencies/proposal?id=${encodeURIComponent(id)}`);
    setSelected(id); setProposal(asRecord(data.install));
  });

  const plan = () => run(async () => {
    const data = await apiPost<JsonRecord>('/api/dependencies/plan', { id: selected, conversation_id: conversationId() });
    if (!data.planned || !asRecord(data.plan).id) {
      throw new Error(String(asRecord(data.install).message || 'No reviewed install plan is available.'));
    }
    onOpenPopup('approvals', {
      plan: data.plan, guardian: data.guardian,
      onApproved: (op: JsonRecord) => { setNotice(`Installation operation: ${String(op.status || 'unknown')}. Refresh to rescan.`); },
      onRejected: () => setNotice('Installation rejected. Nothing was executed.'),
    });
  });

  const planPackage = () => run(async () => {
    const name = packageName.trim().toLowerCase();
    if (!name) throw new Error('Enter one exact Debian package name.');
    const data = await apiPost<JsonRecord>('/api/dependencies/plan', { package: name, conversation_id: conversationId() });
    if (!data.planned || !asRecord(data.plan).id) {
      throw new Error(String(asRecord(data.install).message || 'No reviewed package plan is available.'));
    }
    onOpenPopup('approvals', {
      plan: data.plan, guardian: data.guardian,
      onApproved: (op: JsonRecord) => { setNotice(`Installation operation: ${String(op.status || 'unknown')}. Refresh to rescan.`); },
      onRejected: () => setNotice('Installation rejected. Nothing was executed.'),
    });
  });

  const persistHideStartup = (value: boolean) => {
    setHideStartup(value);
    try { localStorage.setItem('vortex.deps-window-dismissed', value ? '1' : '0'); } catch { /* */ }
    onDismissStartup?.();
  };

  return (
    <div className="p-4 space-y-3 text-stone-300">
      <p className="text-[11px] text-stone-500 leading-relaxed">
        This window lists what is already on this host and what is missing. Apt packages become a
        Guardian-reviewed plan. Local LLM weights are <span className="text-stone-300">not</span> in
        GitHub or the .deb — download them yourself or import a file, then tap Refresh.
      </p>
      <div className="flex flex-wrap gap-2">
        <GhostButton disabled={busy} onClick={() => void refresh(false)}>Refresh</GhostButton>
        <GhostButton disabled={busy} onClick={() => void refresh(true)}>Rescan host</GhostButton>
        <GhostButton disabled={busy} onClick={() => onOpenPopup('models')}>Open Models (import GGUF)</GhostButton>
      </div>
      <ErrorLine message={error} />
      {busy && <p role="status">Loading dependency data…</p>}
      {notice && <p role="status">{notice}</p>}
      {error && (
        <p className="text-[11px] text-stone-500">
          If a probe failed, tap Refresh or Rescan host. Vortex Terminal never pretends a missing tool is installed.
        </p>
      )}
      {loaded && (
        <p className="text-[11px] text-stone-400">
          {String(counts.installed || 0)}/{String(counts.total || items.length)} present · {String(counts.missing || 0)} missing · auto_install=no
        </p>
      )}
      <div className="flex flex-wrap gap-1">
        {(['all', 'present', 'missing'] as const).map((key) => (
          <button
            key={key}
            type="button"
            onClick={() => setFilter(key)}
            className={`px-2 py-0.5 rounded border text-[10px] uppercase cursor-pointer ${
              filter === key
                ? 'border-[var(--theme-primary)] text-[var(--theme-primary)]'
                : 'border-[var(--theme-border)] text-stone-400'
            }`}
          >
            {key}
          </button>
        ))}
      </div>
      {loaded && !visible.length && <p>No catalog items match this filter on this host.</p>}
      {visible.map((item) => (
        <div key={String(item.id)} className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--theme-border)] py-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-stone-200">{String(item.title || item.id)}</span>
              <StateBadge state={item.installed ? 'installed' : String(item.state || 'missing')} />
            </div>
            <div className="text-[10px] text-stone-500">
              {String(item.kind || '')} · {String(item.method || '')} · {String(item.role || '')}
            </div>
          </div>
          <GhostButton disabled={busy} onClick={() => void review(String(item.id))}>
            {item.installed ? 'Inspect' : (item.method === 'apt' ? 'Review install' : 'How to obtain')}
          </GhostButton>
        </div>
      ))}
      <Section title="Manual Debian package">
        <p className="text-[11px] text-stone-500">One exact package name becomes a Guardian-reviewed apt plan. Root stays with the OS. Never start Vortex Terminal with sudo.</p>
        <div className="flex flex-wrap gap-2">
          <input
            aria-label="Debian package name"
            value={packageName}
            onChange={(event) => setPackageName(event.target.value)}
            placeholder="e.g. nmap"
            className="flex-1 min-w-40 bg-black/60 border border-[var(--theme-border)] rounded px-2 py-1 text-[12px] text-stone-200"
          />
          <PrimaryButton disabled={busy} onClick={() => void planPackage()}>Create reviewed install plan</PrimaryButton>
        </div>
      </Section>
      {proposal && (
        <Section title={String(proposal.title || selected)}>
          <p>{String(proposal.message || '')}</p>
          <p className="break-all">Source: {String(proposal.source || 'Not supplied')} · License: {String(proposal.license || 'Not supplied')}</p>
          <pre className="whitespace-pre-wrap break-all">{Array.isArray(proposal.commands) ? proposal.commands.map(String).join('\n') : 'No commands supplied.'}</pre>
          {proposal.method === 'apt' && !!proposal.plan_request && !proposal.installed
            ? <PrimaryButton disabled={busy} onClick={() => void plan()}>Create reviewed install plan</PrimaryButton>
            : <p>Operator-installed item. Vortex Terminal will not download or execute these instructions.</p>}
        </Section>
      )}
      <label className="flex items-center gap-2 text-[11px] text-stone-500">
        <input type="checkbox" checked={hideStartup} onChange={(event) => persistHideStartup(event.target.checked)} />
        Do not open this window automatically on startup
      </label>
    </div>
  );
}
