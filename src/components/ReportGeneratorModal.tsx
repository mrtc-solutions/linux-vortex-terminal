/* Reports — REAL operation reports, system report, and per-engagement
   assessments, all rendered from sidecar output. Nothing is authored here. */
import React, { useCallback, useEffect, useState } from 'react';
import { Download, FileText, Loader2, RefreshCw, Trash2 } from 'lucide-react';
import {
  JsonRecord, apiDownload, apiGet, deleteReport, downloadReport,
  listEngagements, listReports,
} from '../services/vortexApi';
import { sound } from '../services/soundEffects';

interface ReportGeneratorModalProps {
  onReportSaved: () => void;
  onNavigateToOut: () => void;
}

const FORMATS = ['md', 'html', 'json', 'pdf'];

export const ReportGeneratorModal: React.FC<ReportGeneratorModalProps> = ({ onReportSaved, onNavigateToOut }) => {
  const [reports, setReports] = useState<JsonRecord[]>([]);
  const [engagements, setEngagements] = useState<JsonRecord[]>([]);
  const [selected, setSelected] = useState<JsonRecord | null>(null);
  const [systemReport, setSystemReport] = useState('');
  const [assessment, setAssessment] = useState('');
  const [assessmentId, setAssessmentId] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setError('');
    try {
      const [reportsPayload, engagementsPayload] = await Promise.all([listReports(), listEngagements()]);
      setReports(Array.isArray(reportsPayload.reports) ? reportsPayload.reports as JsonRecord[] : []);
      const engs = Array.isArray(engagementsPayload.engagements) ? engagementsPayload.engagements as JsonRecord[] : [];
      setEngagements(engs);
      if (!assessmentId && engs.length > 0) setAssessmentId(String(engs[0].id));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [assessmentId]);

  useEffect(() => { void refresh(); }, [refresh]);

  const viewSystem = async () => {
    if (busy) return;
    setBusy('system');
    setError('');
    setSystemReport('');
    try {
      const payload = await apiGet<JsonRecord>('/api/reports/system');
      setSystemReport(JSON.stringify(payload, null, 2).slice(0, 6000));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('');
    }
  };

  const viewAssessment = async () => {
    if (busy || !assessmentId) return;
    setBusy('assessment');
    setError('');
    setAssessment('');
    try {
      const payload = await apiGet<JsonRecord>(`/api/reports/assessment/${encodeURIComponent(assessmentId)}?format=json`);
      setAssessment(JSON.stringify(payload.report || payload, null, 2).slice(0, 6000));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('');
    }
  };

  const download = (id: string, format: string) => {
    setError('');
    try {
      void downloadReport(id, format).catch((err: unknown) => {
        setError(err instanceof Error ? err.message : String(err));
      });
      sound.playKeypress();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const remove = async (id: string) => {
    if (busy) return;
    setBusy(`delete-${id}`);
    setError('');
    try {
      await deleteReport(id);
      if (selected && String(selected.id) === id) setSelected(null);
      await refresh();
      onReportSaved();
      sound.playKeypress();
    } catch (err) {
      sound.playAlert();
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('');
    }
  };

  const selectedBody = selected ? ((selected.body || {}) as JsonRecord) : null;

  return (
    <div className="flex-1 flex flex-col lg:flex-row overflow-hidden bg-[var(--theme-bg)] font-mono text-xs">
      {/* Report list */}
      <div className="w-full lg:w-80 shrink-0 border-b lg:border-b-0 lg:border-r border-[var(--theme-border)] bg-[var(--theme-surface)]/60 flex flex-col overflow-hidden max-h-64 lg:max-h-none">
        <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--theme-border)]">
          <FileText className="w-4 h-4 text-[var(--theme-primary)]" />
          <span className="font-bold text-stone-200">REPORTS ({reports.length})</span>
          <span className="flex-1" />
          <button
            onClick={() => { setLoading(true); void refresh(); }}
            className="flex items-center gap-1 px-2 py-0.5 rounded border border-[var(--theme-border)] text-stone-300 hover:text-[var(--theme-primary)] cursor-pointer"
          >
            <RefreshCw className="w-3 h-3" />
            <span>Refresh</span>
          </button>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1.5">
          {loading && reports.length === 0 && <div className="text-stone-500 p-2">Reading reports…</div>}
          {!loading && reports.length === 0 && <div className="text-stone-500 p-2">No reports yet — completed tasks file them here automatically.</div>}
          {reports.map((report) => (
            <button
              key={String(report.id)}
              onClick={() => { setSelected(report); sound.playKeypress(); }}
              className={`w-full text-left p-2 rounded border cursor-pointer transition-colors ${
                selected && String(selected.id) === String(report.id)
                  ? 'bg-black/70 border-[var(--theme-primary)]'
                  : 'bg-black/50 border-[var(--theme-border)] hover:border-[var(--theme-primary)]'
              }`}
            >
              <div className="font-bold text-stone-100 break-words">{String(report.title || 'Untitled')}</div>
              <div className="text-[10px] text-stone-500">
                {String(report.kind || '')} · {String(report.created_at || '').slice(0, 16).replace('T', ' ')}
              </div>
            </button>
          ))}
        </div>
        <div className="p-2 border-t border-[var(--theme-border)] space-y-1.5">
          <button
            onClick={() => void viewSystem()}
            disabled={!!busy}
            className="w-full px-2 py-1.5 rounded border border-[var(--theme-border)] text-stone-200 font-bold hover:text-[var(--theme-primary)] disabled:opacity-40 cursor-pointer"
          >
            {busy === 'system' ? 'Reading system report…' : 'View live system report'}
          </button>
          <div className="flex gap-1.5">
            <select
              value={assessmentId}
              onChange={(e) => setAssessmentId(e.target.value)}
              className="flex-1 bg-black/60 border border-[var(--theme-border)] rounded px-2 py-1 text-stone-200 focus:outline-none"
            >
              {engagements.length === 0 && <option value="">No engagements</option>}
              {engagements.map((engagement) => (
                <option key={String(engagement.id)} value={String(engagement.id)}>
                  {String(engagement.name || engagement.id).slice(0, 32)}
                </option>
              ))}
            </select>
            <button
              onClick={() => void viewAssessment()}
              disabled={!!busy || !assessmentId}
              className="px-2 py-1 rounded bg-[var(--theme-primary)] text-black font-bold hover:opacity-90 disabled:opacity-40 cursor-pointer"
            >
              {busy === 'assessment' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : 'Assess'}
            </button>
          </div>
        </div>
      </div>

      {/* Reader */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {error && (
          <div className="p-2.5 rounded bg-rose-950/20 border border-rose-900/40 text-rose-400 whitespace-pre-wrap">{error}</div>
        )}
        {!selected && !systemReport && !assessment && !error && (
          <div className="h-full flex flex-col items-center justify-center gap-2 text-center">
            <FileText className="w-8 h-8 text-stone-700" />
            <div className="font-bold text-stone-300">Select a report to read it</div>
            <div className="text-stone-500 max-w-md leading-relaxed">
              Operation reports are written by the sidecar when tasks complete. The system report is generated
              live from this machine. Assessment reports compile per-engagement findings.
            </div>
            <button onClick={onNavigateToOut} className="mt-2 text-[var(--theme-primary)] hover:underline cursor-pointer">
              Browse /out evidence instead →
            </button>
          </div>
        )}

        {selected && selectedBody && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="font-bold text-stone-100 text-sm">{String(selected.title || 'Untitled')}</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded border border-[var(--theme-border)] text-[var(--theme-primary)]">
                {String(selected.kind || '')}
              </span>
              <span className="flex-1" />
              {FORMATS.map((format) => (
                <button
                  key={format}
                  onClick={() => download(String(selected.id), format)}
                  className="flex items-center gap-1 px-2 py-0.5 rounded border border-[var(--theme-border)] text-stone-300 hover:text-[var(--theme-primary)] cursor-pointer text-[10px]"
                >
                  <Download className="w-3 h-3" />
                  <span>.{format}</span>
                </button>
              ))}
              <button
                onClick={() => void remove(String(selected.id))}
                disabled={!!busy}
                className="flex items-center gap-1 px-2 py-0.5 rounded border border-rose-900/60 text-rose-300 hover:bg-rose-950/40 disabled:opacity-40 cursor-pointer text-[10px]"
              >
                {busy === `delete-${String(selected.id)}` ? <Loader2 className="w-3 h-3 animate-spin" /> : <Trash2 className="w-3 h-3" />}
                <span>Delete</span>
              </button>
            </div>
            <pre className="p-3 rounded bg-black/70 border border-[var(--theme-border)] text-stone-200 whitespace-pre-wrap leading-relaxed select-text">
              {String(selectedBody.markdown || JSON.stringify(selectedBody, null, 2)).slice(0, 12000)}
            </pre>
          </div>
        )}

        {systemReport && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="font-bold text-stone-100 text-sm">Live system report</span>
              <span className="flex-1" />
              <button
                onClick={() => { void apiDownload('/api/reports/system', 'vortex-system-report.json').catch((err: unknown) => setError(err instanceof Error ? err.message : String(err))); }}
                className="flex items-center gap-1 px-2 py-0.5 rounded border border-[var(--theme-border)] text-stone-300 hover:text-[var(--theme-primary)] cursor-pointer text-[10px]"
              >
                <Download className="w-3 h-3" />
                <span>.json</span>
              </button>
            </div>
            <pre className="p-3 rounded bg-black/70 border border-[var(--theme-border)] text-stone-300 whitespace-pre-wrap leading-relaxed select-text text-[11px]">
              {systemReport}
            </pre>
          </div>
        )}

        {assessment && (
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="font-bold text-stone-100 text-sm">Engagement assessment</span>
              <span className="flex-1" />
              <button
                onClick={() => { void apiDownload(`/api/reports/assessment/${encodeURIComponent(assessmentId)}?format=md`, `assessment-${assessmentId.slice(0, 8)}.md`).catch((err: unknown) => setError(err instanceof Error ? err.message : String(err))); }}
                className="flex items-center gap-1 px-2 py-0.5 rounded border border-[var(--theme-border)] text-stone-300 hover:text-[var(--theme-primary)] cursor-pointer text-[10px]"
              >
                <Download className="w-3 h-3" />
                <span>.md</span>
              </button>
            </div>
            <pre className="p-3 rounded bg-black/70 border border-[var(--theme-border)] text-stone-300 whitespace-pre-wrap leading-relaxed select-text text-[11px]">
              {assessment}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
};
