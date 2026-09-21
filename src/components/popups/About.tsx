/* About popup — real version/license plus the real installable artifacts.
   Every status line is sidecar-backed; iOS is honestly marked unavailable. */
import React, { useCallback, useEffect, useState } from 'react';
import { Download, Info, Loader2, Package, RefreshCw, Scale, Smartphone } from 'lucide-react';
import {
  JsonRecord, buildDeb, downloadApk, downloadDeb, getApkStatus, getDebStatus,
  getHealth, getLicense, syncApk,
} from '../../services/vortexApi';
import { EmptyLine, ErrorLine, GhostButton, PrimaryButton, Section, StateBadge, asRecord } from './common';

function mb(bytes: number): string {
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

function shortHash(hash: string): string {
  return hash.length > 16 ? `${hash.slice(0, 12)}…` : hash;
}

export const About: React.FC = () => {
  const [health, setHealth] = useState<JsonRecord | null>(null);
  const [license, setLicense] = useState<JsonRecord | null>(null);
  const [apk, setApk] = useState<JsonRecord | null>(null);
  const [deb, setDeb] = useState<JsonRecord | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setError('');
    try {
      const [h, l, a, d] = await Promise.all([getHealth(), getLicense(), getApkStatus(), getDebStatus()]);
      setHealth(asRecord(h) as JsonRecord);
      setLicense(asRecord(l) as JsonRecord);
      setApk(asRecord(a.apk) as JsonRecord);
      setDeb(asRecord(d.deb) as JsonRecord);
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

  const licenseText = String(license?.license || '');
  const noticeText = String(license?.notice || '');

  return (
    <div className="p-4 space-y-4 text-stone-300">
      <div className="flex items-center gap-2">
        <Info className="w-4 h-4 text-[var(--theme-primary)]" />
        <span className="text-[12px] font-bold text-stone-200">About Vortex Terminal</span>
        {health?.version ? (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-[var(--theme-border)] font-mono opacity-80">
            v{String(health.version)}
          </span>
        ) : null}
        <span className="flex-1" />
        <GhostButton onClick={() => { setLoading(true); void refresh(); }} disabled={loading}>
          <span className="flex items-center gap-1"><RefreshCw className="w-3 h-3" />Refresh</span>
        </GhostButton>
      </div>

      <ErrorLine message={error} />
      {loading && !health && <EmptyLine message="Reading live version, license, and package state…" />}

      {health && (
        <Section title="This app">
          <div className="p-2 rounded bg-black/50 border border-[var(--theme-border)] space-y-1 text-[11px]">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-stone-500">sidecar:</span>
              <StateBadge state={health.ok === true ? 'online' : 'error'} />
              {health.backend ? <span className="font-mono text-stone-400">{String(health.backend)}</span> : null}
            </div>
            <div className="text-stone-400 leading-relaxed">
              Vortex Terminal is a local-first Linux terminal: deterministic orchestration over
              reviewed adapters, Guardian-reviewed plans, a loopback-only sidecar, and on-device
              AI with the llamafile server preferred. Nothing here is simulated — every number
              on this screen came from the sidecar just now.
            </div>
          </div>
        </Section>
      )}

      <Section title="Author">
        <div className="p-2 rounded bg-black/50 border border-[var(--theme-border)] space-y-1 text-[11px] text-stone-400 leading-relaxed">
          <div className="text-stone-200 font-bold">Francis Fweta, certified cybersecurity specialist and developer</div>
          <div>Vortex Terminal started in 2025 and was released 04 August 2026.</div>
          <div>Dedicated to his daughter Theodora (born 2026).</div>
        </div>
      </Section>

      {license && (
        <Section title={`${String(license.name || 'License')} · ${String(license.spdx || '')}`}>
          <div className="p-2 rounded bg-black/50 border border-[var(--theme-border)] space-y-1.5">
            <div className="flex items-center gap-2 text-[11px] text-stone-400">
              <Scale className="w-3.5 h-3.5 text-[var(--theme-primary)]" />
              <span>Vortex Terminal is free software under the MIT License.</span>
            </div>
            {licenseText ? (
              <pre className="text-[10px] text-stone-400 font-mono whitespace-pre-wrap max-h-40 overflow-y-auto p-2 rounded bg-black/60 border border-[var(--theme-border)]">
                {licenseText.slice(0, 8000)}
              </pre>
            ) : <EmptyLine message="License text was not returned by the sidecar." />}
            {noticeText ? (
              <pre className="text-[10px] text-stone-500 font-mono whitespace-pre-wrap max-h-24 overflow-y-auto p-2 rounded bg-black/60 border border-[var(--theme-border)]">
                {noticeText.slice(0, 4000)}
              </pre>
            ) : null}
          </div>
        </Section>
      )}

      {apk && (
        <Section title="Android APK">
          <div className="p-2 rounded bg-black/50 border border-[var(--theme-border)] space-y-1.5 text-[11px]">
            <div className="flex items-center gap-2 flex-wrap">
              <Smartphone className="w-3.5 h-3.5 text-[var(--theme-primary)]" />
              <StateBadge state={apk.built === true ? 'built' : 'missing'} />
              {apk.built === true && (
                <span className="font-mono text-stone-400">
                  {mb(Number(apk.size_bytes || 0))} · sha256 {shortHash(String(apk.sha256 || ''))}
                </span>
              )}
              {apk.built !== true && apk.message ? (
                <span className="text-stone-500">{String(apk.message)}</span>
              ) : null}
            </div>
            {apk.built === true && apk.mtime ? (
              <div className="text-[10px] text-stone-600 font-mono">built {String(apk.mtime)}</div>
            ) : null}
            <div className="flex items-center gap-2 flex-wrap">
              <PrimaryButton onClick={() => void run('apk', syncApk)} disabled={!!busy}>
                <span className="flex items-center gap-1">
                  {busy === 'apk' ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                  Sync APK
                </span>
              </PrimaryButton>
              {apk.built === true && (
                <GhostButton onClick={() => void run('apk-dl', downloadApk)} disabled={!!busy}>
                  <span className="flex items-center gap-1">
                    {busy === 'apk-dl' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />}
                    Download
                  </span>
                </GhostButton>
              )}
            </div>
            <div className="text-[10px] text-stone-600">
              Sync rebuilds and re-signs the APK against this sidecar, then verifies size and SHA-256 before download.
            </div>
          </div>
        </Section>
      )}

      {deb && (
        <Section title="Linux DEB">
          <div className="p-2 rounded bg-black/50 border border-[var(--theme-border)] space-y-1.5 text-[11px]">
            <div className="flex items-center gap-2 flex-wrap">
              <Package className="w-3.5 h-3.5 text-[var(--theme-primary)]" />
              <StateBadge state={deb.built === true ? 'built' : 'missing'} />
              {deb.built === true && (
                <span className="font-mono text-stone-400">
                  {String(deb.filename || 'package.deb')} · {mb(Number(deb.size_bytes || 0))}
                </span>
              )}
              {deb.built !== true && deb.message ? (
                <span className="text-stone-500">{String(deb.message)}</span>
              ) : null}
            </div>
            {deb.built === true && deb.sha256 ? (
              <div className="text-[10px] text-stone-600 font-mono">sha256 {shortHash(String(deb.sha256))}</div>
            ) : null}
            <div className="flex items-center gap-2 flex-wrap">
              <PrimaryButton onClick={() => void run('deb', buildDeb)} disabled={!!busy}>
                <span className="flex items-center gap-1">
                  {busy === 'deb' ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                  Build DEB
                </span>
              </PrimaryButton>
              {deb.built === true && (
                <GhostButton onClick={() => void run('deb-dl', () => downloadDeb(String(deb.filename || '')))} disabled={!!busy}>
                  <span className="flex items-center gap-1">
                    {busy === 'deb-dl' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />}
                    Download
                  </span>
                </GhostButton>
              )}
            </div>
          </div>
        </Section>
      )}

      <Section title="iOS">
        <div className="p-2 rounded bg-black/50 border border-[var(--theme-border)] text-[11px] text-stone-400 leading-relaxed">
          No iOS package is offered. iOS apps require Apple Developer signing on macOS hardware,
          which this Linux project cannot produce or verify — so there is no download button
          here on purpose. The Android APK and Linux DEB above are the real installable artifacts.
        </div>
      </Section>
    </div>
  );
};
