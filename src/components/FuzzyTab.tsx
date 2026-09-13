/* Fuzzy Consensus — the LIVE model router: real candidate ranking with
   membership traces, refreshed from the sidecar. No toy simulation. */
import React, { useCallback, useEffect, useState } from 'react';
import { RefreshCw, Scale } from 'lucide-react';
import { JsonRecord, getModels } from '../services/vortexApi';
import { sound } from '../services/soundEffects';

interface FuzzyTabProps {
  onExecuteCommand: (cmd: string) => void;
}

function MembershipBar({ label, value }: { label: string; value: number }) {
  const pct = Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="flex items-center gap-2 text-[10px]">
      <span className="text-stone-500 w-14 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 rounded bg-stone-800 overflow-hidden">
        <div className="h-full rounded" style={{ width: `${pct}%`, backgroundColor: 'var(--theme-primary)' }} />
      </div>
      <span className="text-stone-400 font-mono w-10 text-right">{pct.toFixed(0)}%</span>
    </div>
  );
}

export const FuzzyTab: React.FC<FuzzyTabProps> = ({ onExecuteCommand }) => {
  const [model, setModel] = useState<JsonRecord | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setError('');
    try {
      const payload = await getModels();
      setModel((payload.model || {}) as JsonRecord);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const fuzzy = ((model || {}).fuzzy || {}) as JsonRecord;
  const ranking = Array.isArray(fuzzy.ranking) ? fuzzy.ranking as JsonRecord[] : [];

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-[var(--theme-bg)] font-mono text-xs">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-[var(--theme-border)] bg-[var(--theme-surface)]/70">
        <Scale className="w-4 h-4 text-[var(--theme-primary)]" />
        <span className="font-bold text-stone-200">FUZZY ROUTER</span>
        {model && (
          <span className="text-stone-500">
            selected: <span className="text-[var(--theme-primary)] font-bold">{String(model.selected || 'none')}</span>
            {' '}· confidence: {String(fuzzy.confidence || 'n/a')} · phase: {String(fuzzy.phase || 'n/a')}
          </span>
        )}
        <span className="flex-1" />
        <button
          onClick={() => { setLoading(true); void refresh(); sound.playFuzzyArbiter(); }}
          className="flex items-center gap-1 px-2 py-0.5 rounded border border-[var(--theme-border)] text-stone-300 hover:text-[var(--theme-primary)] cursor-pointer"
        >
          <RefreshCw className="w-3 h-3" />
          <span>Re-score</span>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {error && (
          <div className="p-2.5 rounded bg-rose-950/20 border border-rose-900/40 text-rose-400 whitespace-pre-wrap">{error}</div>
        )}
        {loading && ranking.length === 0 && <div className="text-stone-500">Scoring routing candidates…</div>}

        {model && model.message ? (
          <div className="text-[11px] text-stone-400 p-2.5 rounded bg-black/50 border border-[var(--theme-border)] leading-relaxed">
            {String(model.message).slice(0, 500)}
          </div>
        ) : null}

        {ranking.map((entry, index) => {
          const trace = (entry.trace || {}) as JsonRecord;
          const latency = (trace.latency || {}) as JsonRecord;
          const ram = (trace.ram || {}) as JsonRecord;
          const winner = index === 0;
          return (
            <div key={index} className={`rounded border p-3 space-y-2 ${winner ? 'bg-black/70 border-[var(--theme-primary)]' : 'bg-black/50 border-[var(--theme-border)]'}`}>
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-stone-600 font-bold">#{index + 1}</span>
                <span className={`font-bold text-sm ${winner ? 'text-[var(--theme-primary)]' : 'text-stone-200'}`}>
                  {String(entry.provider || '?')}
                </span>
                {winner && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--theme-primary)] text-black font-bold">ROUTED HERE</span>
                )}
                <span className="flex-1" />
                <span className="text-stone-400">score <span className="font-black text-stone-100">{Number(entry.score ?? 0).toFixed(3)}</span></span>
                {entry.latency_ms != null && <span className="text-stone-500">{String(entry.latency_ms)} ms</span>}
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-x-4 gap-y-1 pl-6">
                <div className="space-y-1">
                  <div className="text-[10px] text-stone-600 uppercase">availability</div>
                  <MembershipBar label="ready" value={Number(trace.availability ?? 0)} />
                </div>
                <div className="space-y-1">
                  <div className="text-[10px] text-stone-600 uppercase">latency</div>
                  <MembershipBar label="fast" value={Number(latency.fast ?? 0)} />
                  <MembershipBar label="ok" value={Number(latency.ok ?? 0)} />
                  <MembershipBar label="slow" value={Number(latency.slow ?? 0)} />
                </div>
                <div className="space-y-1">
                  <div className="text-[10px] text-stone-600 uppercase">memory fit</div>
                  <MembershipBar label="free" value={Number(ram.free ?? 0)} />
                  <MembershipBar label="tight" value={Number(ram.tight ?? 0)} />
                  <MembershipBar label="critical" value={Number(ram.critical ?? 0)} />
                </div>
              </div>
              {trace.phase_fit != null && (
                <div className="text-[10px] text-stone-600 pl-6">phase fit: {Number(trace.phase_fit).toFixed(2)}</div>
              )}
            </div>
          );
        })}

        {!loading && ranking.length === 0 && !error && (
          <div className="text-stone-500">No routing candidates were scored.</div>
        )}

        <button
          onClick={() => onExecuteCommand('Check disk usage on all mounted filesystems')}
          className="text-[var(--theme-primary)] hover:underline cursor-pointer text-left"
        >
          Run a terminal turn to see per-turn advisory detail →
        </button>
      </div>
    </div>
  );
};
