/* Tools popup — real installed-tool inventory + host discovery + rescan. */
import React, { useCallback, useEffect, useState } from 'react';
import { Loader2, RefreshCw, Wrench } from 'lucide-react';
import { JsonRecord, listHostTools, listTools, rescanHostTools } from '../../services/vortexApi';
import { EmptyLine, ErrorLine, GhostButton, Section, StateBadge, asRecord, inputCls } from './common';

export const Tools: React.FC<{ onDependencies: () => void }> = ({ onDependencies }) => {
  const [tools, setTools] = useState<JsonRecord[]>([]);
  const [host, setHost] = useState<JsonRecord | null>(null);
  const [filter, setFilter] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setError('');
    try {
      const [inventory, hostTools] = await Promise.all([listTools(), listHostTools()]);
      setTools(Array.isArray(inventory.tools) ? inventory.tools as JsonRecord[] : []);
      setHost(hostTools);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const rescan = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await rescanHostTools();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const counts = asRecord(asRecord(host?.host_tools).counts);
  const needle = filter.trim().toLowerCase();
  const visible = needle
    ? tools.filter((tool) => `${String(tool.name || '')} ${String(tool.path || '')} ${String(tool.role || '')} ${String(tool.family || '')}`.toLowerCase().includes(needle))
    : tools;

  return (
    <div className="p-4 space-y-4 text-stone-300">
      <div className="flex items-center gap-2">
        <Wrench className="w-4 h-4 text-[var(--theme-primary)]" />
        <span className="text-[12px] font-bold text-stone-200">Tools</span>
        <span className="flex-1" />
        <GhostButton onClick={() => void rescan()} disabled={busy || loading}>
          <span className="flex items-center gap-1">
            {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
            {busy ? 'Scanning…' : 'Rescan host'}
          </span>
        </GhostButton>
      </div>

      <GhostButton onClick={onDependencies}>Missing dependencies</GhostButton>
      <ErrorLine message={error} />

      {host && (
        <Section title="Host discovery">
          <div className="flex items-center gap-2 flex-wrap text-[11px]">
            <StateBadge state={host.host_tool_access === true ? 'active' : 'disabled'} />
            <span className="text-stone-500">
              discovered {String(counts.discovered ?? '?')} · PATH {String(counts.path_executables ?? '?')} ·
              kali installed {String(counts.kali_known_installed ?? '?')} / absent {String(counts.kali_known_absent ?? '?')}
            </span>
          </div>
          <div className="text-[10px] text-stone-600">
            Host-tool planning is {host.host_tool_access === true ? 'ON — the planner may propose typed argv for discovered tools (Guardian still reviews).' : 'OFF — enable host_tool_access in Settings to let the planner use discovered tools.'}
          </div>
        </Section>
      )}

      <Section title={`Installed inventory (${visible.length}${needle ? ` of ${tools.length}` : ''})`}>
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="Filter by name, path, role…"
          spellCheck={false}
          className={inputCls}
        />
        {loading && <EmptyLine message="Reading the tool inventory…" />}
        {!loading && visible.length === 0 && <EmptyLine message={needle ? 'No tools match that filter.' : 'No tools inventoried yet — try Rescan host.'} />}
        <div className="space-y-1.5 max-h-96 overflow-y-auto pr-1">
          {visible.slice(0, 300).map((tool, index) => (
            <div key={`${String(tool.path || tool.name || index)}-${index}`} className="p-1.5 rounded bg-black/50 border border-[var(--theme-border)]">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="font-bold text-[12px] text-stone-200 font-mono">{String(tool.name || '?')}</span>
                <StateBadge state={String(tool.state || 'unknown')} />
                {tool.version ? <span className="text-[10px] text-stone-500 font-mono">{String(tool.version)}</span> : null}
              </div>
              <div className="text-[10px] text-stone-500 font-mono break-all">{String(tool.path || '')}</div>
              {Boolean(tool.role || tool.family) && (
                <div className="text-[10px] text-stone-600">{[tool.family, tool.role].filter(Boolean).map(String).join(' · ')}</div>
              )}
            </div>
          ))}
        </div>
      </Section>
    </div>
  );
};
