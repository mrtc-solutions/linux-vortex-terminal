/* AI Ops popup — the REAL advisory trace: last turn's provider outcome,
   council consultations, fallback reason, assist coverage, live ranking. */
import React, { useCallback, useEffect, useState } from 'react';
import { Bot, RefreshCw } from 'lucide-react';
import { JsonRecord, TurnResult, apiGet, getModels } from '../../services/vortexApi';
import { getLastTurn } from '../../services/lastTurnStore';
import { EmptyLine, ErrorLine, GhostButton, Section } from './common';

function asRecord(value: unknown): JsonRecord {
  return (value && typeof value === 'object' ? value : {}) as JsonRecord;
}

export const AiOps: React.FC = () => {
  const [snapshot, setSnapshot] = useState<{ turn: TurnResult | null; at: string }>({ turn: null, at: '' });
  const [coverage, setCoverage] = useState<JsonRecord | null>(null);
  const [ranking, setRanking] = useState<JsonRecord[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setError('');
    setSnapshot(getLastTurn());
    try {
      const [coveragePayload, modelsPayload] = await Promise.all([
        apiGet<JsonRecord>('/api/assist/coverage'),
        getModels(),
      ]);
      setCoverage(asRecord(coveragePayload.coverage));
      const fuzzy = asRecord(asRecord(modelsPayload.model).fuzzy);
      setRanking(Array.isArray(fuzzy.ranking) ? fuzzy.ranking as JsonRecord[] : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const turn = snapshot.turn;
  const localAi = asRecord(turn?.local_ai);
  const fuzzy = asRecord(localAi.fuzzy);
  const fallback = asRecord(localAi.fallback);
  const council = asRecord(turn?.council);
  const critic = asRecord(council.critic);
  const consultations = Array.isArray(council.consultations) ? council.consultations as JsonRecord[] : [];
  const coverageFns = Array.isArray(coverage?.assisted_functions) ? coverage.assisted_functions as unknown[] : [];

  return (
    <div className="p-4 space-y-4 text-stone-300">
      <div className="flex items-center gap-2">
        <Bot className="w-4 h-4 text-[var(--theme-primary)]" />
        <span className="text-[12px] font-bold text-stone-200">AI Operations</span>
        <span className="flex-1" />
        <GhostButton onClick={() => { setLoading(true); void refresh(); }} disabled={loading}>
          <span className="flex items-center gap-1"><RefreshCw className="w-3 h-3" />Refresh</span>
        </GhostButton>
      </div>

      <ErrorLine message={error} />

      <Section title={turn ? `Last turn advisory · ${snapshot.at}` : 'Last turn advisory'}>
        {!turn && <EmptyLine message="No turn has run yet in this session. Run something in the terminal, then reopen AI Ops." />}
        {turn && (
          <div className="p-2 rounded bg-black/50 border border-[var(--theme-border)] space-y-1.5 text-[11px]">
            <div className="text-stone-200 leading-relaxed">{String(localAi.message || 'No advisory message was recorded.').slice(0, 400)}</div>
            <div className="flex items-center gap-2 flex-wrap font-mono text-[10px] text-stone-500">
              <span>models responded: {String(fuzzy.models_responded ?? 0)}</span>
              <span>agreement: {String(fuzzy.agreement || 'none')}</span>
              <span>evidence: {String(fuzzy.evidence_basis || 'n/a')}</span>
            </div>
            {fallback.used === true && (
              <div className="text-amber-300/90 leading-relaxed">
                fallback: {String(fallback.reason || fallback.summary || 'deterministic core took over.').slice(0, 300)}
              </div>
            )}
            {String(critic.summary || '') && (
              <div className="text-stone-400 leading-relaxed">
                critic ({String(critic.agents_useful ?? 0)}/{String(critic.agents_consulted ?? 0)} useful):
                {' '}{String(critic.summary).slice(0, 300)}
              </div>
            )}
            {consultations.length > 0 && (
              <div className="space-y-1 pt-1 border-t border-[var(--theme-border)]/50">
                {consultations.slice(0, 4).map((item, index) => (
                  <div key={index} className="text-stone-400">
                    <span className="text-[var(--theme-primary)] font-bold">{String(item.agent || 'agent')}</span>
                    <span className="text-stone-600"> [{String(item.state || '?')}]</span>
                    {' '}{String(item.message || item.result || '').slice(0, 220)}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </Section>

      <Section title={`Assist coverage (${String(coverage?.count ?? coverageFns.length ?? '?')} functions)`}>
        {loading && !coverage && <EmptyLine message="Reading assist coverage…" />}
        {coverage?.contract ? <div className="text-[10px] text-stone-600 leading-relaxed">{String(coverage.contract)}</div> : null}
        {coverageFns.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {coverageFns.map((fn, index) => (
              <span key={index} className="text-[10px] px-1.5 py-0.5 rounded bg-black/60 border border-[var(--theme-border)] text-stone-300 font-mono">
                {String(fn)}
              </span>
            ))}
          </div>
        )}
      </Section>

      <Section title={`Live router ranking (${ranking.length})`}>
        {ranking.length === 0 && !loading && <EmptyLine message="No routing candidates were scored." />}
        {ranking.map((entry, index) => (
          <div key={index} className="flex items-center gap-2 p-1.5 rounded bg-black/50 border border-[var(--theme-border)] font-mono text-[11px]">
            <span className="text-stone-500 w-4">{index + 1}.</span>
            <span className="text-stone-200 font-bold">{String(entry.provider || '?')}</span>
            <span className="text-stone-500">score {Number(entry.score ?? 0).toFixed(2)}</span>
          </div>
        ))}
      </Section>

      <div className="text-[10px] text-stone-600 leading-relaxed">
        Advisory only: models and agents recommend, the Guardian authorizes. Nothing on this screen can execute anything.
      </div>
    </div>
  );
};
