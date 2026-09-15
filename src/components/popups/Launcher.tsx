/* Vortex Terminal start menu — a Linux-like launcher grid. Every tile opens a real
   tab or a live sidecar-backed popup. */
import React from 'react';
import {
  Activity, BrainCircuit, Crosshair, Database, FileText, FolderDown, History,
  ListChecks, MapPin, Scale, Settings as SettingsIcon, Terminal as TerminalIcon,
  TerminalSquare, Wrench, Bot, Cpu, CircleHelp, Info,
} from 'lucide-react';
import { sound } from '../../services/soundEffects';

interface LauncherProps {
  onGoTab: (tab: 'terminal' | 'map' | 'out' | 'report' | 'fuzzy' | 'agent-reach') => void;
  onOpenPopup: (kind: string) => void;
  onClose: () => void;
}

interface Tile {
  label: string;
  hint: string;
  icon: React.ReactNode;
  action: () => void;
}

export const Launcher: React.FC<LauncherProps> = ({ onGoTab, onOpenPopup, onClose }) => {
  const go = (action: () => void) => () => {
    sound.playKeypress();
    onClose();
    action();
  };

  const tiles: Tile[] = [
    { label: 'Dependencies', hint: 'Missing tools', icon: <Wrench className="w-5 h-5" />, action: go(() => onOpenPopup('dependencies')) },
    { label: 'Terminal', hint: 'Ask + run', icon: <TerminalIcon className="w-5 h-5" />, action: go(() => onGoTab('terminal')) },
    { label: 'Tactical Map', hint: 'Asset graph', icon: <MapPin className="w-5 h-5" />, action: go(() => onGoTab('map')) },
    { label: '/out', hint: 'Evidence', icon: <FolderDown className="w-5 h-5" />, action: go(() => onGoTab('out')) },
    { label: 'Reports', hint: 'Read + export', icon: <FileText className="w-5 h-5" />, action: go(() => onGoTab('report')) },
    { label: 'Fuzzy Router', hint: 'Live routing', icon: <Scale className="w-5 h-5" />, action: go(() => onGoTab('fuzzy')) },
    { label: 'Agent Reach', hint: 'Roster + caps', icon: <Bot className="w-5 h-5" />, action: go(() => onGoTab('agent-reach')) },
    { label: 'Host Shell', hint: 'Live PTY', icon: <TerminalSquare className="w-5 h-5" />, action: go(() => onOpenPopup('shell')) },
    { label: 'Tasks', hint: 'Ledger', icon: <ListChecks className="w-5 h-5" />, action: go(() => onOpenPopup('tasks')) },
    { label: 'Scope', hint: 'Engagements', icon: <Crosshair className="w-5 h-5" />, action: go(() => onOpenPopup('scope')) },
    { label: 'Tools', hint: 'Inventory', icon: <Wrench className="w-5 h-5" />, action: go(() => onOpenPopup('tools')) },
    { label: 'Models', hint: 'Local AI', icon: <BrainCircuit className="w-5 h-5" />, action: go(() => onOpenPopup('models')) },
    { label: 'System', hint: 'Health', icon: <Activity className="w-5 h-5" />, action: go(() => onOpenPopup('system')) },
    { label: 'Conversations', hint: 'Threads', icon: <History className="w-5 h-5" />, action: go(() => onOpenPopup('history')) },
    { label: 'Memory', hint: 'Knowledge', icon: <Database className="w-5 h-5" />, action: go(() => onOpenPopup('memory')) },
    { label: 'Settings', hint: 'Policy', icon: <SettingsIcon className="w-5 h-5" />, action: go(() => onOpenPopup('settings')) },
    { label: 'AI Ops', hint: 'Advisory trace', icon: <Cpu className="w-5 h-5" />, action: go(() => onOpenPopup('aiops')) },
    { label: 'Help', hint: 'Reference', icon: <CircleHelp className="w-5 h-5" />, action: go(() => onOpenPopup('helpwin')) },
    { label: 'About', hint: 'App + downloads', icon: <Info className="w-5 h-5" />, action: go(() => onOpenPopup('about')) },
  ];

  return (
    <div className="p-4">
      <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
        {tiles.map((tile) => (
          <button
            key={tile.label}
            onClick={tile.action}
            className="flex flex-col items-center gap-1 p-3 rounded bg-black/50 border border-[var(--theme-border)] text-stone-300 hover:text-[var(--theme-primary)] hover:border-[var(--theme-primary)] hover:bg-black/70 transition-all cursor-pointer"
          >
            <span className="text-[var(--theme-primary)]">{tile.icon}</span>
            <span className="font-bold text-[11px]">{tile.label}</span>
            <span className="text-[9px] text-stone-500">{tile.hint}</span>
          </button>
        ))}
      </div>
    </div>
  );
};
