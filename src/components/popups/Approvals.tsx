/* Guardian plan-review popup — approve & execute, or reject. Real routes only.
   Also hosts the second confirmation step: when a mutation operation pauses in
   `awaiting_confirmation` (preflight), this popup offers CONFIRM MUTATION —
   there is no other surface that can complete that gate. */
import React, { useState } from 'react';
import { ShieldAlert, ShieldCheck, ShieldX, Play, Loader2 } from 'lucide-react';
import { JsonRecord, OperationDocument, PlanDocument, TurnResult, rejectPlan } from '../../services/vortexApi';
import { approveMutation, executePlan, watchOperation } from '../../services/turnRunner';
import { sound } from '../../services/soundEffects';

interface ApprovalsProps {
  onBusyChange?: (busy: boolean) => void;
  plan: PlanDocument;
  guardian: JsonRecord;
  onApproved: (operation: OperationDocument) => void;
  onRejected: () => void;
  onClose: () => void;
  mutation?: { operation: OperationDocument; approvalToken: string };
}

function riskColor(risk: string): string {
  if (risk === 'high') return 'text-rose-400 border-rose-800 bg-rose-950/40';
  if (risk === 'medium') return 'text-amber-400 border-amber-800 bg-amber-950/40';
  return 'text-emerald-400 border-emerald-800 bg-emerald-950/40';
}

export const Approvals: React.FC<ApprovalsProps> = ({ plan, guardian, onApproved, onRejected, onClose, mutation, onBusyChange }) => {
  const [busy, setBusyState] = useState(false);
  const setBusy = (value: boolean) => { setBusyState(value); onBusyChange?.(value); };
  const [liveStatus, setLiveStatus] = useState('');
  const [error, setError] = useState('');
  const [pendingMutation, setPendingMutation] = useState<OperationDocument | null>(() => {
    const op = mutation?.operation;
    return op && String(op.status) === 'awaiting_confirmation' ? op : null;
  });

  const commands = Array.isArray(plan.commands) ? plan.commands as JsonRecord[] : [];
  const notes = Array.isArray(plan.notes) ? (plan.notes as unknown[]).map(String) : [];
  const reasons = Array.isArray(guardian.reasons) ? (guardian.reasons as unknown[]).map(String) : [];
  const risk = String(guardian.risk || plan.risk || 'unknown');
  const decision = String(guardian.decision || 'review');
  const approvalToken = String(mutation?.approvalToken || plan.approval_token || '');

  const finishOrPreflight = async (operation: OperationDocument) => {
    if (String(operation.status) === 'awaiting_confirmation') {
      setPendingMutation(operation);
      setBusy(false);
      setLiveStatus('');
      sound.playAlert();
      return;
    }
    setBusy(false);
    sound.playSuccess();
    onApproved(operation);
    onClose();
  };

  const handleApprove = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    setLiveStatus('Starting approved execution…');
    sound.playExecute();
    try {
      const operation = await executePlan(String(plan.id), approvalToken);
      if (String(operation.status) === 'awaiting_confirmation') {
        await finishOrPreflight(operation);
        return;
      }
      setLiveStatus(`Running (${operation.status || 'started'})… streaming real output.`);
      const final = await watchOperation(String(operation.id), { plan } as unknown as TurnResult, {
        onLive: (live) => setLiveStatus(`Running (${String(live.status || 'running')})… streaming real output.`),
      });
      await finishOrPreflight(final);
    } catch (err) {
      sound.playAlert();
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
      setLiveStatus('');
    }
  };

  const handleConfirmMutation = async () => {
    if (busy || !pendingMutation) return;
    const digest = String((pendingMutation as JsonRecord).preflight_digest || '');
    if (!approvalToken || !digest) {
      setError('Cannot confirm: the approval token or preflight digest is missing. Re-run the request for a fresh plan.');
      return;
    }
    setBusy(true);
    setError('');
    setLiveStatus('Confirming mutation preflight…');
    sound.playExecute();
    try {
      const resumed = await approveMutation(String(pendingMutation.id), approvalToken, digest);
      setPendingMutation(null);
      setLiveStatus(`Running (${resumed.status || 'started'})… streaming real output.`);
      const final = await watchOperation(String(resumed.id), { plan } as unknown as TurnResult, {
        onLive: (live) => setLiveStatus(`Running (${String(live.status || 'running')})… streaming real output.`),
      });
      await finishOrPreflight(final);
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
      setBusy(false);
      onRejected();
      onClose();
    } catch (err) {
      sound.playAlert();
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  if (pendingMutation) {
    const op = pendingMutation as JsonRecord;
    const preflight = (op.preflight && typeof op.preflight === 'object' ? op.preflight : {}) as JsonRecord;
    const ran = Array.isArray(op.commands) ? (op.commands as unknown[]).length : 0;
    return (
      <div className="p-4 space-y-3 text-stone-300">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px] font-bold px-2 py-0.5 rounded border text-amber-400 border-amber-800 bg-amber-950/40">
            MUTATION PREFLIGHT
          </span>
          <span className="text-[11px] text-stone-500 font-mono">op {String(op.id || '').slice(0, 12)}…</span>
        </div>
        <div className="text-[11px] leading-relaxed p-2 rounded bg-black/50 border border-amber-900/40 flex gap-1.5">
          <ShieldAlert className="w-3.5 h-3.5 mt-0.5 shrink-0 text-amber-400" />
          <span>
            The operation paused before a mutating step and will not continue without this second,
            explicit confirmation. {ran} command{ran === 1 ? '' : 's'} already ran.
            {preflight.next_command ? (
              <> Next: <span className="font-mono text-stone-200">{String(preflight.next_command).slice(0, 120)}</span></>
            ) : null}
          </span>
        </div>
        <div className="text-[10px] text-stone-600 font-mono break-all">
          preflight {String(op.preflight_digest || 'unknown').slice(0, 32)}…
        </div>

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
            onClick={handleConfirmMutation}
            disabled={busy}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-[var(--theme-primary)] text-black font-bold text-xs hover:opacity-90 disabled:opacity-40 transition-opacity cursor-pointer"
          >
            {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
            <span>CONFIRM MUTATION</span>
          </button>
          <button
            onClick={onClose}
            disabled={busy}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-[var(--theme-border)] text-stone-300 font-bold text-xs hover:bg-black/60 disabled:opacity-40 transition-colors cursor-pointer"
          >
            <span>LEAVE PAUSED</span>
          </button>
        </div>
      </div>
    );
  }

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
