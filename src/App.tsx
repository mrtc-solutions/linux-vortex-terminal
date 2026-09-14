import { useState, useEffect, useCallback } from 'react';
import {
  ShieldCheck, TerminalSquare, ListChecks, Crosshair, Wrench, BrainCircuit,
  Activity, History as HistoryIcon, Database, Settings as SettingsIcon, LayoutGrid,
  Bot, CircleHelp, Info as InfoIcon,
} from 'lucide-react';
import { ThemeMode, FuzzyConsensusResult } from './types/terminal';
import { sound } from './services/soundEffects';
import { JsonRecord, OperationDocument, PlanDocument, listArtifacts } from './services/vortexApi';

import { MatrixRainCanvas } from './components/MatrixRainCanvas';
import { HeaderBar } from './components/HeaderBar';
import { QuickPromptBar } from './components/QuickPromptBar';
import { TerminalView } from './components/TerminalView';
import { TacticalMap } from './components/TacticalMap';
import { OutDirectoryExplorer } from './components/OutDirectoryExplorer';
import { ReportGeneratorModal } from './components/ReportGeneratorModal';
import { FuzzyTab } from './components/FuzzyTab';
import { AgentReachInspector } from './components/AgentReachInspector';
import { FuzzyOrchestrationModal } from './components/FuzzyOrchestrationModal';
import { WindowManager, PopupSpec } from './components/WindowManager';
import { Approvals } from './components/popups/Approvals';
import { Shell } from './components/popups/Shell';
import { Tasks } from './components/popups/Tasks';
import { Scope } from './components/popups/Scope';
import { Tools } from './components/popups/Tools';
import { Models } from './components/popups/Models';
import { SystemPanel } from './components/popups/SystemPanel';
import { History } from './components/popups/History';
import { Memory } from './components/popups/Memory';
import { SettingsPanel } from './components/popups/SettingsPanel';
import { Launcher } from './components/popups/Launcher';
import { AiOps } from './components/popups/AiOps';
import { Help } from './components/popups/Help';
import { About } from './components/popups/About';

export function App() {
  const [activeTab, setActiveTab] = useState<'terminal' | 'map' | 'out' | 'report' | 'fuzzy' | 'agent-reach'>('terminal');
  const [theme, setTheme] = useState<ThemeMode>('matrix');
  const [crtEnabled, setCrtEnabled] = useState<boolean>(true);
  const [matrixRainEnabled, setMatrixRainEnabled] = useState<boolean>(true);
  const [soundMuted, setSoundMuted] = useState<boolean>(sound.getMuted());
  const [artifactCount, setArtifactCount] = useState<number>(0);
  const [inspectingFuzzy, setInspectingFuzzy] = useState<FuzzyConsensusResult | null>(null);
  const [externalCommand, setExternalCommand] = useState<string | null>(null);
  const [popups, setPopups] = useState<PopupSpec[]>([]);

  // Sync /out artifact count from the REAL sidecar store.
  const updateArtifactCount = useCallback(() => {
    listArtifacts()
      .then((payload) => {
        const list = Array.isArray(payload.artifacts) ? payload.artifacts : [];
        setArtifactCount(list.length);
      })
      .catch(() => {
        /* sidecar unreachable — badge keeps its last honest value */
      });
  }, []);

  useEffect(() => {
    updateArtifactCount();
  }, [updateArtifactCount]);

  const closePopup = useCallback((id: string) => {
    setPopups((prev) => prev.filter((popup) => popup.id !== id));
  }, []);

  const openPopup = useCallback((kind: string, props: JsonRecord = {}) => {
    const id = `${kind}-${Date.now()}-${Math.floor(Math.random() * 100000)}`;
    const close = () => closePopup(id);
    let spec: PopupSpec | null = null;
    switch (kind) {
      case 'approvals': {
        const plan = (props.plan || {}) as PlanDocument;
        const guardian = (props.guardian || {}) as JsonRecord;
        const onApproved = (props.onApproved as ((op: OperationDocument) => void) | undefined) || (() => undefined);
        const onRejected = (props.onRejected as (() => void) | undefined) || (() => undefined);
        const mutation = (props.mutation && typeof props.mutation === 'object'
          ? props.mutation as { operation: OperationDocument; approvalToken: string }
          : undefined);
        spec = {
          id, title: mutation ? 'MUTATION PREFLIGHT REVIEW' : 'GUARDIAN PLAN REVIEW',
          icon: <ShieldCheck className="w-3.5 h-3.5 text-[var(--theme-primary)]" />,
          width: 680, height: 560,
          content: <Approvals plan={plan} guardian={guardian} onApproved={onApproved} onRejected={onRejected} onClose={close} mutation={mutation} />,
        };
        break;
      }
      case 'shell':
        spec = {
          id, title: 'HOST SHELL (LIVE PTY)',
          icon: <TerminalSquare className="w-3.5 h-3.5 text-[var(--theme-primary)]" />,
          width: 720, height: 500,
          content: <Shell />,
        };
        break;
      case 'tasks':
        spec = { id, title: 'TASKS', icon: <ListChecks className="w-3.5 h-3.5 text-[var(--theme-primary)]" />, width: 660, height: 560, content: <Tasks /> };
        break;
      case 'scope':
        spec = { id, title: 'ENGAGEMENT SCOPE', icon: <Crosshair className="w-3.5 h-3.5 text-[var(--theme-primary)]" />, width: 620, height: 560, content: <Scope /> };
        break;
      case 'tools':
        spec = { id, title: 'TOOLS', icon: <Wrench className="w-3.5 h-3.5 text-[var(--theme-primary)]" />, width: 640, height: 560, content: <Tools /> };
        break;
      case 'models':
        spec = { id, title: 'LOCAL AI / MODELS', icon: <BrainCircuit className="w-3.5 h-3.5 text-[var(--theme-primary)]" />, width: 660, height: 580, content: <Models /> };
        break;
      case 'system':
        spec = { id, title: 'SYSTEM HEALTH', icon: <Activity className="w-3.5 h-3.5 text-[var(--theme-primary)]" />, width: 600, height: 540, content: <SystemPanel /> };
        break;
      case 'history':
        spec = { id, title: 'CONVERSATIONS', icon: <HistoryIcon className="w-3.5 h-3.5 text-[var(--theme-primary)]" />, width: 600, height: 520, content: <History onClose={close} /> };
        break;
      case 'memory':
        spec = { id, title: 'MEMORY', icon: <Database className="w-3.5 h-3.5 text-[var(--theme-primary)]" />, width: 600, height: 540, content: <Memory /> };
        break;
      case 'settings':
        spec = { id, title: 'SETTINGS', icon: <SettingsIcon className="w-3.5 h-3.5 text-[var(--theme-primary)]" />, width: 580, height: 540, content: <SettingsPanel /> };
        break;
      case 'launcher':
        spec = {
          id, title: 'VORTEX TERMINAL START MENU',
          icon: <LayoutGrid className="w-3.5 h-3.5 text-[var(--theme-primary)]" />,
          width: 600, height: 480,
          content: <Launcher onGoTab={(tab) => setActiveTab(tab)} onOpenPopup={(kind) => openPopup(kind)} onClose={close} />,
        };
        break;
      case 'aiops':
        spec = { id, title: 'AI OPERATIONS', icon: <Bot className="w-3.5 h-3.5 text-[var(--theme-primary)]" />, width: 640, height: 560, content: <AiOps /> };
        break;
      case 'helpwin':
        spec = { id, title: 'VORTEX TERMINAL HELP', icon: <CircleHelp className="w-3.5 h-3.5 text-[var(--theme-primary)]" />, width: 600, height: 540, content: <Help onOpenPopup={(kind) => openPopup(kind)} /> };
        break;
      case 'about':
        spec = { id, title: 'ABOUT · DOWNLOADS · LICENSE', icon: <InfoIcon className="w-3.5 h-3.5 text-[var(--theme-primary)]" />, width: 620, height: 600, content: <About /> };
        break;
      default:
        return;
    }
    setPopups((prev) => [...prev.slice(-7), spec as PopupSpec]);
    sound.playKeypress();
  }, [closePopup]);

  // Update CSS variables on theme switch
  useEffect(() => {
    const root = document.documentElement;
    switch (theme) {
      case 'amber':
        root.style.setProperty('--theme-primary', '#ffb000');
        root.style.setProperty('--theme-primary-rgb', '255, 176, 0');
        root.style.setProperty('--theme-bg', '#090805');
        root.style.setProperty('--theme-surface', '#13100a');
        root.style.setProperty('--theme-border', 'rgba(255, 176, 0, 0.25)');
        root.style.setProperty('--theme-dim', '#b37b00');
        break;
      case 'cyan':
        root.style.setProperty('--theme-primary', '#00f0ff');
        root.style.setProperty('--theme-primary-rgb', '0, 240, 255');
        root.style.setProperty('--theme-bg', '#050a0d');
        root.style.setProperty('--theme-surface', '#09131a');
        root.style.setProperty('--theme-border', 'rgba(0, 240, 255, 0.25)');
        root.style.setProperty('--theme-dim', '#0099a8');
        break;
      case 'crimson':
        root.style.setProperty('--theme-primary', '#ff3366');
        root.style.setProperty('--theme-primary-rgb', '255, 51, 102');
        root.style.setProperty('--theme-bg', '#0d0507');
        root.style.setProperty('--theme-surface', '#1a0a0f');
        root.style.setProperty('--theme-border', 'rgba(255, 51, 102, 0.25)');
        root.style.setProperty('--theme-dim', '#aa1e40');
        break;
      case 'violet':
        root.style.setProperty('--theme-primary', '#c084fc');
        root.style.setProperty('--theme-primary-rgb', '192, 132, 252');
        root.style.setProperty('--theme-bg', '#0b050f');
        root.style.setProperty('--theme-surface', '#160a1e');
        root.style.setProperty('--theme-border', 'rgba(192, 132, 252, 0.25)');
        root.style.setProperty('--theme-dim', '#8b3fd0');
        break;
      case 'matrix':
      default:
        root.style.setProperty('--theme-primary', '#00ff66');
        root.style.setProperty('--theme-primary-rgb', '0, 255, 102');
        root.style.setProperty('--theme-bg', '#050b07');
        root.style.setProperty('--theme-surface', '#0a140d');
        root.style.setProperty('--theme-border', 'rgba(0, 255, 102, 0.25)');
        root.style.setProperty('--theme-dim', '#00993d');
        break;
    }
  }, [theme]);

  const handleExecuteExternal = (cmd: string) => {
    setExternalCommand(cmd);
    setActiveTab('terminal');
  };

  return (
    <div className="relative w-screen h-screen flex flex-col overflow-hidden bg-[var(--theme-bg)] text-[var(--theme-primary)] font-mono select-none">
      {/* 1. Digital Matrix Rain Animation */}
      <MatrixRainCanvas theme={theme} enabled={matrixRainEnabled} opacity={0.16} />

      {/* 2. Top Header Bar & Cluster Telemetry */}
      <HeaderBar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        theme={theme}
        setTheme={setTheme}
        crtEnabled={crtEnabled}
        setCrtEnabled={setCrtEnabled}
        matrixRainEnabled={matrixRainEnabled}
        setMatrixRainEnabled={setMatrixRainEnabled}
        soundMuted={soundMuted}
        setSoundMuted={setSoundMuted}
        artifactCount={artifactCount}
        onOpenLauncher={() => openPopup('launcher')}
      />

      {/* 3. Quick AI Prompt Suggestion Chips */}
      <QuickPromptBar onSelectPrompt={handleExecuteExternal} />

      {/* 4. Active Main View Container — all tabs stay mounted so terminal
          scrollback, selections, and in-flight turns survive tab switches. */}
      <main className="flex-1 flex flex-col overflow-hidden relative z-10">
        <div className={activeTab === 'terminal' ? 'flex-1 flex flex-col overflow-hidden min-h-0' : 'hidden'}>
          <TerminalView
            onInspectFuzzy={(res) => setInspectingFuzzy(res)}
            onNavigateToOut={() => setActiveTab('out')}
            onNavigateToMap={() => setActiveTab('map')}
            onNavigateToReport={() => setActiveTab('report')}
            onOpenPopup={openPopup}
            externalCommand={externalCommand}
            onClearExternalCommand={() => setExternalCommand(null)}
            onArtifactCountChange={updateArtifactCount}
          />
        </div>

        <div className={activeTab === 'map' ? 'flex-1 flex flex-col overflow-hidden min-h-0' : 'hidden'}>
          <TacticalMap
            onExecuteCommand={handleExecuteExternal}
            onNavigateToOut={() => setActiveTab('out')}
          />
        </div>

        <div className={activeTab === 'out' ? 'flex-1 flex flex-col overflow-hidden min-h-0' : 'hidden'}>
          <OutDirectoryExplorer
            onArtifactChange={updateArtifactCount}
            onRunTerminalCommand={handleExecuteExternal}
          />
        </div>

        <div className={activeTab === 'report' ? 'flex-1 flex flex-col overflow-hidden min-h-0' : 'hidden'}>
          <ReportGeneratorModal
            onReportSaved={updateArtifactCount}
            onNavigateToOut={() => setActiveTab('out')}
          />
        </div>

        <div className={activeTab === 'fuzzy' ? 'flex-1 flex flex-col overflow-hidden min-h-0' : 'hidden'}>
          <FuzzyTab onExecuteCommand={handleExecuteExternal} />
        </div>

        <div className={activeTab === 'agent-reach' ? 'flex-1 flex flex-col overflow-hidden min-h-0' : 'hidden'}>
          <AgentReachInspector onExecuteCommand={handleExecuteExternal} />
        </div>
      </main>

      {/* 5. CRT Scanline Overlay & Curved Vignette (Toggleable) */}
      {crtEnabled && (
        <div className="crt-overlay crt-vignette pointer-events-none fixed inset-0 z-40" />
      )}

      {/* 6. Fuzzy Consensus Inspection Modal (When clicked inside Terminal or Elsewhere) */}
      {inspectingFuzzy && (
        <FuzzyOrchestrationModal
          consensus={inspectingFuzzy}
          onClose={() => setInspectingFuzzy(null)}
        />
      )}

      {/* 7. Popup windows (secondary surfaces) */}
      <WindowManager popups={popups} onClose={closePopup} />
    </div>
  );
}

export default App;
