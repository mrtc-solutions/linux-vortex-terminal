/* Guardian plan-review popup — approve & execute, or reject. Real routes only. */
import React, { useState } from 'react';
import { ShieldCheck, ShieldX, Play, Loader2 } from 'lucide-react';
import { JsonRecord, OperationDocument, PlanDocument, TurnResult, rejectPlan } from '../../services/vortexApi';
import { executePlan, watchOperation } from '../../services/turnRunner';
import { sound } from '../../services/soundEffects';

interface ApprovalsProps {
  plan: PlanDocument;
  guardian: JsonRecord;
  onApproved: (operation: OperationDocument) => void;
  onRejected: () => void;
  onClose: () => void;
}

function riskColor(risk: string): string {
  if (risk === 'high') return 'text-rose-400 border-rose-800 bg-rose-950/40';
  if (risk === 'medium') return 'text-amber-400 border-amber-800 bg-amber-950/40';
  return 'text-emerald-400 border-emerald-800 bg-emerald-950/40';
}

export const Approvals: React.FC<ApprovalsProps> = ({ plan, guardian, onApproved, onRejected, onClose }) => {
  const [busy, setBusy] = useState(false);
  const [liveStatus, setLiveStatus] = useState('');
  const [error, setError] = useState('');

  const commands = Array.isArray(plan.commands) ? plan.commands as JsonRecord[] : [];
  const notes = Array.isArray(plan.notes) ? (plan.notes as unknown[]).map(String) : [];
  const reasons = Array.isArray(guardian.reasons) ? (guardian.reasons as unknown[]).map(String) : [];
  const risk = String(guardian.risk || plan.risk || 'unknown');
  const decision = String(guardian.decision || 'review');

  const handleApprove = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    setLiveStatus('Starting approved execution…');
    sound.playExecute();
    try {
      const operation = await executePlan(String(plan.id), String(plan.approval_token || ''));
      setLiveStatus(`Running (${operation.status || 'started'})… streaming real output.`);
      const final = await watchOperation(String(operation.id), { plan } as unknown as TurnResult, {
        onLive: (live) => setLiveStatus(`Running (${String(live.status || 'running')})… streaming real output.`),
      });
      sound.playSuccess();
      onApproved(final);
      onClose();
    } catch (err) {
      sound.playAlert();
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
      setLiveStatus('');
    }
  };

  const handleReject = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await rejectPlan(String(plan.id));
      sound.playKeypress();
      onRejected();
      onClose();
    } catch (err) {
      sound.playAlert();
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  return (
    <div className="p-4 space-y-3 text-stone-300">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`text-[11px] font-bold px-2 py-0.5 rounded border ${riskColor(risk)}`}>
          RISK: {risk.toUpperCase()}
        </span>
        <span className="text-[11px] px-2 py-0.5 rounded border border-[var(--theme-border)] text-[var(--theme-primary)]">
          GUARDIAN: {decision.toUpperCase()}
        </span>
        <span className="text-[11px] text-stone-500 font-mono">kind: {String(plan.kind || 'unknown')}</span>
      </div>

      {reasons.length > 0 && (
        <div className="text-[11px] leading-relaxed p-2 rounded bg-black/50 border border-[var(--theme-border)]">
          {reasons.map((reason, index) => (
            <div key={index} className="flex gap-1.5">
              <ShieldCheck className="w-3 h-3 mt-0.5 shrink-0 text-[var(--theme-primary)]" />
              <span>{reason}</span>
            </div>
          ))}
        </div>
      )}

      <div className="space-y-1.5">
        <div className="text-[10px] uppercase tracking-wider text-stone-500 font-semibold">
          Typed commands to execute ({commands.length})
        </div>
        {commands.length === 0 && (
          <div className="text-[11px] text-stone-500">No commands were planned. There is nothing to approve.</div>
        )}
        {commands.map((command, index) => (
          <div key={index} className="p-2 rounded bg-black/70 border border-[var(--theme-border)] font-mono">
            <div className="text-emerald-300 text-xs font-semibold break-all">
              $ {String(command.display || (Array.isArray(command.argv) ? command.argv.join(' ') : ''))}
            </div>
            {command.explanation ? (
              <div className="text-[11px] text-stone-400 mt-0.5">{String(command.explanation)}</div>
            ) : null}
            <div className="text-[10px] text-stone-600 mt-0.5">
              adapter: {String(command.adapter_id || 'unknown')}
              {command.executable_identity && typeof command.executable_identity === 'object'
                ? ` · ${(command.executable_identity as JsonRecord).path || ''} ${(command.executable_identity as JsonRecord).version || ''}`.trimEnd()
                : ''}
            </div>
          </div>
        ))}
      </div>

      {notes.length > 0 && (
        <div className="text-[11px] text-stone-500 leading-relaxed">
          {notes.slice(0, 4).map((note, index) => (
            <div key={index}>• {note}</div>
          ))}
        </div>
      )}

      {liveStatus && (
        <div className="flex items-center gap-2 text-[11px] text-[var(--theme-primary)]">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          <span>{liveStatus}</span>
        </div>
      )}

      {error && (
        <div className="text-[11px] text-rose-400 p-2 rounded bg-rose-950/20 border border-rose-900/40 whitespace-pre-wrap">
          {error}
        </div>
      )}

      <div className="flex items-center gap-2 pt-1">
        <button
          onClick={handleApprove}
          disabled={busy || commands.length === 0}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-[var(--theme-primary)] text-black font-bold text-xs hover:opacity-90 disabled:opacity-40 transition-opacity cursor-pointer"
        >
          {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
          <span>APPROVE &amp; EXECUTE</span>
        </button>
        <button
          onClick={handleReject}
          disabled={busy}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-rose-900/60 text-rose-300 font-bold text-xs hover:bg-rose-950/40 disabled:opacity-40 transition-colors cursor-pointer"
        >
          <ShieldX className="w-3.5 h-3.5" />
          <span>REJECT PLAN</span>
        </button>
        <span className="text-[10px] text-stone-600 ml-auto font-mono">
          {String(plan.approval_phrase || '')}
        </span>
      </div>
    </div>
  );
};
