import React, { useState } from 'react';
import { 
  Activity, 
  Shield, 
  Layers, 
  CheckCircle2, 
  Sliders
} from 'lucide-react';
import { sound } from '../services/soundEffects';

interface AgentReachInspectorProps {
  onExecuteCommand: (cmd: string) => void;
}

export const AgentReachInspector: React.FC<AgentReachInspectorProps> = ({ onExecuteCommand }) => {
  const [dryRunMode, setDryRunMode] = useState(false);
  const [reachLevel, setReachLevel] = useState<'RESTRICTED' | 'SANDBOX_JAIL' | 'RAW_SOCKETS' | 'ROOT_CAP_ADMIN'>('RAW_SOCKETS');

  const capabilities = [
    {
      name: 'POSIX File System Writethrough',
      scope: '/out and /tmp only (Immutable root)',
      status: 'ACTIVE',
      reach: 'SANDBOX',
    },
    {
      name: 'Raw Network Sockets (CAP_NET_RAW)',
      scope: 'Permits ARP, SYN stealth probes, and tshark PCAP captures',
      status: 'ACTIVE',
      reach: 'RAW_SOCKETS',
    },
    {
      name: 'Memory Introspection & /proc Read',
      scope: 'Process tree analysis, open file descriptors, CPU profiling',
      status: 'ACTIVE',
      reach: 'USERLAND',
    },
    {
      name: 'Destructive Modification Shield',
      scope: 'Blocks rm -rf, dd to block devices, forkbombs, zeroing MBR',
      status: 'ENFORCED BY MISTRAL-NEMO',
      reach: 'GUARDRAIL',
    },
    {
      name: 'Out Directory Auto-Mirroring',
      scope: 'Every command output with artifacts writes to /out filesystem',
      status: 'ACTIVE',
      reach: 'SYSTEM',
    },
  ];

  const handleTestProbe = () => {
    sound.playExecute();
    onExecuteCommand('agentctl reach --status --verbose');
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--theme-bg)] font-mono text-xs overflow-y-auto p-4 select-text">
      <div className="max-w-5xl mx-auto w-full space-y-4">
        {/* Header */}
        <div className="bg-[var(--theme-surface)]/90 border border-[var(--theme-border)] rounded-lg p-4 box-glow flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center space-x-3">
            <div className="p-2 rounded bg-black/60 border border-[var(--theme-border)] text-[var(--theme-primary)]">
              <Activity className="w-6 h-6 animate-pulse" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <h1 className="text-sm font-bold text-[var(--theme-primary)] glow-primary">
                  AGENT-REACH EXECUTION ENVELOPE &amp; KERNEL BRIDGE
                </h1>
                <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800 font-bold">
                  eBPF MONITORING: ACTIVE
                </span>
              </div>
              <p className="text-stone-400 text-[11px] mt-0.5">
                The Agent-Reach framework bridges translated natural language from local LLMs directly into sandboxed POSIX execution syscalls.
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            <button
              onClick={() => {
                setDryRunMode(!dryRunMode);
                sound.playKeypress();
              }}
              className={`px-3 py-1.5 rounded border text-xs font-semibold cursor-pointer transition-all ${
                dryRunMode
                  ? 'bg-amber-500 text-black border-amber-400'
                  : 'bg-black/50 border-[var(--theme-border)] text-stone-300'
              }`}
            >
              Dry-Run Mode: {dryRunMode ? 'ON' : 'OFF'}
            </button>

            <button
              onClick={handleTestProbe}
              className="px-3 py-1.5 rounded bg-[var(--theme-primary)] text-black font-semibold hover:opacity-90 cursor-pointer text-xs"
            >
              Probe Reach Health
            </button>
          </div>
        </div>

        {/* Reach Privilege Level Selector */}
        <div className="bg-black/50 border border-[var(--theme-border)] rounded-lg p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2 text-stone-200 font-semibold text-xs">
              <Sliders className="w-4 h-4 text-[var(--theme-primary)]" />
              <span>Current Agent Security Clearance &amp; System Envelope</span>
            </div>
            <span className="text-[11px] text-[var(--theme-primary)] font-bold">
              Level: {reachLevel}
            </span>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {[
              { id: 'RESTRICTED', label: '1. Restricted Userland', desc: 'Read-only unprivileged CLI tools' },
              { id: 'SANDBOX_JAIL', label: '2. Sandbox Jail', desc: 'Isolated namespaces with RAM overlay' },
              { id: 'RAW_SOCKETS', label: '3. Raw Sockets (Active)', desc: 'CAP_NET_RAW for Nmap & Tshark' },
              { id: 'ROOT_CAP_ADMIN', label: '4. Root Sudo Reach', desc: 'Full root privileges with confirmation' },
            ].map((lvl) => (
              <button
                key={lvl.id}
                onClick={() => {
                  setReachLevel(lvl.id as unknown as typeof reachLevel);
                  sound.playKeypress();
                }}
                className={`p-3 rounded text-left border transition-all cursor-pointer ${
                  reachLevel === lvl.id
                    ? 'bg-[var(--theme-surface)] border-[var(--theme-primary)] text-white box-glow'
                    : 'bg-black/40 border-stone-800 text-stone-400 hover:text-stone-200'
                }`}
              >
                <div className="font-bold text-xs">{lvl.label}</div>
                <div className="text-[10px] text-stone-500 mt-1">{lvl.desc}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Agent Flow Diagram */}
        <div className="bg-black/60 border border-[var(--theme-border)] rounded-lg p-4 space-y-3">
          <div className="text-xs font-semibold text-stone-200 flex items-center space-x-2">
            <Layers className="w-4 h-4 text-[var(--theme-primary)]" />
            <span>Agent-Reach Pipeline Flow Architecture</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-5 gap-2 text-center text-[11px]">
            <div className="p-3 rounded bg-black/80 border border-sky-800/60">
              <div className="text-sky-400 font-bold mb-1">1. User Natural Language</div>
              <div className="text-stone-400 text-[10px]">"Scan subnet 192.168.1.0/24 for SSH and HTTP"</div>
            </div>
            <div className="p-3 rounded bg-black/80 border border-indigo-800/60">
              <div className="text-indigo-400 font-bold mb-1">2. Local Multi-LLM Cluster</div>
              <div className="text-stone-400 text-[10px]">DeepSeek-R1 (Reason) + Llama-3.3 (POSIX)</div>
            </div>
            <div className="p-3 rounded bg-black/80 border border-emerald-800/60">
              <div className="text-emerald-400 font-bold mb-1">3. Fuzzy Consensus Arbiter</div>
              <div className="text-stone-400 text-[10px]">Mamdani Rules &amp; Centroid Defuzzification (94.6%)</div>
            </div>
            <div className="p-3 rounded bg-black/80 border border-amber-800/60">
              <div className="text-amber-400 font-bold mb-1">4. Agent-Reach Kernel Bridge</div>
              <div className="text-stone-400 text-[10px]">eBPF Syscall Sandbox &amp; Raw Socket Dispatch</div>
            </div>
            <div className="p-3 rounded bg-black/80 border border-emerald-500/60">
              <div className="text-[var(--theme-primary)] font-bold mb-1">5. Write to /out &amp; UI</div>
              <div className="text-stone-400 text-[10px]">Auto-saved to /out/scans, logs, and reports</div>
            </div>
          </div>
        </div>

        {/* Monitored Capabilities */}
        <div className="bg-black/50 border border-[var(--theme-border)] rounded-lg p-4 space-y-3">
          <div className="text-xs font-semibold text-stone-200 flex items-center space-x-2">
            <Shield className="w-4 h-4 text-[var(--theme-primary)]" />
            <span>Active Reach Capabilities &amp; Sandbox Isolation</span>
          </div>

          <div className="space-y-2">
            {capabilities.map((cap, i) => (
              <div
                key={i}
                className="p-3 rounded bg-black/40 border border-stone-800 flex flex-wrap items-center justify-between gap-2"
              >
                <div>
                  <div className="font-bold text-stone-200 text-xs flex items-center space-x-1.5">
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
                    <span>{cap.name}</span>
                  </div>
                  <div className="text-stone-400 text-[11px] mt-0.5">{cap.scope}</div>
                </div>
                <div className="flex items-center space-x-2">
                  <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-950/80 text-emerald-400 font-mono font-bold border border-emerald-800/60">
                    {cap.status}
                  </span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-stone-900 text-stone-400 font-mono border border-stone-700">
                    [{cap.reach}]
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
