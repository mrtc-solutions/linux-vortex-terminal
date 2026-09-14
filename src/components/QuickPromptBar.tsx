import React from 'react';
import { Sparkles, TerminalSquare, ShieldAlert, Cpu, Activity, FolderSearch, Radio } from 'lucide-react';
import { sound } from '../services/soundEffects';

interface QuickPromptBarProps {
  onSelectPrompt: (prompt: string) => void;
}

export const QuickPromptBar: React.FC<QuickPromptBarProps> = ({ onSelectPrompt }) => {
  const prompts = [
    {
      label: 'System Health',
      cmd: 'Show a system health summary for this machine',
      badge: 'Host',
      icon: Activity,
    },
    {
      label: 'Disk Usage',
      cmd: 'Check disk usage on all mounted filesystems',
      badge: 'Host',
      icon: FolderSearch,
    },
    {
      label: 'Listening Ports',
      cmd: 'List listening network ports and the processes behind them',
      badge: 'Network',
      icon: Radio,
    },
    {
      label: 'SUID Audit',
      cmd: 'Find all SUID binaries on this machine to check for privilege escalation vectors',
      badge: 'PrivEsc',
      icon: TerminalSquare,
    },
    {
      label: 'Failed SSH Logins',
      cmd: 'Extract failed SSH login attempts from the auth log and summarize attacker IPs',
      badge: 'Forensics',
      icon: Cpu,
    },
    {
      label: 'Tool Inventory',
      cmd: 'What security tools are installed on this machine?',
      badge: 'Tools',
      icon: Sparkles,
    },
    {
      label: 'Guardian Block Demo',
      cmd: 'Delete everything on this machine',
      badge: 'Guardrail',
      icon: ShieldAlert,
    },
  ];

  return (
    <div className="bg-[var(--theme-surface)]/70 border-b border-[var(--theme-border)] px-3 py-1.5 flex items-center gap-2 overflow-x-auto text-xs no-scrollbar select-none">
      <span className="text-[var(--theme-dim)] font-mono whitespace-nowrap flex items-center gap-1 font-semibold">
        <Sparkles className="w-3.5 h-3.5 text-[var(--theme-primary)]" />
        AI Prompts:
      </span>
      <div className="flex items-center space-x-2">
        {prompts.map((p, idx) => (
          <button
            key={idx}
            onClick={() => {
              sound.playKeypress();
              onSelectPrompt(p.cmd);
            }}
            className="flex items-center space-x-1.5 px-2 py-0.5 rounded border border-[var(--theme-border)] bg-black/40 hover:bg-[var(--theme-border)] text-stone-300 hover:text-[var(--theme-primary)] transition-all cursor-pointer whitespace-nowrap text-[11px]"
          >
            <span
              className={`text-[9px] uppercase px-1 rounded font-mono ${
                p.badge === 'Guardrail'
                  ? 'bg-rose-950 text-rose-300 border border-rose-800/40'
                  : 'bg-[var(--theme-dim)]/20 text-[var(--theme-primary)]'
              }`}
            >
              {p.badge}
            </span>
            <span>{p.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
};
