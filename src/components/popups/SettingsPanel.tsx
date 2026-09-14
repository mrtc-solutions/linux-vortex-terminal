/* Settings popup — real operator policy, saved to the sidecar.
   auto_low_risk is DERIVED from the policy profile, and auto_medium_risk is
   always OFF (a Guardian invariant) — the UI shows that honestly. */
import React, { useCallback, useEffect, useState } from 'react';
import { Loader2, RefreshCw, Settings as SettingsIcon } from 'lucide-react';
import { JsonRecord, getSettings, saveSettings } from '../../services/vortexApi';
import { EmptyLine, ErrorLine, GhostButton, PrimaryButton, Section } from './common';

interface ToggleDef {
  key: string;
  label: string;
  help: string;
}

const TOGGLES: ToggleDef[] = [
  {
    key: 'host_tool_access',
    label: 'Let planner use discovered host tools',
    help: 'The planner may propose typed argv for tools found on a safe PATH. Guardian, scope, and shell=False still apply.',
  },
  {
    key: 'ai_enabled',
    label: 'Local AI assistance',
    help: 'Master switch for local-model advisory. Off = deterministic core only, fully offline-capable.',
  },
  {
    key: 'gguf_enabled',
    label: 'GGUF provider',
    help: 'Allow the fuzzy router to consider GGUF files found in the model directories.',
  },
  {
    key: 'offline',
    label: 'Offline policy',
    help: 'Guardian blocks any command with network effects. Local-only operation.',
  },
  {
    key: 'developer_mode',
    label: 'Developer mode',
    help: 'Extra diagnostics in explanations and reports. No safety gate is bypassed.',
  },
];

const PROFILES: { id: string; label: string; help: string }[] = [
  { id: 'safe', label: 'Safe', help: 'Every plan opens an approval review first. Nothing auto-runs.' },
  { id: 'standard', label: 'Standard', help: 'Low-risk read-only plans auto-run. Everything else asks first.' },
  { id: 'expert', label: 'Expert', help: 'Low-risk read-only plans auto-run with wider planner latitude. Medium-risk plans still always ask.' },
];

function Toggle({ on, label, help, onFlip }: { on: boolean; label: string; help: string; onFlip: () => void }) {
  return (
    <button
      onClick={onFlip}
      className="w-full text-left p-2 rounded bg-black/50 border border-[var(--theme-border)] hover:border-[var(--theme-primary)] transition-colors cursor-pointer"
    >
      <div className="flex items-center gap-2">
        <span className="rounded-full relative shrink-0 transition-colors" style={{ width: 32, height: 18, backgroundColor: on ? 'var(--theme-primary)' : '#292524' }}>
          <span className="absolute top-0.5 w-3.5 h-3.5 rounded-full bg-white transition-all" style={{ left: on ? 18 : 2 }} />
        </span>
        <span className="font-bold text-[12px] text-stone-200">{label}</span>
        <span className="text-[10px] text-stone-500 ml-auto font-mono">{on ? 'ON' : 'OFF'}</span>
      </div>
      <div className="text-[10px] text-stone-500 mt-1 leading-relaxed">{help}</div>
    </button>
  );
}

export const SettingsPanel: React.FC = () => {
  const [settings, setSettings] = useState<JsonRecord | null>(null);
  const [error, setError] = useState('');
  const [saved, setSaved] = useState('');
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setError('');
    setSaved('');
    try {
      const payload = await getSettings();
      setSettings((payload.settings || {}) as JsonRecord);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const flip = (key: string) => {
    setSettings((prev) => (prev ? { ...prev, [key]: !(prev[key] === true) } : prev));
    setSaved('');
  };

  const setProfile = (id: string) => {
    setSettings((prev) => (prev ? { ...prev, profile: id } : prev));
    setSaved('');
  };

  const save = async () => {
    if (busy || !settings) return;
    setBusy(true);
    setError('');
    setSaved('');
    try {
      const payload = await saveSettings(settings);
      setSettings((payload.settings || {}) as JsonRecord);
      setSaved('Policy saved — it applies to the next turn.');
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const profile = String(settings?.profile || 'safe');
  const autoLow = profile === 'standard' || profile === 'expert';

  return (
    <div className="p-4 space-y-4 text-stone-300">
      <div className="flex items-center gap-2">
        <SettingsIcon className="w-4 h-4 text-[var(--theme-primary)]" />
        <span className="text-[12px] font-bold text-stone-200">Settings</span>
        <span className="flex-1" />
        <GhostButton onClick={() => { setLoading(true); void refresh(); }} disabled={loading || busy}>
          <span className="flex items-center gap-1"><RefreshCw className="w-3 h-3" />Reload</span>
        </GhostButton>
      </div>

      <ErrorLine message={error} />
      {loading && !settings && <EmptyLine message="Reading policy…" />}

      {settings && (
        <Section title="Policy profile">
          <div className="space-y-1.5">
            {PROFILES.map((entry) => {
              const active = profile === entry.id;
              return (
                <button
                  key={entry.id}
                  onClick={() => setProfile(entry.id)}
                  className={`w-full text-left p-2 rounded border transition-colors cursor-pointer ${
                    active ? 'bg-black/60 border-[var(--theme-primary)]' : 'bg-black/50 border-[var(--theme-border)] hover:border-[var(--theme-primary)]'
                  }`}
                >
                  <div className="flex items-center gap-2">
                    <span className={`w-2.5 h-2.5 rounded-full ${active ? 'bg-[var(--theme-primary)]' : 'bg-stone-700'}`} />
                    <span className="font-bold text-[12px] text-stone-200">{entry.label}</span>
                  </div>
                  <div className="text-[10px] text-stone-500 mt-0.5 leading-relaxed">{entry.help}</div>
                </button>
              );
            })}
            <div className="text-[10px] text-stone-500 font-mono p-1.5 rounded bg-black/40 border border-[var(--theme-border)]">
              derived: auto_low_risk {autoLow ? 'ON' : 'OFF'} · auto_medium_risk always OFF (Guardian invariant)
            </div>
          </div>
        </Section>
      )}

      {settings && (
        <Section title="Switches">
          <div className="space-y-1.5">
            {TOGGLES.map((toggle) => (
              <Toggle
                key={toggle.key}
                on={settings[toggle.key] === true}
                label={toggle.label}
                help={toggle.help}
                onFlip={() => flip(toggle.key)}
              />
            ))}
          </div>
        </Section>
      )}

      {settings && (
        <div className="flex items-center gap-2">
          <PrimaryButton onClick={() => void save()} disabled={busy}>
            {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : 'Save policy'}
          </PrimaryButton>
          {saved && <span className="text-[11px] text-emerald-300">{saved}</span>}
        </div>
      )}

      <div className="text-[10px] text-stone-600 leading-relaxed">
        Policy is enforced server-side: the Guardian re-checks every plan against these flags at execution time.
        Interface preferences (theme, CRT, matrix rain, sound) live in the header bar.
      </div>
    </div>
  );
};
