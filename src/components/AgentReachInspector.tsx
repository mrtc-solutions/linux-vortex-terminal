/* Agent Reach — the REAL secondary-agent roster plus the real capability
   surface: implemented features and host probes. No staged agents. */
import React, { useCallback, useEffect, useState } from 'react';
import { Activity, Bot, RefreshCw } from 'lucide-react';
import { JsonRecord, apiGet, getCapabilities, listTools } from '../services/vortexApi';
import { sound } from '../services/soundEffects';

interface AgentReachInspectorProps {
  onExecuteCommand: (cmd: string) => void;
  onOpenPopup?: (kind: string) => void;
}

export const AgentReachInspector: React.FC<AgentReachInspectorProps> = ({ onExecuteCommand, onOpenPopup }) => {
  const [upstream, setUpstream] = useState<JsonRecord>({});
  const [implemented, setImplemented] = useState<string[]>([]);
  const [probes, setProbes] = useState<JsonRecord>({});
  const [tools, setTools] = useState<JsonRecord[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setError('');
    try {
      const [upstreamPayload, capsPayload, toolsPayload] = await Promise.all([
        apiGet<JsonRecord>('/api/agents/upstream'),
        getCapabilities(),
        listTools(),
      ]);
      setUpstream((upstreamPayload.upstream || {}) as JsonRecord);
      setImplemented(Array.isArray(capsPayload.implemented) ? capsPayload.implemented.map(String) : []);
      setProbes(((capsPayload.host_probes || {}) as JsonRecord));
      setTools(Array.isArray(toolsPayload.tools) ? toolsPayload.tools as JsonRecord[] : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const agents = Object.entries(upstream);
  const installed = Array.isArray(probes.agents_installed) ? probes.agents_installed.map(String) : [];

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-[var(--theme-bg)] font-mono text-xs">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-[var(--theme-border)] bg-[var(--theme-surface)]/70">
        <Activity className="w-4 h-4 text-[var(--theme-primary)]" />
        <span className="font-bold text-stone-200">AGENT REACH</span>
        <span className="text-stone-500">{agents.length} upstream · {installed.length} installed</span>
        <span className="flex-1" />
        <button
          onClick={() => { setLoading(true); void refresh(); sound.playKeypress(); }}
          className="flex items-center gap-1 px-2 py-0.5 rounded border border-[var(--theme-border)] text-stone-300 hover:text-[var(--theme-primary)] cursor-pointer"
        >
          <RefreshCw className="w-3 h-3" />
          <span>Refresh</span>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {error && (
          <div className="p-2.5 rounded bg-rose-950/20 border border-rose-900/40 text-rose-400 whitespace-pre-wrap">{error}</div>
        )}
        {loading && agents.length === 0 && <div className="text-stone-500">Reading the agent roster…</div>}

        <div className="space-y-1.5">
          <div className="text-[10px] uppercase tracking-wider text-stone-500 font-semibold">Secondary agents (advisory-only)</div>
          {!loading && agents.length === 0 && !error && <div className="text-stone-500">No agents registered upstream.</div>}
          {agents.map(([id, detail]) => {
            const info = (detail || {}) as JsonRecord;
            return (
              <div key={id} className="rounded bg-black/60 border border-[var(--theme-border)] p-3 space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <Bot className="w-4 h-4 text-[var(--theme-primary)]" />
                  <span className="font-bold text-stone-100">{id}</span>
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${
                    installed.includes(id)
                      ? 'text-emerald-400 border-emerald-800 bg-emerald-950/40'
                      : 'text-stone-400 border-stone-700 bg-stone-900/40'
                  }`}>
                    {installed.includes(id) ? 'INSTALLED' : 'NOT INSTALLED'}
                  </span>
                  {info.consult ? (
                    <span className="text-[10px] text-stone-500">consult: {String(info.consult)}</span>
                  ) : null}
                </div>
                {info.notes ? <div className="text-[11px] text-stone-400">{String(info.notes)}</div> : null}
                <div className="text-[10px] text-stone-600">
                  {[
                    info.branch ? `branch: ${info.branch}` : '',
                    info.license ? `license: ${info.license}` : '',
                    info.sync_state ? `sync: ${info.sync_state}` : '',
                  ].filter(Boolean).join(' · ')}
                </div>
              </div>
            );
          })}
          <div className="text-[10px] text-stone-600 leading-relaxed">
            Advisors recommend; they never authorize. Every consultation is recorded on the turn, and agent output
            is treated as untrusted data by the Guardian.
          </div>
        </div>

        <div className="space-y-1.5">
          <div className="text-[10px] uppercase tracking-wider text-stone-500 font-semibold">
            Implemented capabilities ({implemented.length})
          </div>
          <div className="flex flex-wrap gap-1.5">
            {implemented.map((capability) => (
              <span key={capability} className="text-[10px] px-1.5 py-0.5 rounded bg-black/60 border border-[var(--theme-border)] text-stone-300 font-mono">
                {capability}
              </span>
            ))}
          </div>
        </div>

        <div className="space-y-1.5">
          <div className="text-[10px] uppercase tracking-wider text-stone-500 font-semibold">Host probes</div>
          <div className="rounded bg-black/60 border border-[var(--theme-border)] p-2.5 space-y-1">
            {Object.entries(probes).filter(([key]) => key !== 'agents_installed' && key !== 'agents_catalog').map(([key, value]) => (
              <div key={key} className="flex items-start gap-2 text-[11px]">
                <span className="text-stone-500 w-28 shrink-0">{key}</span>
                <span className={String(value) === 'absent' ? 'text-stone-600' : 'text-stone-200'}>
                  {typeof value === 'object' ? JSON.stringify(value).slice(0, 200) : String(value)}
                </span>
              </div>
            ))}
          </div>
        </div>

        <div className="space-y-1.5">
          <div className="text-[10px] uppercase tracking-wider text-stone-500 font-semibold">
            Host FOSS tools ({tools.length})
          </div>
          <div className="text-[10px] text-stone-600 leading-relaxed">
            Installed tools are observed on this host. Missing catalog items open a Guardian-reviewed
            <span className="font-mono"> install package </span> plan — they are never downloaded silently.
          </div>
          <div className="flex flex-wrap gap-1.5">
            {tools.slice(0, 48).map((tool) => {
              const name = String(tool.name || '');
              const state = String(tool.state || 'unknown');
              const installed = state === 'installed';
              return (
                <button
                  key={name}
                  type="button"
                  title={installed ? `${name} is installed` : `Plan install of ${name}`}
                  onClick={() => onExecuteCommand(installed ? `which ${name}` : `install package ${name}`)}
                  className={`text-[10px] px-1.5 py-0.5 rounded border cursor-pointer font-mono ${
                    installed
                      ? 'text-emerald-300 border-emerald-800 bg-emerald-950/30'
                      : 'text-stone-400 border-stone-700 bg-black/60 hover:text-[var(--theme-primary)]'
                  }`}
                >
                  {name} · {installed ? 'ready' : 'missing'}
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => onOpenPopup?.('agent')}
            className="px-2 py-1 rounded border border-[var(--theme-border)] text-stone-200 hover:text-[var(--theme-primary)] cursor-pointer"
          >
            Open Agent Mode (think → plan → Guardian → execute)
          </button>
          <button
            onClick={() => onExecuteCommand('What security tools are installed on this machine?')}
            className="text-[var(--theme-primary)] hover:underline cursor-pointer text-left"
          >
            Ask the terminal about this machine's tooling →
          </button>
        </div>
      </div>
    </div>
  );
};
