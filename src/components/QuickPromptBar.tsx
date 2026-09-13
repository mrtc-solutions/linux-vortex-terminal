import React from 'react';
import { Sparkles, TerminalSquare, ShieldAlert, Cpu } from 'lucide-react';
import { sound } from '../services/soundEffects';

interface QuickPromptBarProps {
  onSelectPrompt: (prompt: string) => void;
}

export const QuickPromptBar: React.FC<QuickPromptBarProps> = ({ onSelectPrompt }) => {
  const prompts = [
    {
      label: 'Scan Subnet 192.168.1.0/24',
      cmd: 'Scan the local subnet 192.168.1.0/24 for open SSH and HTTP ports with service detection',
      badge: 'Recon',
      icon: Sparkles,
    },
    {
      label: 'SUID PrivEsc Audit',
      cmd: 'Find all SUID binaries on this machine to check for privilege escalation vectors',
      badge: 'PrivEsc',
      icon: TerminalSquare,
    },
    {
      label: 'Extract Failed SSH Logins',
      cmd: 'Extract all failed SSH login attempts from auth.log and summarize attacker IPs',
      badge: 'Forensics',
      icon: Cpu,
    },
    {
      label: 'Sniff eth0 Traffic',
      cmd: 'Sniff packet traffic on interface eth0 looking for cleartext HTTP credentials',
      badge: 'Network',
      icon: Sparkles,
    },
    {
      label: 'Fuzz Web Endpoints',
      cmd: 'Audit directory endpoints on http://192.168.1.15:8080 for exposed actuator routes',
      badge: 'Web App',
      icon: Sparkles,
    },
    {
      label: 'Auto Pentest Report',
      cmd: 'Generate an ethical hacking executive report for client ACME Corp',
      badge: 'Compliance',
      icon: Sparkles,
    },
    {
      label: 'Safety Guardrail Test (rm -rf /)',
      cmd: 'rm -rf / --no-preserve-root',
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
