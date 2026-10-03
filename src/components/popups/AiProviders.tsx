/* AI Providers panel — multi-provider layer: local Ollama + free cloud tiers.
   Shows real, live provider state from the sidecar ProviderManager:
   enabled/disabled, key configured, free/paid/unknown billing, latency,
   cooldowns, discovered models, and the FREE-ONLY cost guarantee.
   Cloud models are CONNECTED (API), never "downloaded". */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Cloud, Cpu, Loader2, RefreshCw, ShieldCheck, Stethoscope } from 'lucide-react';
import {
  JsonRecord, checkProvider, configureGemini, getProviderDiagnostics, getProviders,
  refreshProviders, saveSettings, selectProviderModel, setProviderEnabled,
  warmupLocalModel,
} from '../../services/vortexApi';
import { EmptyLine, ErrorLine, GhostButton, PrimaryButton, Section, StateBadge, asRecord, inputCls } from './common';

function asList(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? (value as JsonRecord[]) : [];
}

function billingLabel(provider: JsonRecord): { label: string; cls: string } {
  const status = String(provider.free_status || 'unknown');
  if (provider.mode === 'local') return { label: 'LOCAL / $0', cls: 'text-emerald-400 border-emerald-800' };
  if (status === 'free') return { label: 'FREE', cls: 'text-emerald-400 border-emerald-800' };
  if (status === 'conditional') return { label: 'FREE TIER', cls: 'text-amber-300 border-amber-800' };
  return { label: 'FREE STATUS: UNKNOWN', cls: 'text-rose-300 border-rose-900' };
}

function healthLabel(provider: JsonRecord): string {
  const health = asRecord(provider.health);
  const stats = asRecord(provider.stats);
  if (health.state) return String(health.state);
  if (!provider.enabled) return 'disabled';
  if (provider.requires_api_key && !provider.key_configured) return 'no_api_key';
  if (stats.last_error_kind) return String(stats.last_error_kind);
  return 'unchecked';
}

const GROUP_LABELS: Record<string, string> = {
  'ollama': 'LOCAL', 'google-gemini': 'GOOGLE', 'groq': 'GROQ', 'openrouter': 'OPENROUTER',
  'cloudflare': 'CLOUDFLARE', 'pollinations': 'POLLINATIONS',
};

const ProviderRow: React.FC<{
  provider: JsonRecord;
  active: boolean;
  busy: string;
  onAction: (label: string, fn: () => Promise<unknown>) => void;
}> = ({ provider, active, busy, onAction }) => {
  const id = String(provider.id);
  const models = asList(provider.models);
  const freeModels = models.filter((m) => m.free === true && m.available !== false);
  const billing = billingLabel(provider);
  const stats = asRecord(provider.stats);
  const health = asRecord(provider.health);
  const gemini = asRecord(provider.gemini);
  const [model, setModel] = useState(String(gemini.model || provider.default_model || ''));

  useEffect(() => {
    setModel(String(asRecord(provider.gemini).model || provider.default_model || ''));
  }, [provider]);

  return (
    <div className={`p-2 rounded border space-y-1.5 ${active ? 'border-[var(--theme-primary)] bg-black/60' : 'border-[var(--theme-border)] bg-black/40'}`}>
      <div className="flex items-center gap-2 flex-wrap">
        {provider.mode === 'local'
          ? <Cpu className="w-3.5 h-3.5 text-[var(--theme-primary)]" />
          : <Cloud className="w-3.5 h-3.5 text-stone-400" />}
        <span className="font-bold text-[12px] text-stone-200">{String(provider.name)}</span>
        <span className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${billing.cls}`}>{billing.label}</span>
        <StateBadge state={healthLabel(provider)} />
        {active ? <span className="text-[9px] font-bold px-1.5 py-0.5 rounded border text-sky-300 border-sky-800">ACTIVE</span> : null}
        <span className="ml-auto text-[10px] text-stone-500">
          {stats.latency_ms_ewma ? `${(Number(stats.latency_ms_ewma) / 1000).toFixed(1)}s` : ''}
        </span>
      </div>
      <div className="text-[10px] text-stone-500">
        {String(provider.mode).toUpperCase()}
        {provider.requires_api_key ? ` · key ${provider.key_configured ? 'configured' : `missing (${String(provider.key_slot)})`}` : ' · no key needed'}
        {provider.models_refreshed_at ? ` · models checked ${String(provider.models_refreshed_at)}` : ' · models not discovered yet'}
        {Number(stats.cooldown_seconds) > 0 ? ` · cooling down ${String(stats.cooldown_seconds)}s` : ''}
      </div>
      {health.detail ? <div className="text-[10px] text-stone-400">{String(health.detail)}</div> : null}
      {stats.last_error ? (
        <div className="text-[10px] text-rose-400/80">{String(stats.last_error_kind)}: {String(stats.last_error)}</div>
      ) : null}
      {provider.cloud_blocked ? <div className="text-[10px] text-amber-400">{String(provider.cloud_blocked)}</div> : null}
      {!provider.policy_allowed ? <div className="text-[10px] text-amber-400">{String(provider.policy_reason)}</div> : null}
      {gemini.key_slot ? (
        <div className="flex items-center gap-2 text-[10px] text-stone-400">
          <span>Model</span>
          <input className={`${inputCls} max-w-[200px]`} value={model} onChange={(e) => setModel(e.target.value)} />
          <span>Key slot</span>
          <select
            className={`${inputCls} max-w-[170px]`}
            value={String(gemini.key_slot)}
            onChange={(e) => onAction(`gemini-${id}`, () => configureGemini(id, undefined, e.target.value))}
          >
            <option value="GEMINI_API_KEY_1">GEMINI_API_KEY_1</option>
            <option value="GEMINI_API_KEY_2">GEMINI_API_KEY_2</option>
            <option value="GEMINI_API_KEY_3">GEMINI_API_KEY_3</option>
          </select>
          <GhostButton disabled={!!busy} onClick={() => onAction(`gemini-${id}`, () => configureGemini(id, model))}>Save model</GhostButton>
        </div>
      ) : null}
      {models.length > 0 && !gemini.key_slot ? (
        <div className="text-[10px] text-stone-500">
          {freeModels.length} verified $0 model(s) of {models.length} discovered
          {freeModels.length > 0 ? ` — e.g. ${freeModels.slice(0, 3).map((m) => String(m.id)).join(', ')}` : ''}
        </div>
      ) : null}
      <div className="flex items-center gap-2 flex-wrap">
        <GhostButton disabled={!!busy} onClick={() => onAction(`check-${id}`, () => checkProvider(id))}>
          {busy === `check-${id}` ? <Loader2 className="w-3 h-3 animate-spin inline" /> : null} Check availability
        </GhostButton>
        <GhostButton
          disabled={!!busy}
          onClick={() => onAction(`toggle-${id}`, () => setProviderEnabled(id, !(provider.enabled === true)))}
        >
          {provider.enabled ? 'Disable' : 'Enable'}
        </GhostButton>
        {String(provider.free_status) === 'unknown' && provider.enabled ? (
          <GhostButton
            disabled={!!busy}
            title="Only after you verified the provider's terms yourself"
            onClick={() => onAction(`free-${id}`, () => setProviderEnabled(id, true, !(provider.allow_in_free_mode === true)))}
          >
            {provider.allow_in_free_mode ? 'Revoke free-mode override' : 'I verified it is free'}
          </GhostButton>
        ) : null}
        {!active ? (
          <PrimaryButton disabled={!!busy || !(provider.enabled === true)} onClick={() => onAction(`select-${id}`, () => selectProviderModel(id))}>
            Use for conversation
          </PrimaryButton>
        ) : null}
        {id === 'ollama-local' ? (
          <GhostButton disabled={!!busy} onClick={() => onAction('warmup', () => warmupLocalModel())}>
            {busy === 'warmup' ? <Loader2 className="w-3 h-3 animate-spin inline" /> : null} Warm up Qwen
          </GhostButton>
        ) : null}
      </div>
    </div>
  );
};

export const AiProviders: React.FC = () => {
  const [snapshot, setSnapshot] = useState<JsonRecord | null>(null);
  const [diagnostics, setDiagnostics] = useState('');
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async (fresh = false) => {
    setError('');
    try {
      const payload = await getProviders(fresh);
      setSnapshot(asRecord(payload.providers) as JsonRecord);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(true); }, [refresh]);

  const onAction = useCallback(async (label: string, fn: () => Promise<unknown>) => {
    if (busy) return;
    setBusy(label);
    setError('');
    try {
      await fn();
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('');
    }
  }, [busy, refresh]);

  const providers = asList(snapshot?.providers);
  const local = asRecord(snapshot?.local);
  const freeOnly = snapshot?.free_only === true;
  const cloudGate = snapshot?.cloud_gate ? String(snapshot.cloud_gate) : '';
  const activeProvider = String(snapshot?.conversation_provider || 'auto');

  const groups = useMemo(() => {
    const byGroup = new Map<string, JsonRecord[]>();
    for (const provider of providers) {
      const family = String(provider.family || provider.id);
      const key = GROUP_LABELS[family] || 'OTHER CLOUD PROVIDERS';
      byGroup.set(key, [...(byGroup.get(key) || []), provider]);
    }
    return byGroup;
  }, [providers]);

  return (
    <div className="p-3 space-y-3 text-stone-300 overflow-y-auto h-full">
      <div className="flex items-center gap-2 flex-wrap">
        {freeOnly ? (
          <span className="flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded border text-emerald-400 border-emerald-800 bg-emerald-950/40">
            <ShieldCheck className="w-3 h-3" /> FREE ONLY — $0 MODE
          </span>
        ) : (
          <span className="text-[10px] font-bold px-2 py-0.5 rounded border text-amber-300 border-amber-800">PAID PROVIDERS PERMITTED</span>
        )}
        <span className="text-[10px] text-stone-500">
          Conversation: {activeProvider === 'auto' ? 'automatic fallback order' : activeProvider}
        </span>
        <span className="ml-auto flex items-center gap-2">
          <GhostButton disabled={!!busy} onClick={() => onAction('diag', async () => {
            const payload = await getProviderDiagnostics();
            setDiagnostics(String(asRecord(payload.diagnostics).text || ''));
            setShowDiagnostics(true);
          })}>
            <Stethoscope className="w-3 h-3 inline" /> Diagnostics
          </GhostButton>
          <GhostButton disabled={!!busy} onClick={() => onAction('refresh', () => refreshProviders())}>
            {busy === 'refresh' ? <Loader2 className="w-3 h-3 animate-spin inline" /> : <RefreshCw className="w-3 h-3 inline" />} Re-check all
          </GhostButton>
          {activeProvider !== 'auto' ? (
            <GhostButton disabled={!!busy} onClick={() => onAction('auto', () => selectProviderModel('auto'))}>Back to auto</GhostButton>
          ) : null}
        </span>
      </div>
      <ErrorLine message={error} />
      {cloudGate ? (
        <div className="text-[11px] text-amber-300 p-2 rounded bg-amber-950/20 border border-amber-900/40 flex items-center gap-2 flex-wrap">
          <span>{cloudGate}</span>
          <GhostButton disabled={!!busy} onClick={() => onAction('privacy', async () => {
            await saveSettings({ privacy_mode: 'hybrid' });
          })}>Allow cloud fallback (privacy: hybrid)</GhostButton>
        </div>
      ) : null}
      <div className="text-[11px] text-stone-400 p-2 rounded bg-black/40 border border-[var(--theme-border)]">
        Local Qwen: <span className="text-stone-200 font-semibold">{String(local.message || local.state || 'unknown')}</span>
        {local.latency_ms ? <span className="text-stone-500"> ({(Number(local.latency_ms) / 1000).toFixed(1)}s probe)</span> : null}
        <div className="text-[10px] text-stone-500 mt-1">
          Cloud models are connected through provider APIs — they are never downloaded. Free catalogs change over time;
          pricing is re-verified at discovery and a model that stops being $0 is blocked in free-only mode.
        </div>
      </div>
      {loading ? <EmptyLine message="Loading live provider state…" /> : null}
      {showDiagnostics && diagnostics ? (
        <Section title="Provider diagnostics (credentials masked)">
          <pre className="text-[10px] text-stone-400 whitespace-pre-wrap bg-black/50 border border-[var(--theme-border)] rounded p-2 max-h-64 overflow-y-auto">{diagnostics}</pre>
          <GhostButton onClick={() => setShowDiagnostics(false)}>Hide diagnostics</GhostButton>
        </Section>
      ) : null}
      {[...groups.entries()].map(([label, rows]) => (
        <Section key={label} title={label}>
          <div className="space-y-2">
            {rows.map((provider) => (
              <ProviderRow
                key={String(provider.id)}
                provider={provider}
                active={activeProvider === String(provider.id)}
                busy={busy}
                onAction={onAction}
              />
            ))}
          </div>
        </Section>
      ))}
      {providers.length === 0 && !loading ? <EmptyLine message="No provider state available from the sidecar." /> : null}
    </div>
  );
};
