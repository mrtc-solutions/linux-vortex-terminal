/* /out explorer — REAL operation artifacts from the sidecar store.
   Files land here only when executed commands actually produce them. */
import React, { useCallback, useEffect, useState } from 'react';
import { FileSearch, FolderDown, Loader2, RefreshCw } from 'lucide-react';
import { JsonRecord, analyzeArtifact, listArtifacts } from '../services/vortexApi';
import { sound } from '../services/soundEffects';

interface OutDirectoryExplorerProps {
  onArtifactChange: () => void;
  onRunTerminalCommand: (cmd: string) => void;
}

export const OutDirectoryExplorer: React.FC<OutDirectoryExplorerProps> = ({ onArtifactChange, onRunTerminalCommand }) => {
  const [artifacts, setArtifacts] = useState<JsonRecord[]>([]);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [analysis, setAnalysis] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setError('');
    try {
      const payload = await listArtifacts();
      setArtifacts(Array.isArray(payload.artifacts) ? payload.artifacts as JsonRecord[] : []);
      onArtifactChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [onArtifactChange]);

  useEffect(() => { void refresh(); }, [refresh]);

  const analyze = async (artifact: JsonRecord, index: number) => {
    const path = String(artifact.path || '');
    if (!path || busy) return;
    setBusy(`analyze-${index}`);
    setError('');
    setAnalysis('');
    sound.playExecute();
    try {
      const payload = await analyzeArtifact(path);
      const result = (payload.analysis || payload.artifact || payload) as JsonRecord;
      setAnalysis(JSON.stringify(result, null, 2).slice(0, 3000));
      sound.playSuccess();
    } catch (err) {
      sound.playAlert();
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('');
    }
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden bg-[var(--theme-bg)] font-mono text-xs">
      <div className="flex items-center gap-2 px-4 py-2 border-b border-[var(--theme-border)] bg-[var(--theme-surface)]/70">
        <FolderDown className="w-4 h-4 text-[var(--theme-primary)]" />
        <span className="font-bold text-stone-200">/out ARTIFACTS</span>
        <span className="text-stone-500">{artifacts.length} stored</span>
        <span className="flex-1" />
        <button
          onClick={() => { setLoading(true); void refresh(); }}
          className="flex items-center gap-1 px-2 py-0.5 rounded border border-[var(--theme-border)] text-stone-300 hover:text-[var(--theme-primary)] cursor-pointer"
        >
          <RefreshCw className="w-3 h-3" />
          <span>Refresh</span>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-2">
        {error && (
          <div className="p-2.5 rounded bg-rose-950/20 border border-rose-900/40 text-rose-400 whitespace-pre-wrap">{error}</div>
        )}
        {loading && artifacts.length === 0 && <div className="text-stone-500">Reading stored artifacts…</div>}
        {!loading && artifacts.length === 0 && !error && (
          <div className="flex flex-col items-center justify-center gap-2 text-center p-8 h-full">
            <FolderDown className="w-8 h-8 text-stone-700" />
            <div className="font-bold text-stone-300">No artifacts yet</div>
            <div className="text-stone-500 max-w-md leading-relaxed">
              Artifacts appear when executed commands save evidence files — reports, captures, scan outputs.
              Nothing here is staged: run work in the terminal and its evidence lands here.
            </div>
            <button
              onClick={() => onRunTerminalCommand('Show a system health summary for this machine')}
              className="mt-2 px-3 py-1.5 rounded bg-[var(--theme-primary)] text-black font-bold hover:opacity-90 cursor-pointer"
            >
              Run something real
            </button>
          </div>
        )}

        {artifacts.map((artifact, index) => {
          const kind = String(artifact.kind || 'evidence');
          const state = String(artifact.state || 'unknown');
          const summary = String(artifact.summary || `${kind} · ${String(artifact.artifact_id || index).slice(0, 12)}`);
          const source = ((artifact.source || {}) as JsonRecord);
          const sourcePath = String(source.path || '');
          const observations = Array.isArray(artifact.observations) ? artifact.observations as JsonRecord[] : [];
          const limitations = Array.isArray(artifact.limitations) ? (artifact.limitations as unknown[]).map(String) : [];
          return (
            <div key={String(artifact.artifact_id || index)} className="rounded bg-black/60 border border-[var(--theme-border)] overflow-hidden">
              <button
                onClick={() => setExpanded(expanded === index ? null : index)}
                className="w-full flex items-center gap-2 p-2.5 text-left hover:bg-white/5 cursor-pointer"
              >
                <FileSearch className="w-4 h-4 text-[var(--theme-primary)] shrink-0" />
                <span className="font-bold text-stone-100 break-all">{summary}</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded border border-[var(--theme-border)] text-[var(--theme-primary)] shrink-0">{kind}</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded border border-stone-700 text-stone-400 shrink-0">{state}</span>
                <span className="flex-1" />
                {artifact.size_bytes != null && <span className="text-[10px] text-stone-500 shrink-0">{String(artifact.size_bytes)} B</span>}
              </button>
              {expanded === index && (
                <div className="border-t border-[var(--theme-border)]/50 p-2.5 space-y-2">
                  {sourcePath && <div className="text-[10px] text-stone-500 font-mono break-all">source: {sourcePath}</div>}
                  {artifact.sha256 ? <div className="text-[10px] text-stone-600 font-mono break-all">sha256: {String(artifact.sha256).slice(0, 32)}…</div> : null}
                  {observations.length > 0 && (
                    <div className="space-y-1">
                      <div className="text-[10px] uppercase tracking-wider text-stone-500 font-semibold">
                        Observations ({observations.length})
                      </div>
                      {observations.slice(0, 20).map((observation, obsIndex) => (
                        <div key={obsIndex} className="text-[11px] text-stone-300 font-mono break-all">
                          <span className="text-[var(--theme-primary)]">{String(observation.name || observation.type || '?')}</span>
                          {' = '}{String(observation.value ?? '').slice(0, 200)}
                        </div>
                      ))}
                    </div>
                  )}
                  {limitations.length > 0 && (
                    <div className="text-[10px] text-stone-600 leading-relaxed">
                      {limitations.slice(0, 3).map((limitation, limIndex) => (
                        <div key={limIndex}>• {limitation}</div>
                      ))}
                    </div>
                  )}
                  <pre className="text-[10px] leading-relaxed text-stone-500 whitespace-pre-wrap break-all max-h-40 overflow-y-auto border-t border-[var(--theme-border)]/30 pt-2">
                    {JSON.stringify(artifact, null, 2).slice(0, 2000)}
                  </pre>
                  {sourcePath ? (
                    <button
                      onClick={() => void analyze({ ...artifact, path: sourcePath }, index)}
                      disabled={!!busy}
                      className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-[var(--theme-primary)] text-black font-bold hover:opacity-90 disabled:opacity-40 cursor-pointer"
                    >
                      {busy === `analyze-${index}` ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <FileSearch className="w-3.5 h-3.5" />}
                      <span>Re-analyze source file</span>
                    </button>
                  ) : (
                    <div className="text-[10px] text-stone-600">No source file recorded for this artifact — nothing to re-analyze.</div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {analysis && (
          <div className="rounded bg-black/70 border border-[var(--theme-border)] p-3 space-y-1.5">
            <div className="text-[10px] uppercase tracking-wider text-stone-500 font-semibold">Evidence analysis</div>
            <pre className="text-[11px] leading-relaxed text-stone-200 whitespace-pre-wrap">{analysis}</pre>
          </div>
        )}
      </div>
    </div>
  );
};
