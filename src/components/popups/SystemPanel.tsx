/* System popup — real host/service health, audit verification, rescan. */
import React, { useCallback, useEffect, useState } from 'react';
import { Activity, Loader2, RefreshCw, ShieldCheck } from 'lucide-react';
import { JsonRecord, getSystemHealth, refreshAll, verifyAudit } from '../../services/vortexApi';
import { EmptyLine, ErrorLine, GhostButton, Section, StateBadge, asRecord } from './common';

function kv(label: string, value: string): React.ReactNode {
  return (
    <div className="flex items-start gap-2 text-[11px]">
      <span className="text-stone-500 w-28 shrink-0">{label}</span>
      <span className="text-stone-200 break-all">{value}</span>
    </div>
  );
}

export const SystemPanel: React.FC = () => {
  const [health, setHealth] = useState<JsonRecord | null>(null);
  const [audit, setAudit] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setError('');
    try {
      const payload = await getSystemHealth();
      setHealth(asRecord(payload.health) as JsonRecord);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const run = async (label: string, action: () => Promise<unknown>, done?: (result: unknown) => void) => {
    if (busy) return;
    setBusy(label);
    setError('');
    try {
      const result = await action();
      done?.(result);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('');
    }
  };

  const host = asRecord(health?.host) as JsonRecord;
  const distribution = asRecord(host.distribution) as JsonRecord;
  const components = asRecord(health?.components);
  const services = asRecord(health?.services);
  const probes = asRecord(health?.probes);

  return (
    <div className="p-4 space-y-4 text-stone-300">
      <div className="flex items-center gap-2">
        <Activity className="w-4 h-4 text-[var(--theme-primary)]" />
        <span className="text-[12px] font-bold text-stone-200">System health</span>
        <span className="flex-1" />
        <GhostButton onClick={() => { setLoading(true); void refresh(); }} disabled={loading || !!busy}>
          <span className="flex items-center gap-1"><RefreshCw className="w-3 h-3" />Refresh</span>
        </GhostButton>
      </div>

      <ErrorLine message={error} />
      {loading && !health && <EmptyLine message="Probing the host…" />}

      {health && (
        <Section title="Host">
          <div className="p-2 rounded bg-black/50 border border-[var(--theme-border)] space-y-1">
            {kv('distro', String(distribution.pretty_name || distribution.id || 'unknown'))}
            {kv('kernel', String(host.kernel || 'unknown'))}
            {kv('arch', String(host.architecture || 'unknown'))}
            {kv('cwd', String(host.cwd || 'unknown'))}
            {kv('shell', String(host.shell || 'unknown'))}
            {kv('container', String(host.container ?? 'unknown'))}
            {kv('support tier', String(host.support_tier || 'unknown'))}
          </div>
        </Section>
      )}

      {Object.keys(components).length > 0 && (
        <Section title="Components">
          <div className="grid grid-cols-1 gap-1.5">
            {Object.entries(components).map(([name, detail]) => {
              const item = asRecord(detail);
              const extra = [item.runtime, item.path, item.available, item.version]
                .filter((value) => value !== undefined && value !== null && String(value).length > 0)
                .map((value) => String(value));
              return (
                <div key={name} className="flex items-center gap-2 p-1.5 rounded bg-black/50 border border-[var(--theme-border)] text-[11px]">
                  <span className="text-stone-200 font-bold">{name.replace(/_/g, ' ')}</span>
                  <StateBadge state={String(item.state || 'unknown')} />
                  {extra.length ? <span className="text-stone-500 font-mono truncate">{extra.slice(0, 3).join(' · ')}</span> : null}
                </div>
              );
            })}
          </div>
        </Section>
      )}

      {Object.keys(services).length > 0 && (
        <Section title="Services">
          <div className="grid grid-cols-1 gap-1.5">
            {Object.entries(services).map(([name, detail]) => (
              <div key={name} className="flex items-center gap-2 p-1.5 rounded bg-black/50 border border-[var(--theme-border)] text-[11px]">
                <span className="text-stone-200 font-bold">{name}</span>
                <StateBadge state={String(asRecord(detail).state || asRecord(detail).status || 'unknown')} />
                {asRecord(detail).reason ? <span className="text-stone-500">{String(asRecord(detail).reason)}</span> : null}
              </div>
            ))}
          </div>
        </Section>
      )}

      {Object.keys(probes).length > 0 && (
        <Section title="Probes">
          <div className="p-2 rounded bg-black/50 border border-[var(--theme-border)] space-y-1">
            {Object.entries(probes).slice(0, 24).map(([name, value]) => (
              <div key={name}>{kv(name, typeof value === 'object' ? JSON.stringify(value).slice(0, 200) : String(value))}</div>
            ))}
          </div>
        </Section>
      )}

      <Section title="Integrity & rescan">
        <div className="flex items-center gap-2 flex-wrap">
          <GhostButton
            onClick={() => void run('audit', verifyAudit, (result) => {
              const auditResult = asRecord((result as JsonRecord).audit);
              setAudit(`chain valid: ${String(auditResult.valid ?? auditResult.ok ?? '?')} · checked: ${String(auditResult.checked ?? auditResult.records ?? auditResult.count ?? '?')} · head ${String(auditResult.head ?? '').slice(0, 16)}`);
            })}
            disabled={!!busy}
          >
            <span className="flex items-center gap-1">
              {busy === 'audit' ? <Loader2 className="w-3 h-3 animate-spin" /> : <ShieldCheck className="w-3 h-3" />}
              Verify audit chain
            </span>
          </GhostButton>
          <GhostButton onClick={() => void run('refresh', refreshAll)} disabled={!!busy}>
            <span className="flex items-center gap-1">
              {busy === 'refresh' ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
              Rescan everything
            </span>
          </GhostButton>
        </div>
        {audit && <div className="text-[11px] text-emerald-300 font-mono">{audit}</div>}
        <div className="text-[10px] text-stone-600">Rescan re-probes host tools, Docker, Podman, network facts, and model providers. It can take up to a minute.</div>
      </Section>
    </div>
  );
};
