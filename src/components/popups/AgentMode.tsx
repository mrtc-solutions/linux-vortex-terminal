import { useCallback, useEffect, useRef, useState } from 'react';
import { apiGet, apiPost, JsonRecord } from '../../services/vortexApi';
import { ErrorLine, GhostButton, PrimaryButton, Section, asRecord, inputCls } from './common';

// Bounded backend agent runs, separate from the advisory-only AI Ops inspector.
export function AgentMode() {
  const [goal, setGoal] = useState('');
  const [steps, setSteps] = useState(5);
  const [runs, setRuns] = useState<JsonRecord[]>([]);
  const [id, setId] = useState('');
  const [payload, setPayload] = useState<JsonRecord>({});
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [error, setError] = useState('');
  const generation = useRef(0);
  const refresh = useCallback(async () => {
    const ticket = ++generation.current;
    try {
      const list = await apiGet<JsonRecord>('/api/agent/runs');
      if (ticket !== generation.current) return;
      const items = Array.isArray(list.runs) ? list.runs.map(asRecord) : [];
      setRuns(items);
      if (id) {
        const detail = await apiGet<JsonRecord>(`/api/agent/runs/${encodeURIComponent(id)}`);
        if (ticket === generation.current) setPayload(detail);
      } else if (items[0]?.id) setId(String(items[0].id));
    } catch (err) { if (ticket === generation.current) setError(err instanceof Error ? err.message : String(err)); }
  }, [id]);
  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => { if (!lock.current) void refresh(); }, 2000);
    return () => { generation.current++; window.clearInterval(timer); };
  }, [refresh]);
  const run = asRecord(payload.run);
  const config = asRecord(run.config);
  const events = Array.isArray(payload.events) ? payload.events.map(asRecord) : [];
  const plan = [...events].reverse().find(event => event.kind === 'step_planned');
  const planned = asRecord(plan?.payload);
  const act = async (action: () => Promise<JsonRecord>) => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError('');
    try {
      const result = await action();
      if (asRecord(result.run).id) { setId(String(asRecord(result.run).id)); setPayload(result); }
      await refresh();
    } catch (err) { setError(err instanceof Error ? err.message : String(err)); }
    finally { lock.current = false; setBusy(false); }
  };
  const active = runs.some(item => item.status !== 'finished');
  return <div className="p-4 space-y-3 text-stone-300">
    <p>Bounded agent mode: the model proposes steps, Guardian authorizes, and the host produces evidence. Missing models are reported, never simulated.</p>
    <ErrorLine message={error} />
    <textarea aria-label="Agent goal" className={inputCls} value={goal} onChange={e => setGoal(e.target.value)} placeholder="Describe an authorized local goal" />
    <label>Maximum steps (1–10)<input aria-label="Agent maximum steps" type="number" min={1} max={10} className={inputCls} value={steps} onChange={e => setSteps(Math.max(1, Math.min(10, Number(e.target.value) || 1)))} /></label>
    <PrimaryButton disabled={busy || active || !goal.trim()} onClick={() => void act(() => apiPost<JsonRecord>('/api/agent/runs', { goal: goal.trim(), max_steps: steps }))}>Start bounded run</PrimaryButton>
    <GhostButton disabled={busy} onClick={() => { setError(''); void refresh(); }}>Refresh runs</GhostButton>
    <Section title="Recorded runs">
      {runs.map(item => <GhostButton key={String(item.id)} disabled={busy} onClick={() => { setPayload({}); setId(String(item.id)); }}>{String(item.goal)} · {String(item.status)}</GhostButton>)}
    </Section>
    {!!run.id && <Section title={`Run ${String(run.status)}`}>
      <p>{String(run.goal)} · step {String(config.step_index || 0)} / {String(config.max_steps || steps)}</p>
      {run.status === 'awaiting_approval' && <div className="space-y-2 border border-amber-700 p-2">
        <p>Review this exact step before continuing.</p>
        <pre className="whitespace-pre-wrap break-all">{JSON.stringify(planned, null, 2)}</pre>
        <PrimaryButton disabled={busy} onClick={() => void act(() => apiPost<JsonRecord>(`/api/agent/runs/${encodeURIComponent(id)}/approve`, { plan_id: config.pending_plan_id || planned.plan_id, confirm: true }))}>Approve exact agent step</PrimaryButton>
      </div>}
      {run.status !== 'finished' && <GhostButton disabled={busy} onClick={() => void act(() => apiPost<JsonRecord>(`/api/agent/runs/${encodeURIComponent(id)}/stop`))}>Stop agent run</GhostButton>}
      <p className="text-amber-300">Closing this window does not stop a run. Use Stop agent run to cancel it.</p>
      {events.map(event => <details key={String(event.seq)} open><summary>{String(event.kind)}</summary><pre className="whitespace-pre-wrap break-all select-text">{JSON.stringify(event.payload, null, 2)}</pre></details>)}
    </Section>}
  </div>;
}
