/* Local AI popup — real provider states, fuzzy routing, llamafile lifecycle. */
import React, { useCallback, useEffect, useState } from 'react';
import { BrainCircuit, Download, Loader2, Play, RefreshCw, Square } from 'lucide-react';
import {
  JsonRecord, cancelLlamafileInstall, getGguf, getLlamafile, getModels, getOllama,
  installLlamafile, startLlamafileServer, stopLlamafileServer,
} from '../../services/vortexApi';
import { EmptyLine, ErrorLine, GhostButton, PrimaryButton, Section, StateBadge, asRecord } from './common';

function ProviderCard({ name, detail }: { name: string; detail: JsonRecord }) {
  const state = String(detail.state || 'unknown');
  return (
    <div className="p-2 rounded bg-black/50 border border-[var(--theme-border)] space-y-1">
      <div className="flex items-center gap-2">
        <span className="font-bold text-[12px] text-stone-200">{name}</span>
        <StateBadge state={state} />
      </div>
      {detail.reason ? <div className="text-[11px] text-stone-400">{String(detail.reason)}</div> : null}
      {detail.endpoint ? <div className="text-[10px] text-stone-500 font-mono">{String(detail.endpoint)}</div> : null}
    </div>
  );
}

export const Models: React.FC = () => {
  const [models, setModels] = useState<JsonRecord | null>(null);
  const [llamafile, setLlamafile] = useState<JsonRecord | null>(null);
  const [gguf, setGguf] = useState<JsonRecord | null>(null);
  const [ollama, setOllama] = useState<JsonRecord | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(true);
  const [confirmInstall, setConfirmInstall] = useState(false);

  const refresh = useCallback(async () => {
    setError('');
    try {
      const [m, l, g, o] = await Promise.all([getModels(), getLlamafile(), getGguf(), getOllama()]);
      setModels(asRecord(m.model) as JsonRecord);
      setLlamafile(asRecord(l.llamafile) as JsonRecord);
      setGguf(asRecord(g.gguf) as JsonRecord);
      setOllama(asRecord(o.ollama ?? o) as JsonRecord);
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

  const fuzzy = asRecord(models?.fuzzy) as JsonRecord;
  const ranking = Array.isArray(fuzzy.ranking) ? fuzzy.ranking as JsonRecord[] : [];
  const providers = asRecord(models?.providers) as JsonRecord;
  const install = asRecord(llamafile?.install) as JsonRecord;
  const server = asRecord(llamafile?.server) as JsonRecord;
  const binary = asRecord(llamafile?.binary) as JsonRecord;
  const installActive = install.status === 'downloading' || install.status === 'running'
    || install.status === 'started' || install.status === 'starting';

  // Poll progress while a download is in flight (3s cadence, operator-visible only).
  useEffect(() => {
    if (!installActive) return undefined;
    const timer = window.setInterval(() => { void refresh(); }, 3000);
    return () => window.clearInterval(timer);
  }, [installActive, refresh]);

  return (
    <div className="p-4 space-y-4 text-stone-300">
      <div className="flex items-center gap-2">
        <BrainCircuit className="w-4 h-4 text-[var(--theme-primary)]" />
        <span className="text-[12px] font-bold text-stone-200">Local-first routing</span>
        <span className="flex-1" />
        <GhostButton onClick={() => { setLoading(true); void refresh(); }} disabled={loading}>
          <span className="flex items-center gap-1"><RefreshCw className="w-3 h-3" />Refresh</span>
        </GhostButton>
      </div>

      <ErrorLine message={error} />
      {loading && !models && <EmptyLine message="Reading live model state…" />}

      {models && (
        <Section title={`Fuzzy router · selected: ${String(models.selected || 'none')} · confidence: ${String(fuzzy.confidence || fuzzy.phase || 'n/a')}`}>
          {ranking.length === 0 && <EmptyLine message="No routing candidates were scored." />}
          {ranking.map((entry, index) => (
            <div key={index} className="flex items-center gap-2 p-1.5 rounded bg-black/50 border border-[var(--theme-border)] font-mono text-[11px]">
              <span className="text-stone-500 w-4">{index + 1}.</span>
              <span className="text-stone-200 font-bold">{String(entry.provider || '?')}</span>
              <span className="text-stone-500">score {Number(entry.score ?? 0).toFixed(2)}</span>
              {entry.latency_ms != null && <span className="text-stone-500">{String(entry.latency_ms)}ms</span>}
            </div>
          ))}
          {models.message ? <div className="text-[11px] text-stone-500">{String(models.message).slice(0, 300)}</div> : null}
        </Section>
      )}

      {models && (
        <Section title="Providers">
          <div className="grid grid-cols-1 gap-1.5">
            {['llamafile', 'gguf', 'ollama', 'council', 'deterministic'].map((name) => (
              providers[name] && typeof providers[name] === 'object'
                ? <ProviderCard key={name} name={name} detail={providers[name] as JsonRecord} />
                : null
            ))}
          </div>
        </Section>
      )}

      {llamafile && (
        <Section title={`llamafile ${String(llamafile.version || '')}`}>
          <div className="p-2 rounded bg-black/50 border border-[var(--theme-border)] space-y-1.5 text-[11px]">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-stone-500">binary:</span>
              <StateBadge state={binary.present === true ? 'installed' : 'missing'} />
              {binary.reason ? <span className="text-stone-500">{String(binary.reason)}</span> : null}
            </div>
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-stone-500">server:</span>
              <StateBadge state={String(server.state || 'unknown')} />
              {server.endpoint ? <span className="font-mono text-stone-400">{String(server.endpoint)}</span> : null}
              {server.model ? <span className="font-mono text-stone-500">{String(server.model)}</span> : null}
            </div>
            {installActive && (
              <div className="flex items-center gap-2 text-[var(--theme-primary)]">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>Downloading {String(install.asset || 'llamafile')}… {String(install.received_bytes || 0)} bytes</span>
              </div>
            )}
            {install.error ? <div className="text-rose-400">{String(install.error)}</div> : null}
            <div className="flex items-center gap-2 pt-1 flex-wrap">
              {binary.present !== true && !installActive && !confirmInstall && (
                <PrimaryButton onClick={() => setConfirmInstall(true)} disabled={!!busy}>
                  <span className="flex items-center gap-1">
                    <Download className="w-3 h-3" />
                    Install llamafile
                  </span>
                </PrimaryButton>
              )}
              {binary.present !== true && !installActive && confirmInstall && (
                <>
                  <PrimaryButton
                    onClick={() => { setConfirmInstall(false); void run('install', () => installLlamafile(true)); }}
                    disabled={!!busy}
                  >
                    <span className="flex items-center gap-1">
                      {busy === 'install' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />}
                      Confirm download
                    </span>
                  </PrimaryButton>
                  <GhostButton onClick={() => setConfirmInstall(false)} disabled={!!busy}>Back</GhostButton>
                </>
              )}
              {installActive && (
                <GhostButton onClick={() => void run('cancel-install', cancelLlamafileInstall)} disabled={!!busy}>
                  {busy === 'cancel-install' ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Cancel download'}
                </GhostButton>
              )}
              {String(server.state || '') === 'stopped' && binary.present === true && (
                <PrimaryButton onClick={() => void run('start', () => startLlamafileServer())} disabled={!!busy}>
                  <span className="flex items-center gap-1">
                    {busy === 'start' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Play className="w-3 h-3" />}
                    Start server
                  </span>
                </PrimaryButton>
              )}
              {String(server.state || '') !== 'stopped' && (
                <GhostButton onClick={() => void run('stop', stopLlamafileServer)} disabled={!!busy}>
                  <span className="flex items-center gap-1">
                    {busy === 'stop' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Square className="w-3 h-3" />}
                    Stop server
                  </span>
                </GhostButton>
              )}
              <GhostButton onClick={() => { setLoading(true); void refresh(); }} disabled={!!busy}>Recheck</GhostButton>
            </div>
            {confirmInstall && !installActive && (
              <div className="text-[11px] text-amber-300 p-2 rounded bg-amber-950/20 border border-amber-900/40">
                This downloads the pinned llamafile {String(llamafile.version || '')} binary from GitHub
                (SHA-256 verified, ~GB scale). Nothing downloads until you confirm.
              </div>
            )}
            <div className="text-[10px] text-stone-600">
              Free, local, loopback-only. Install fetches a pinned llamafile release; the model file itself goes in the GGUF directories below.
            </div>
          </div>
        </Section>
      )}

      {gguf && (
        <Section title="GGUF files">
          <div className="p-2 rounded bg-black/50 border border-[var(--theme-border)] space-y-1 text-[11px]">
            <div className="text-stone-500">Engine: <StateBadge state={String(asRecord(gguf.engine).state || 'unknown')} /></div>
            {(Array.isArray(gguf.directories) ? gguf.directories as unknown[] : []).map((dir, i) => (
              <div key={i} className="font-mono text-stone-500 text-[10px]">{String(dir)}</div>
            ))}
            {(Array.isArray(gguf.files) ? gguf.files as JsonRecord[] : []).length === 0
              ? <EmptyLine message={String(gguf.reason || 'No .gguf files found. Drop one into a directory above, then Recheck.')} />
              : (gguf.files as JsonRecord[]).map((file, i) => (
                <div key={i} className="font-mono text-stone-300">{String(file.name || file.path || file)}</div>
              ))}
          </div>
        </Section>
      )}

      {ollama && typeof ollama === 'object' && (
        <Section title="Ollama">
          <div className="text-[11px] text-stone-400">
            <StateBadge state={String(asRecord(ollama).state || (providers.ollama as JsonRecord | undefined)?.state || 'unknown')} />
            <span className="ml-2">{String(asRecord(ollama).reason || (providers.ollama as JsonRecord | undefined)?.reason || '')}</span>
          </div>
        </Section>
      )}
    </div>
  );
};
