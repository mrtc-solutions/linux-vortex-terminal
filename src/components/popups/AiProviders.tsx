/* AI Providers panel — multi-provider layer: local Ollama + free cloud tiers.
   Shows real, live provider state from the sidecar ProviderManager:
   enabled/disabled, key configured, free/paid/unknown billing, latency,
   cooldowns, discovered models, and the FREE-ONLY cost guarantee.
   Cloud models are CONNECTED (API), never "downloaded". */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Cloud,
  Cpu,
  ExternalLink,
  Flame,
  Globe,
  Key,
  Layers,
  Loader2,
  Lock,
  RefreshCw,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Stethoscope,
  Zap,
} from 'lucide-react';
import {
  JsonRecord, checkProvider, configureGemini, getProviderDiagnostics, getProviders,
  refreshProviders, saveSettings, selectProviderModel, setProviderEnabled,
  warmupLocalModel,
} from '../../services/vortexApi';
import { EmptyLine, ErrorLine, GhostButton, PrimaryButton, Section, StateBadge, asRecord, inputCls } from './common';

function asList(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? (value as JsonRecord[]) : [];
}

function billingBadge(provider: JsonRecord): { label: string; cls: string; desc?: string } {
  const status = String(provider.free_category || provider.free_status || 'UNKNOWN');
  if (provider.mode === 'local' || status === 'LOCAL_$0') {
    return { label: 'LOCAL · $0', cls: 'text-emerald-400 border-emerald-800 bg-emerald-950/40', desc: 'Runs locally on this machine at $0 forever.' };
  }
  if (status === 'FREE_NO_CARD') {
    return { label: 'FREE (NO CARD)', cls: 'text-emerald-400 border-emerald-800 bg-emerald-950/30', desc: 'Free API tier with no credit card required.' };
  }
  if (status === 'FREE_REGISTRATION') {
    return { label: 'FREE (REGISTER)', cls: 'text-teal-300 border-teal-800 bg-teal-950/30', desc: 'Free tier with standard account registration.' };
  }
  if (status === 'FREE_PHONE_VERIFICATION') {
    return { label: 'PHONE VERIFY', cls: 'text-cyan-300 border-cyan-800 bg-cyan-950/30', desc: 'Free credits/tier requiring SMS/phone verification.' };
  }
  if (status === 'FREE_RATE_LIMITED') {
    return { label: 'RATE LIMITED', cls: 'text-amber-300 border-amber-800 bg-amber-950/30', desc: 'Free tier subject to strict requests/day and requests/min caps.' };
  }
  if (status === 'FREE_BILLABLE_OVERAGE') {
    return { label: 'BILLABLE OVERAGE', cls: 'text-amber-400 border-amber-800 bg-amber-950/40', desc: 'Free quota, but exceeding usage may incur billable charges if card attached.' };
  }
  if (status === 'RENEWABLE_CREDITS') {
    return { label: 'RENEWABLE CREDITS', cls: 'text-sky-300 border-sky-800 bg-sky-950/30', desc: 'Free recurring monthly credits.' };
  }
  if (status === 'TRIAL_ONLY') {
    return { label: 'TRIAL ONLY', cls: 'text-orange-400 border-orange-900 bg-orange-950/40', desc: 'Time-limited or one-off trial credits (blocked in free-only mode).' };
  }
  if (status === 'PAID') {
    return { label: 'PAID ONLY', cls: 'text-rose-400 border-rose-900 bg-rose-950/40', desc: 'Paid inference provider (blocked in free-only mode).' };
  }
  return { label: 'FREE STATUS: UNKNOWN', cls: 'text-stone-400 border-stone-700 bg-stone-900/40', desc: 'Pricing unverified. Blocked in free-only mode unless manually overridden.' };
}

function healthLabel(provider: JsonRecord): string {
  const health = asRecord(provider.health);
  const stats = asRecord(provider.stats);
  if (health.state) return String(health.state);
  if (!provider.enabled) return 'disabled';
  if (provider.requires_api_key && !provider.key_configured) return 'NOT CONFIGURED';
  if (stats.last_error_kind) return String(stats.last_error_kind);
  return 'ready';
}

const CATEGORY_GROUPS: { title: string; icon: React.ComponentType<{ className?: string }>; match: (p: JsonRecord) => boolean }[] = [
  {
    title: 'LOCAL AI (OFFLINE)',
    icon: Cpu,
    match: (p) => p.mode === 'local',
  },
  {
    title: 'GOOGLE GEMINI (3 LOGICAL MODELS)',
    icon: Sparkles,
    match: (p) => String(p.family) === 'google-gemini',
  },
  {
    title: 'FAST INFERENCE & LPU TIERS',
    icon: Zap,
    match: (p) => ['groq', 'cerebras', 'sambanova'].includes(String(p.id)),
  },
  {
    title: 'MULTI-MODEL AGGREGATORS & HUBS',
    icon: Layers,
    match: (p) => ['openrouter', 'llm7', 'siliconflow', 'kilo', 'cline', 'huggingface', 'chutes', 'glhf'].includes(String(p.id)),
  },
  {
    title: 'FRONTIER & SPECIALIZED CLOUD PROVIDERS',
    icon: Flame,
    match: (p) => ['nvidia-nim', 'deepseek', 'xai', 'mistral', 'cohere', 'ai21', 'zai'].includes(String(p.id)),
  },
  {
    title: 'GLOBAL CLOUD & COMMUNITY PLATFORMS',
    icon: Globe,
    match: (p) => ['modelscope', 'cloudflare', 'pollinations', 'ovhcloud', 'aion', 'agnes', 'alibaba', 'nscale', 'nebius', 'scaleway', 'tencent', 'arli', 'ollama-cloud'].includes(String(p.id)),
  },
];

const ProviderRow: React.FC<{
  provider: JsonRecord;
  active: boolean;
  busy: string;
  onAction: (label: string, fn: () => Promise<unknown>) => void;
}> = ({ provider, active, busy, onAction }) => {
  const id = String(provider.id);
  const models = asList(provider.models);
  const freeModels = models.filter((m) => m.free === true && m.available !== false);
  const billing = billingBadge(provider);
  const stats = asRecord(provider.stats);
  const health = asRecord(provider.health);
  const gemini = asRecord(provider.gemini);
  const sourceUrl = String(provider.source_url || '');
  const [model, setModel] = useState(String(gemini.model || provider.default_model || ''));

  useEffect(() => {
    setModel(String(asRecord(provider.gemini).model || provider.default_model || ''));
  }, [provider]);

  return (
    <div className={`p-2.5 rounded border space-y-2 transition-all ${
      active
        ? 'border-[var(--theme-primary)] bg-black/70 shadow-sm shadow-[var(--theme-primary)]/10'
        : 'border-[var(--theme-border)] bg-black/40 hover:border-stone-600'
    }`}>
      {/* Header row */}
      <div className="flex items-center gap-2 flex-wrap">
        {provider.mode === 'local'
          ? <Cpu className="w-4 h-4 text-[var(--theme-primary)] shrink-0" />
          : <Cloud className="w-4 h-4 text-sky-400 shrink-0" />}
        <span className="font-bold text-[13px] text-stone-100">{String(provider.name)}</span>
        <span
          title={billing.desc}
          className={`text-[9px] font-bold px-1.5 py-0.5 rounded border ${billing.cls}`}
        >
          {billing.label}
        </span>
        <StateBadge state={healthLabel(provider)} />
        {active ? (
          <span className="text-[9px] font-bold px-1.5 py-0.5 rounded border text-sky-300 border-sky-800 bg-sky-950/40">
            ACTIVE FOR CHAT
          </span>
        ) : null}
        <span className="ml-auto text-[10px] text-stone-400 font-mono">
          {stats.latency_ms_ewma ? `${(Number(stats.latency_ms_ewma) / 1000).toFixed(2)}s avg` : ''}
        </span>
      </div>

      {/* Details row */}
      <div className="text-[11px] text-stone-400 leading-relaxed">
        {String(provider.free_detail || '')}
      </div>

      {/* Metadata tags */}
      <div className="flex items-center gap-2 text-[10px] text-stone-400 flex-wrap">
        <span className="px-1.5 py-0.5 rounded bg-stone-900 border border-stone-800">
          {provider.mode === 'local' ? 'LOCAL ENDPOINT' : 'CLOUD API'}
        </span>
        {provider.rate_limits ? (
          <span className="px-1.5 py-0.5 rounded bg-stone-900 border border-stone-800 text-stone-400">
            Limits: {String(provider.rate_limits)}
          </span>
        ) : null}
        {provider.requires_api_key ? (
          <span className={`px-1.5 py-0.5 rounded border ${
            provider.key_configured
              ? 'bg-emerald-950/30 border-emerald-900 text-emerald-400'
              : 'bg-rose-950/30 border-rose-900 text-rose-300'
          }`}>
            <Key className="w-2.5 h-2.5 inline mr-1" />
            {provider.key_configured ? 'Key Configured' : `Missing Key (${String(provider.key_slot)})`}
          </span>
        ) : (
          <span className="px-1.5 py-0.5 rounded bg-stone-900 border border-stone-800 text-stone-400">
            No API Key Required
          </span>
        )}
        {provider.requires_phone ? (
          <span className="px-1.5 py-0.5 rounded bg-amber-950/30 border border-amber-900 text-amber-300">
            Requires SMS/Phone
          </span>
        ) : null}
        {provider.models_refreshed_at ? (
          <span className="text-stone-400">
            · Models checked {String(provider.models_refreshed_at).slice(0, 19).replace('T', ' ')}
          </span>
        ) : null}
        {Number(stats.cooldown_seconds) > 0 ? (
          <span className="text-amber-400 font-mono">
            · Cooling down ({String(stats.cooldown_seconds)}s)
          </span>
        ) : null}
      </div>

      {/* Warning/Error banners */}
      {health.detail ? <div className="text-[10px] text-stone-400 bg-stone-900/50 p-1.5 rounded">{String(health.detail)}</div> : null}
      {stats.last_error ? (
        <div className="text-[10px] text-rose-300/90 bg-rose-950/20 border border-rose-900/40 p-1.5 rounded">
          Last Error ({String(stats.last_error_kind)}): {String(stats.last_error)}
        </div>
      ) : null}
      {provider.cloud_blocked ? (
        <div className="text-[10px] text-amber-300 bg-amber-950/20 border border-amber-900/40 p-1.5 rounded">
          {String(provider.cloud_blocked)}
        </div>
      ) : null}
      {!provider.policy_allowed ? (
        <div className="text-[10px] text-amber-300 bg-amber-950/20 border border-amber-900/40 p-1.5 rounded flex items-center gap-1">
          <ShieldAlert className="w-3 h-3 text-amber-400 shrink-0" />
          <span>{String(provider.policy_reason)}</span>
        </div>
      ) : null}

      {/* Gemini Entry Configuration */}
      {gemini.key_slot ? (
        <div className="flex items-center gap-2 text-[10px] text-stone-300 p-2 rounded bg-black/60 border border-[var(--theme-border)] flex-wrap">
          <span className="font-semibold text-stone-200">Model ID:</span>
          <input
            className={`${inputCls} max-w-[200px] text-[11px]`}
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="e.g. gemini-2.5-flash"
          />
          <span className="font-semibold text-stone-200">Key Slot:</span>
          <select
            className={`${inputCls} max-w-[170px] text-[11px]`}
            value={String(gemini.key_slot)}
            onChange={(e) => onAction(`gemini-${id}`, () => configureGemini(id, undefined, e.target.value))}
          >
            <option value="GEMINI_API_KEY_1">GEMINI_API_KEY_1</option>
            <option value="GEMINI_API_KEY_2">GEMINI_API_KEY_2</option>
            <option value="GEMINI_API_KEY_3">GEMINI_API_KEY_3</option>
          </select>
          <GhostButton disabled={!!busy} onClick={() => onAction(`gemini-${id}`, () => configureGemini(id, model))}>
            Save configuration
          </GhostButton>
        </div>
      ) : null}

      {/* Discovered models snippet */}
      {models.length > 0 && !gemini.key_slot ? (
        <div className="text-[10px] text-stone-400 flex items-center gap-1.5 flex-wrap">
          <span className="text-stone-300 font-semibold">{freeModels.length} verified $0 models</span> of {models.length} discovered:
          {freeModels.slice(0, 4).map((m) => (
            <span key={String(m.id)} className="px-1 py-0.5 rounded bg-stone-900 border border-stone-800 text-stone-300 font-mono text-[9px]">
              {String(m.id)}
            </span>
          ))}
          {freeModels.length > 4 ? <span className="text-stone-400">+{freeModels.length - 4} more</span> : null}
        </div>
      ) : null}

      {/* Action buttons */}
      <div className="flex items-center gap-2 flex-wrap pt-1">
        <GhostButton disabled={!!busy} onClick={() => onAction(`check-${id}`, () => checkProvider(id))}>
          {busy === `check-${id}` ? <Loader2 className="w-3 h-3 animate-spin inline" /> : null} Test Connection
        </GhostButton>
        <GhostButton
          disabled={!!busy}
          onClick={() => onAction(`toggle-${id}`, () => setProviderEnabled(id, !(provider.enabled === true)))}
        >
          {provider.enabled ? 'Disable' : 'Enable'}
        </GhostButton>
        {String(provider.free_status) === 'UNKNOWN' && provider.enabled ? (
          <GhostButton
            disabled={!!busy}
            title="Only after you verified the provider's free terms yourself"
            onClick={() => onAction(`free-${id}`, () => setProviderEnabled(id, true, !(provider.allow_in_free_mode === true)))}
          >
            {provider.allow_in_free_mode ? 'Revoke free override' : 'I verified it is free'}
          </GhostButton>
        ) : null}
        {!active && provider.enabled ? (
          <PrimaryButton disabled={!!busy} onClick={() => onAction(`select-${id}`, () => selectProviderModel(id))}>
            Set as Primary Chat
          </PrimaryButton>
        ) : null}
        {id === 'ollama-local' ? (
          <GhostButton disabled={!!busy} onClick={() => onAction('warmup', () => warmupLocalModel())}>
            {busy === 'warmup' ? <Loader2 className="w-3 h-3 animate-spin inline" /> : null} Warm Up Qwen
          </GhostButton>
        ) : null}
        {sourceUrl ? (
          <a
            href={sourceUrl}
            target="_blank"
            rel="noreferrer"
            className="text-[10px] text-sky-400 hover:text-sky-300 flex items-center gap-1 ml-auto"
          >
            Get API Key / Docs <ExternalLink className="w-2.5 h-2.5 inline" />
          </a>
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

  const grouped = useMemo(() => {
    const list = [...providers];
    const result: { group: typeof CATEGORY_GROUPS[0]; items: JsonRecord[] }[] = [];
    const used = new Set<string>();

    for (const group of CATEGORY_GROUPS) {
      const matching = list.filter((p) => !used.has(String(p.id)) && group.match(p));
      for (const m of matching) used.add(String(m.id));
      if (matching.length > 0) {
        result.push({ group, items: matching });
      }
    }

    const remaining = list.filter((p) => !used.has(String(p.id)));
    if (remaining.length > 0) {
      result.push({
        group: { title: 'OTHER PROVIDERS', icon: Cloud, match: () => true },
        items: remaining,
      });
    }
    return result;
  }, [providers]);

  return (
    <div className="p-3 space-y-4 text-stone-300 overflow-y-auto h-full">
      {/* Top Banner & Mode Indicators */}
      <div className="flex items-center gap-2 flex-wrap pb-2 border-b border-[var(--theme-border)]">
        {freeOnly ? (
          <span className="flex items-center gap-1.5 text-[11px] font-bold px-2.5 py-1 rounded border text-emerald-300 border-emerald-700 bg-emerald-950/60 shadow-sm shadow-emerald-900/30">
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" /> FREE ONLY — $0 COST GUARANTEE
          </span>
        ) : (
          <span className="flex items-center gap-1.5 text-[11px] font-bold px-2.5 py-1 rounded border text-amber-300 border-amber-800 bg-amber-950/40">
            <ShieldAlert className="w-3.5 h-3.5 text-amber-400" /> PAID PROVIDERS PERMITTED
          </span>
        )}
        <span className="text-[11px] text-stone-400">
          Chat Router: <span className="text-stone-200 font-mono font-bold">{activeProvider === 'auto' ? 'AUTO FALLBACK CHAIN' : activeProvider}</span>
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
            {busy === 'refresh' ? <Loader2 className="w-3 h-3 animate-spin inline" /> : <RefreshCw className="w-3 h-3 inline" />} Refresh Free Models
          </GhostButton>
          {activeProvider !== 'auto' ? (
            <GhostButton disabled={!!busy} onClick={() => onAction('auto', () => selectProviderModel('auto'))}>
              Back to Auto
            </GhostButton>
          ) : null}
        </span>
      </div>

      <ErrorLine message={error} />

      {/* Cloud Privacy Guard Banner */}
      {cloudGate ? (
        <div className="text-[11px] text-amber-300 p-2.5 rounded bg-amber-950/30 border border-amber-800/50 flex items-center gap-2 flex-wrap">
          <Lock className="w-4 h-4 text-amber-400 shrink-0" />
          <span>{cloudGate}</span>
          <GhostButton disabled={!!busy} onClick={() => onAction('privacy', async () => {
            await saveSettings({ privacy_mode: 'hybrid' });
          })}>
            Enable Cloud Fallback (privacy: hybrid)
          </GhostButton>
        </div>
      ) : null}

      {/* Local Qwen Status Callout */}
      <div className="text-[11px] text-stone-300 p-3 rounded bg-black/60 border border-[var(--theme-border)] space-y-1">
        <div className="flex items-center gap-2">
          <Cpu className="w-4 h-4 text-[var(--theme-primary)]" />
          <span className="font-bold text-stone-100">Primary Local AI:</span>
          <span className="text-emerald-400 font-mono">qwen2.5:3b (Ollama)</span>
          <span className="text-stone-400">· State: <span className="text-stone-200 font-semibold">{String(local.message || local.state || 'unknown')}</span></span>
          {local.latency_ms ? <span className="text-stone-400">({(Number(local.latency_ms) / 1000).toFixed(2)}s probe)</span> : null}
        </div>
        <div className="text-[10px] text-stone-400">
          Vortex utilizes <span className="text-stone-300">open-free-llm-api/awesome-freellm-apis</span> as its free model discovery catalogue.
          Cloud providers are connected via API keys; they are <span className="text-stone-300 font-semibold">never downloaded</span>.
          All credentials remain local and secrets are automatically redacted before sending cloud prompts.
        </div>
      </div>

      {loading ? <EmptyLine message="Reading live provider status and discovery catalogue…" /> : null}

      {/* Diagnostics Modal / Pre */}
      {showDiagnostics && diagnostics ? (
        <Section title="Provider Diagnostics (Masked Credentials)">
          <pre className="text-[10px] text-stone-300 font-mono whitespace-pre-wrap bg-black/70 border border-[var(--theme-border)] rounded p-2.5 max-h-72 overflow-y-auto">
            {diagnostics}
          </pre>
          <div className="mt-2">
            <GhostButton onClick={() => setShowDiagnostics(false)}>Close Diagnostics</GhostButton>
          </div>
        </Section>
      ) : null}

      {/* Provider Category Sections */}
      {grouped.map(({ group, items }) => {
        const Icon = group.icon;
        return (
          <Section
            key={group.title}
            title={
              <span className="flex items-center gap-2">
                <Icon className="w-3.5 h-3.5 text-[var(--theme-primary)]" />
                {group.title} ({items.length})
              </span>
            }
          >
            <div className="space-y-2 mt-1">
              {items.map((provider) => (
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
        );
      })}

      {providers.length === 0 && !loading ? (
        <EmptyLine message="No provider inventory returned from the sidecar." />
      ) : null}
    </div>
  );
};
