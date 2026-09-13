import React, { useEffect, useState } from 'react';
import { ThemeMode } from '../types/terminal';
import { JsonRecord, getCapabilities, getModels, getSystemHealth } from '../services/vortexApi';
import { 
  Terminal, 
  MapPin, 
  FolderDown, 
  FileText, 
  Scale, 
  ShieldCheck, 
  Volume2, 
  VolumeX, 
  Monitor, 
  Binary, 
  Palette,
  Activity,
  LayoutGrid
} from 'lucide-react';
import { sound } from '../services/soundEffects';

interface HeaderBarProps {
  activeTab: 'terminal' | 'map' | 'out' | 'report' | 'fuzzy' | 'agent-reach';
  setActiveTab: (tab: 'terminal' | 'map' | 'out' | 'report' | 'fuzzy' | 'agent-reach') => void;
  theme: ThemeMode;
  setTheme: (theme: ThemeMode) => void;
  crtEnabled: boolean;
  setCrtEnabled: (val: boolean | ((prev: boolean) => boolean)) => void;
  matrixRainEnabled: boolean;
  setMatrixRainEnabled: (val: boolean | ((prev: boolean) => boolean)) => void;
  soundMuted: boolean;
  setSoundMuted: (val: boolean) => void;
  artifactCount: number;
  onOpenLauncher: () => void;
}

export const HeaderBar: React.FC<HeaderBarProps> = ({
  activeTab,
  setActiveTab,
  theme,
  setTheme,
  crtEnabled,
  setCrtEnabled,
  matrixRainEnabled,
  setMatrixRainEnabled,
  soundMuted,
  setSoundMuted,
  artifactCount,
  onOpenLauncher,
}) => {
  const [hostLabel, setHostLabel] = useState('connecting…');
  const [providerBadges, setProviderBadges] = useState<{ name: string; state: string; reason: string }[]>([]);
  const [advisorLabel, setAdvisorLabel] = useState('Advisors: …');

  // One honest telemetry pass from the live sidecar (no staged cluster stats).
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [healthPayload, modelsPayload, capsPayload] = await Promise.all([
          getSystemHealth(), getModels(), getCapabilities(),
        ]);
        if (cancelled) return;
        const host = ((healthPayload.health || {}) as JsonRecord).host as JsonRecord | undefined;
        const distro = ((host || {}).distribution || {}) as JsonRecord;
        const id = String(distro.id || (host || {}).kernel || 'host');
        const arch = String((host || {}).architecture || '');
        setHostLabel(`${id}${arch ? ` ${arch}` : ''}`);
        const providers = (((modelsPayload.model || {}) as JsonRecord).providers || {}) as JsonRecord;
        setProviderBadges(['llamafile', 'gguf', 'ollama'].map((name) => {
          const detail = (providers[name] || {}) as JsonRecord;
          return { name, state: String(detail.state || 'unknown'), reason: String(detail.reason || '') };
        }));
        const probes = (capsPayload.host_probes || {}) as JsonRecord;
        const installed = Array.isArray(probes.agents_installed) ? probes.agents_installed.length : 0;
        setAdvisorLabel(installed > 0 ? `Advisors: ${installed} READY` : 'Advisors: NONE');
      } catch {
        if (!cancelled) {
          setHostLabel('sidecar offline');
          setProviderBadges([]);
          setAdvisorLabel('Advisors: ?');
        }
      }
    };
    void load();
    return () => { cancelled = true; };
  }, []);

  const toggleSound = () => {
    const isMuted = sound.toggleMute();
    setSoundMuted(isMuted);
    if (!isMuted) sound.playSuccess();
  };

  const themes: { id: ThemeMode; label: string; colorHex: string }[] = [
    { id: 'matrix', label: 'Matrix Phosphor', colorHex: '#00ff66' },
    { id: 'amber', label: 'Cyber Amber', colorHex: '#ffb000' },
    { id: 'cyan', label: 'Ice Cyan SOC', colorHex: '#00f0ff' },
    { id: 'crimson', label: 'Blood Strike', colorHex: '#ff3366' },
    { id: 'violet', label: 'Synthetic Violet', colorHex: '#a855f7' },
  ];

  return (
    <header className="border-b border-[var(--theme-border)] bg-[var(--theme-surface)]/90 backdrop-blur-md px-3 py-2 select-none relative z-30 transition-colors">
      <div className="flex flex-wrap items-center justify-between gap-2">
        {/* Left: Start Menu, Branding & Host Status */}
        <div className="flex items-center space-x-3">
          <button
            onClick={() => {
              onOpenLauncher();
              sound.playKeypress();
            }}
            title="VORTEX start menu"
            className="p-1.5 rounded bg-[var(--theme-primary)] text-black hover:opacity-90 transition-opacity cursor-pointer"
          >
            <LayoutGrid className="w-4 h-4" />
          </button>
          <div className="flex items-center space-x-2">
            <div className="relative">
              <div className="w-3 h-3 rounded-full bg-[var(--theme-primary)] animate-ping absolute opacity-75" />
              <div className="w-3 h-3 rounded-full bg-[var(--theme-primary)]" />
            </div>
            <div className="font-bold tracking-widest text-sm flex items-center gap-1.5 glow-primary">
              <ShieldCheck className="w-4 h-4 text-[var(--theme-primary)] inline" />
              <span>VORTEX</span>
              <span className="text-xs px-1.5 py-0.5 rounded bg-[var(--theme-border)] text-xs font-mono opacity-80">
                v0.3.0
              </span>
            </div>
          </div>

          <div className="hidden lg:flex items-center text-xs text-stone-400 font-mono border-l border-[var(--theme-border)] pl-3 space-x-2">
            <span className="text-[var(--theme-dim)]">operator@vortex:</span>
            <span className="text-xs text-[var(--theme-primary)]">{hostLabel}</span>
            <span className="text-xs bg-emerald-950/80 text-emerald-400 px-1 rounded border border-emerald-800/50">
              {advisorLabel}
            </span>
          </div>

          {/* Live Local-AI Provider States */}
          <div className="hidden xl:flex items-center space-x-1.5 text-[11px] font-mono border-l border-[var(--theme-border)] pl-3">
            {providerBadges.map((provider) => (
              <div
                key={provider.name}
                className="flex items-center space-x-1 px-1.5 py-0.5 rounded bg-black/40 border border-[var(--theme-border)] text-stone-300"
                title={provider.reason || provider.state}
              >
                <span
                  className="w-1.5 h-1.5 rounded-full"
                  style={{ backgroundColor: provider.state === 'available' ? 'var(--theme-primary)' : '#525252' }}
                />
                <span className="font-medium">{provider.name}</span>
                <span className="text-stone-500 text-[10px]">({provider.state})</span>
              </div>
            ))}
          </div>
        </div>

        {/* Center / Navigation Tabs */}
        <nav className="flex items-center space-x-1 font-mono text-xs">
          <button
            onClick={() => {
              setActiveTab('terminal');
              sound.playKeypress();
            }}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded transition-all cursor-pointer ${
              activeTab === 'terminal'
                ? 'bg-[var(--theme-primary)] text-black font-semibold shadow-sm'
                : 'text-stone-300 hover:text-[var(--theme-primary)] hover:bg-[var(--theme-border)]'
            }`}
          >
            <Terminal className="w-3.5 h-3.5" />
            <span>Terminal</span>
          </button>

          <button
            onClick={() => {
              setActiveTab('map');
              sound.playRadarBlip();
            }}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded transition-all cursor-pointer ${
              activeTab === 'map'
                ? 'bg-[var(--theme-primary)] text-black font-semibold shadow-sm'
                : 'text-stone-300 hover:text-[var(--theme-primary)] hover:bg-[var(--theme-border)]'
            }`}
          >
            <MapPin className="w-3.5 h-3.5" />
            <span>Tactical Map</span>
          </button>

          <button
            onClick={() => {
              setActiveTab('out');
              sound.playKeypress();
            }}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded transition-all cursor-pointer relative ${
              activeTab === 'out'
                ? 'bg-[var(--theme-primary)] text-black font-semibold shadow-sm'
                : 'text-stone-300 hover:text-[var(--theme-primary)] hover:bg-[var(--theme-border)]'
            }`}
          >
            <FolderDown className="w-3.5 h-3.5" />
            <span>/out Directory</span>
            {artifactCount > 0 && (
              <span className={`text-[10px] px-1 rounded-full font-bold ${activeTab === 'out' ? 'bg-black text-[var(--theme-primary)]' : 'bg-[var(--theme-primary)] text-black'}`}>
                {artifactCount}
              </span>
            )}
          </button>

          <button
            onClick={() => {
              setActiveTab('report');
              sound.playKeypress();
            }}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded transition-all cursor-pointer ${
              activeTab === 'report'
                ? 'bg-[var(--theme-primary)] text-black font-semibold shadow-sm'
                : 'text-stone-300 hover:text-[var(--theme-primary)] hover:bg-[var(--theme-border)]'
            }`}
          >
            <FileText className="w-3.5 h-3.5" />
            <span>Report Gen</span>
          </button>

          <button
            onClick={() => {
              setActiveTab('fuzzy');
              sound.playFuzzyArbiter();
            }}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded transition-all cursor-pointer ${
              activeTab === 'fuzzy'
                ? 'bg-[var(--theme-primary)] text-black font-semibold shadow-sm'
                : 'text-stone-300 hover:text-[var(--theme-primary)] hover:bg-[var(--theme-border)]'
            }`}
          >
            <Scale className="w-3.5 h-3.5" />
            <span>Fuzzy Consensus</span>
          </button>

          <button
            onClick={() => {
              setActiveTab('agent-reach');
              sound.playKeypress();
            }}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded transition-all cursor-pointer ${
              activeTab === 'agent-reach'
                ? 'bg-[var(--theme-primary)] text-black font-semibold shadow-sm'
                : 'text-stone-300 hover:text-[var(--theme-primary)] hover:bg-[var(--theme-border)]'
            }`}
          >
            <Activity className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Agent Reach</span>
          </button>
        </nav>

        {/* Right: Controls, Audio, CRT, Rain & Theme Switcher */}
        <div className="flex items-center space-x-1.5">
          {/* Sound Toggle */}
          <button
            onClick={toggleSound}
            title={soundMuted ? 'Unmute Audio Feedback' : 'Mute Audio Feedback'}
            className="p-1.5 rounded hover:bg-[var(--theme-border)] text-stone-300 hover:text-[var(--theme-primary)] transition-colors cursor-pointer"
          >
            {soundMuted ? <VolumeX className="w-4 h-4 text-stone-500" /> : <Volume2 className="w-4 h-4 text-[var(--theme-primary)]" />}
          </button>

          {/* CRT Scanline Toggle */}
          <button
            onClick={() => {
              setCrtEnabled(prev => !prev);
              sound.playKeypress();
            }}
            title={`CRT Scanline Effects: ${crtEnabled ? 'ON' : 'OFF'}`}
            className={`p-1.5 rounded hover:bg-[var(--theme-border)] transition-colors cursor-pointer ${
              crtEnabled ? 'text-[var(--theme-primary)] bg-[var(--theme-border)]/50' : 'text-stone-500'
            }`}
          >
            <Monitor className="w-4 h-4" />
          </button>

          {/* Matrix Rain Toggle */}
          <button
            onClick={() => {
              setMatrixRainEnabled(prev => !prev);
              sound.playKeypress();
            }}
            title={`Digital Matrix Rain: ${matrixRainEnabled ? 'ON' : 'OFF'}`}
            className={`p-1.5 rounded hover:bg-[var(--theme-border)] transition-colors cursor-pointer ${
              matrixRainEnabled ? 'text-[var(--theme-primary)] bg-[var(--theme-border)]/50' : 'text-stone-500'
            }`}
          >
            <Binary className="w-4 h-4" />
          </button>

          {/* Theme Palette Chooser */}
          <div className="flex items-center space-x-1 border-l border-[var(--theme-border)] pl-1.5">
            <Palette className="w-3.5 h-3.5 text-stone-400 mr-0.5" />
            {themes.map((t) => (
              <button
                key={t.id}
                onClick={() => {
                  setTheme(t.id);
                  sound.playKeypress();
                }}
                title={t.label}
                className={`w-3.5 h-3.5 rounded-full transition-transform cursor-pointer ${
                  theme === t.id ? 'scale-125 ring-2 ring-white/70' : 'opacity-60 hover:opacity-100 hover:scale-110'
                }`}
                style={{ backgroundColor: t.colorHex }}
              />
            ))}
          </div>
        </div>
      </div>
    </header>
  );
};
