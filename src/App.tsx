import { useState, useEffect } from 'react';
import { ThemeMode, FuzzyConsensusResult } from './types/terminal';
import { vfs } from './services/virtualFileSystem';
import { sound } from './services/soundEffects';

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

export function App() {
  const [activeTab, setActiveTab] = useState<'terminal' | 'map' | 'out' | 'report' | 'fuzzy' | 'agent-reach'>('terminal');
  const [theme, setTheme] = useState<ThemeMode>('matrix');
  const [crtEnabled, setCrtEnabled] = useState<boolean>(true);
  const [matrixRainEnabled, setMatrixRainEnabled] = useState<boolean>(true);
  const [soundMuted, setSoundMuted] = useState<boolean>(sound.getMuted());
  const [artifactCount, setArtifactCount] = useState<number>(0);
  const [inspectingFuzzy, setInspectingFuzzy] = useState<FuzzyConsensusResult | null>(null);
  const [externalCommand, setExternalCommand] = useState<string | null>(null);

  // Sync /out artifact count
  const updateArtifactCount = () => {
    const list = vfs.getAllOutArtifacts();
    setArtifactCount(list.length);
  };

  useEffect(() => {
    updateArtifactCount();
  }, []);

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
      />

      {/* 3. Quick AI Prompt Suggestion Chips */}
      <QuickPromptBar onSelectPrompt={handleExecuteExternal} />

      {/* 4. Active Main View Container */}
      <main className="flex-1 flex flex-col overflow-hidden relative z-10">
        {activeTab === 'terminal' && (
          <TerminalView
            onInspectFuzzy={(res) => setInspectingFuzzy(res)}
            onNavigateToOut={() => setActiveTab('out')}
            onNavigateToMap={() => setActiveTab('map')}
            onNavigateToReport={() => setActiveTab('report')}
            externalCommand={externalCommand}
            onClearExternalCommand={() => setExternalCommand(null)}
            onArtifactCountChange={updateArtifactCount}
          />
        )}

        {activeTab === 'map' && (
          <TacticalMap
            onExecuteCommand={handleExecuteExternal}
            onNavigateToOut={() => setActiveTab('out')}
          />
        )}

        {activeTab === 'out' && (
          <OutDirectoryExplorer
            onArtifactChange={updateArtifactCount}
            onRunTerminalCommand={handleExecuteExternal}
          />
        )}

        {activeTab === 'report' && (
          <ReportGeneratorModal
            onReportSaved={updateArtifactCount}
            onNavigateToOut={() => setActiveTab('out')}
          />
        )}

        {activeTab === 'fuzzy' && (
          <FuzzyTab onExecuteCommand={handleExecuteExternal} />
        )}

        {activeTab === 'agent-reach' && (
          <AgentReachInspector onExecuteCommand={handleExecuteExternal} />
        )}
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
    </div>
  );
}

export default App;
