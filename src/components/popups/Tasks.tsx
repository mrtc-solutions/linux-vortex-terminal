/* Tasks popup — real task ledger with pause/resume/restart/delete + events. */
import React, { useCallback, useEffect, useState } from 'react';
import { ListChecks, Loader2, RefreshCw } from 'lucide-react';
import {
  JsonRecord, TaskDocument, cancelOperation, deleteTask, getTaskEvents, listTasks,
  pauseTask, restartTask, resumeTask,
} from '../../services/vortexApi';
import { DangerButton, EmptyLine, ErrorLine, GhostButton, Section, StateBadge } from './common';

export const Tasks: React.FC = () => {
  const [tasks, setTasks] = useState<TaskDocument[]>([]);
  const [interrupted, setInterrupted] = useState<TaskDocument[]>([]);
  const [selected, setSelected] = useState<TaskDocument | null>(null);
  const [events, setEvents] = useState<string>('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setError('');
    try {
      const payload = await listTasks();
      setTasks(Array.isArray(payload.tasks) ? payload.tasks : []);
      setInterrupted(Array.isArray((payload as JsonRecord).interrupted)
        ? (payload as JsonRecord).interrupted as TaskDocument[] : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const run = async (label: string, action: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(label);
    setError('');
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('');
    }
  };

  const inspect = async (task: TaskDocument) => {
    setSelected(task);
    setEvents('Loading events…');
    setError('');
    try {
      const payload = await getTaskEvents(String(task.id));
      const list = Array.isArray(payload.events) ? payload.events : [];
      setEvents(list.length === 0
        ? 'No task events were recorded.'
        : list.map((event) => {
          const item = (event && typeof event === 'object' ? event : {}) as JsonRecord;
          return `[${String(item.at || item.created_at || '?')}] ${String(item.kind || item.type || 'event')}: ${String(item.message || item.detail || JSON.stringify(item)).slice(0, 300)}`;
        }).join('\n'));
    } catch (err) {
      setEvents('');
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const row = (task: TaskDocument) => (
    <div key={String(task.id)} className="p-2 rounded bg-black/50 border border-[var(--theme-border)] space-y-1">
      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-mono text-[10px] text-stone-500">{String(task.id)}</span>
        <StateBadge state={String(task.state || 'unknown')} />
        {task.risk ? <span className="text-[10px] text-stone-500">risk {String(task.risk)}</span> : null}
      </div>
      <div className="text-[12px] text-stone-200 break-words">{String(task.request || '(no request text)')}</div>
      <div className="flex items-center gap-1.5 flex-wrap pt-0.5">
        <GhostButton onClick={() => void inspect(task)}>Events</GhostButton>
        <GhostButton onClick={() => void run(`pause-${task.id}`, () => pauseTask(String(task.id)))} disabled={!!busy}>
          {busy === `pause-${task.id}` ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Pause'}
        </GhostButton>
        <GhostButton onClick={() => void run(`resume-${task.id}`, () => resumeTask(String(task.id)))} disabled={!!busy}>
          {busy === `resume-${task.id}` ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Resume'}
        </GhostButton>
        <GhostButton onClick={() => void run(`restart-${task.id}`, () => restartTask(String(task.id)))} disabled={!!busy}>
          {busy === `restart-${task.id}` ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Restart'}
        </GhostButton>
        {task.operation_id ? (
          <GhostButton onClick={() => void run(`cancel-${task.id}`, () => cancelOperation(String(task.operation_id)))} disabled={!!busy}>
            {busy === `cancel-${task.id}` ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Cancel op'}
          </GhostButton>
        ) : null}
        <DangerButton onClick={() => void run(`delete-${task.id}`, () => deleteTask(String(task.id)))} disabled={!!busy}>
          {busy === `delete-${task.id}` ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Delete'}
        </DangerButton>
      </div>
    </div>
  );

  return (
    <div className="p-4 space-y-4 text-stone-300">
      <div className="flex items-center gap-2">
        <ListChecks className="w-4 h-4 text-[var(--theme-primary)]" />
        <span className="text-[12px] font-bold text-stone-200">Task ledger</span>
        <span className="flex-1" />
        <GhostButton onClick={() => { setLoading(true); void refresh(); }} disabled={loading}>
          <span className="flex items-center gap-1"><RefreshCw className="w-3 h-3" />Refresh</span>
        </GhostButton>
      </div>

      <ErrorLine message={error} />
      {loading && tasks.length === 0 && <EmptyLine message="Reading the task ledger…" />}

      {interrupted.length > 0 && (
        <Section title={`Interrupted — resume to continue (${interrupted.length})`}>
          <div className="space-y-1.5">{interrupted.map(row)}</div>
        </Section>
      )}

      <Section title={`All tasks (${tasks.length})`}>
        {tasks.length === 0 && !loading && <EmptyLine message="No tasks yet. Run something in the terminal." />}
        <div className="space-y-1.5">{tasks.map(row)}</div>
      </Section>

      {selected && (
        <Section title={`Events · ${String(selected.id)}`}>
          <pre className="text-[10px] leading-relaxed p-2 rounded bg-black/70 border border-[var(--theme-border)] text-stone-300 whitespace-pre-wrap max-h-48 overflow-y-auto">
            {events}
          </pre>
        </Section>
      )}
    </div>
  );
};
