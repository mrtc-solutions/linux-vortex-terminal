import React, { useState } from 'react';
import { evaluateFuzzyConsensus } from '../services/fuzzyLogicEngine';
import { LOCAL_MODELS } from '../services/multiLLMOrchestrator';
import { 
  Scale, 
  Cpu, 
  CheckCircle2, 
  AlertTriangle, 
  XCircle, 
  Sparkles, 
  ShieldCheck, 
  Sliders,
  RotateCcw
} from 'lucide-react';
import { sound } from '../services/soundEffects';

interface FuzzyTabProps {
  onExecuteCommand?: (cmd: string) => void;
}

export const FuzzyTab: React.FC<FuzzyTabProps> = () => {
  const [reasoningScore, setReasoningScore] = useState<number>(94);
  const [precisionScore, setPrecisionScore] = useState<number>(92);
  const [safetyScore, setSafetyScore] = useState<number>(96);

  const sampleDeliberations = [
    {
      modelId: 'deepseek-r1-7b',
      modelName: 'DeepSeek-R1-Distill-7B',
      thought: `Deconstructed semantic intention: Subnet port scan with version detection. Chain-of-thought identifies target 192.168.1.0/24 as authorized local CIDR block. Recommends half-open SYN packets to minimize intrusion footprint.`,
      rawOutput: `Intent validated. Threat profile: Passive reconnaissance. Priority: High confidence.`,
      confidence: reasoningScore,
    },
    {
      modelId: 'llama-3.3-8b',
      modelName: 'Llama-3.3-Security-8B',
      thought: `POSIX shell translation formulated: nmap -sS -sV -T4 -p 22,80,443,3306,5432 192.168.1.0/24 -oA /out/scans/recon. Parameter syntax verified against man nmap. Output redirect configured to /out.`,
      rawOutput: `nmap -sS -sV -T4 192.168.1.0/24 -oA /out/scans/recon`,
      confidence: precisionScore,
    },
    {
      modelId: 'mistral-nemo-12b',
      modelName: 'Mistral-Nemo-Audit-12B',
      thought: `Blast radius verification: Non-destructive SYN probes strictly bounded within RFC 1918 space. No denial of service or exploit payload execution. Guardrail status: Approved.`,
      rawOutput: `AUDIT VERDICT: 0 CVE violations. Blast radius: NEGLIGIBLE.`,
      confidence: safetyScore,
    },
  ];

  const consensus = evaluateFuzzyConsensus(
    reasoningScore,
    precisionScore,
    safetyScore,
    sampleDeliberations
  );

  const renderTriangularSVG = (score: number, label: string, color: string) => {
    return (
      <div className="bg-black/60 rounded-lg p-3 border border-[var(--theme-border)]">
        <div className="flex justify-between items-center text-xs mb-1">
          <span className="font-semibold text-stone-200">{label}</span>
          <span className="font-mono font-bold" style={{ color }}>{score}%</span>
        </div>
        <svg viewBox="0 0 100 40" className="w-full h-14 overflow-visible">
          <line x1="0" y1="35" x2="100" y2="35" stroke="#333" strokeWidth="0.8" />
          <line x1="0" y1="5" x2="100" y2="5" stroke="#222" strokeDasharray="2" strokeWidth="0.5" />

          {/* Curve 1: Low */}
          <polygon points="0,5 15,5 45,35 0,35" fill="rgba(239, 68, 68, 0.15)" stroke="#ef4444" strokeWidth="1" />
          {/* Curve 2: Medium */}
          <polygon points="35,35 60,5 80,35" fill="rgba(245, 158, 11, 0.15)" stroke="#f59e0b" strokeWidth="1" />
          {/* Curve 3: High */}
          <polygon points="65,35 90,5 100,5 100,35" fill="rgba(0, 255, 102, 0.15)" stroke="#00ff66" strokeWidth="1" />

          {/* Current Score Indicator */}
          <line x1={score} y1="0" x2={score} y2="35" stroke="#ffffff" strokeWidth="1.5" strokeDasharray="1 1" />
          <circle cx={score} cy="8" r="3" fill="#ffffff" />
        </svg>
        <div className="flex justify-between text-[10px] text-stone-500 font-mono mt-1">
          <span className="text-rose-400">Low (0-40)</span>
          <span className="text-amber-400">Moderate (40-75)</span>
          <span className="text-emerald-400">Optimal (75-100)</span>
        </div>
      </div>
    );
  };

  const getStatusBadge = (rec: typeof consensus.recommendation) => {
    switch (rec) {
      case 'EXECUTE_OPTIMAL':
        return (
          <span className="flex items-center gap-1.5 px-3 py-1 rounded bg-emerald-950/90 border border-emerald-500/70 text-emerald-400 font-bold text-xs">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            EXECUTE_OPTIMAL (Auto-Authorized)
          </span>
        );
      case 'EXECUTE_SANDBOXED':
        return (
          <span className="flex items-center gap-1.5 px-3 py-1 rounded bg-amber-950/90 border border-amber-500/70 text-amber-400 font-bold text-xs">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            EXECUTE_SANDBOXED (RAM Jail Isolation)
          </span>
        );
      case 'SAFETY_INTERLOCK_REQUIRED':
        return (
          <span className="flex items-center gap-1.5 px-3 py-1 rounded bg-orange-950/90 border border-orange-500/70 text-orange-400 font-bold text-xs">
            <AlertTriangle className="w-4 h-4 text-orange-400" />
            SAFETY_INTERLOCK_REQUIRED (Prompt User)
          </span>
        );
      case 'REJECT':
      default:
        return (
          <span className="flex items-center gap-1.5 px-3 py-1 rounded bg-rose-950/90 border border-rose-500/70 text-rose-400 font-bold text-xs">
            <XCircle className="w-4 h-4 text-rose-400" />
            REJECTED BY ETHICAL GUARDRAIL
          </span>
        );
    }
  };

  const handleResetSliders = () => {
    sound.playKeypress();
    setReasoningScore(94);
    setPrecisionScore(92);
    setSafetyScore(96);
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--theme-bg)] font-mono text-xs overflow-y-auto p-4 select-text">
      <div className="max-w-5xl mx-auto w-full space-y-4">
        {/* Top Header */}
        <div className="bg-[var(--theme-surface)]/90 border border-[var(--theme-border)] rounded-lg p-4 box-glow flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center space-x-3">
            <div className="p-2 rounded bg-black/60 border border-[var(--theme-border)] text-[var(--theme-primary)]">
              <Scale className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <h1 className="text-sm font-bold text-[var(--theme-primary)] glow-primary">
                  FUZZY LOGIC MULTI-LLM ORCHESTRATION ARBITER
                </h1>
                <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800 font-bold">
                  Mamdani Centroid Defuzzifier
                </span>
              </div>
              <p className="text-stone-400 text-[11px] mt-0.5">
                Combines asynchronous inference from 3 local LLMs using continuous membership functions and defuzzifies the consensus score.
              </p>
            </div>
          </div>

          <div className="flex items-center space-x-2">
            <button
              onClick={handleResetSliders}
              className="flex items-center space-x-1 px-3 py-1.5 rounded bg-black/50 border border-[var(--theme-border)] text-stone-300 hover:text-white transition-colors cursor-pointer text-xs"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              <span>Reset Weights</span>
            </button>
          </div>
        </div>

        {/* Live Defuzzification Centroid Hero */}
        <div className="bg-black/60 border border-[var(--theme-border)] rounded-lg p-4 flex flex-wrap items-center justify-between gap-4 box-glow">
          <div>
            <div className="text-stone-400 text-xs mb-1">
              Defuzzified Consensus Result ($Z^*$ Centroid):
            </div>
            <div className="flex items-baseline space-x-2">
              <span className="text-4xl font-extrabold text-[var(--theme-primary)] glow-primary">
                {consensus.centroid.toFixed(1)}%
              </span>
              <span className="text-stone-400 text-xs font-mono">/ 100.0</span>
            </div>
            <p className="text-stone-400 text-xs mt-1.5 max-w-xl">
              {consensus.explanation}
            </p>
          </div>

          <div>{getStatusBadge(consensus.recommendation)}</div>
        </div>

        {/* Interactive Sliders: Tune LLM Inputs */}
        <div className="bg-black/50 border border-[var(--theme-border)] rounded-lg p-4 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-2 text-stone-200 font-semibold text-xs">
              <Sliders className="w-4 h-4 text-[var(--theme-primary)]" />
              <span>Interactive Model Confidence Sliders (Test Fuzzy Reactions)</span>
            </div>
            <span className="text-stone-500 text-[11px]">Drag sliders to see live centroid deflection</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Slider 1: DeepSeek R1 */}
            <div className="p-3 rounded bg-black/60 border border-sky-800/60 space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-sky-400 font-bold text-xs">DeepSeek-R1 (Reasoning)</span>
                <span className="text-white font-mono font-bold">{reasoningScore}%</span>
              </div>
              <input
                type="range"
                min="0"
                max="100"
                value={reasoningScore}
                onChange={(e) => {
                  setReasoningScore(Number(e.target.value));
                  sound.playKeypress();
                }}
                className="w-full accent-sky-400 cursor-pointer"
              />
              <div className="text-[10px] text-stone-400">
                Semantic understanding, intent deconstruction, target identification
              </div>
            </div>

            {/* Slider 2: Llama 3.3 */}
            <div className="p-3 rounded bg-black/60 border border-emerald-800/60 space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-emerald-400 font-bold text-xs">Llama-3.3 (Syntax/Shell)</span>
                <span className="text-white font-mono font-bold">{precisionScore}%</span>
              </div>
              <input
                type="range"
                min="0"
                max="100"
                value={precisionScore}
                onChange={(e) => {
                  setPrecisionScore(Number(e.target.value));
                  sound.playKeypress();
                }}
                className="w-full accent-emerald-400 cursor-pointer"
              />
              <div className="text-[10px] text-stone-400">
                POSIX flag accuracy, bash pipeline soundness, output redirect syntax
              </div>
            </div>

            {/* Slider 3: Mistral Nemo */}
            <div className="p-3 rounded bg-black/60 border border-amber-800/60 space-y-2">
              <div className="flex justify-between items-center">
                <span className="text-amber-400 font-bold text-xs">Mistral-Nemo (Safety/Guardrail)</span>
                <span className="text-white font-mono font-bold">{safetyScore}%</span>
              </div>
              <input
                type="range"
                min="0"
                max="100"
                value={safetyScore}
                onChange={(e) => {
                  setSafetyScore(Number(e.target.value));
                  sound.playKeypress();
                }}
                className="w-full accent-amber-400 cursor-pointer"
              />
              <div className="text-[10px] text-stone-400">
                Blast radius analysis, privilege escalation check, non-destructive audit
              </div>
            </div>
          </div>
        </div>

        {/* Membership Curves */}
        <div className="bg-black/50 border border-[var(--theme-border)] rounded-lg p-4 space-y-3">
          <div className="flex items-center space-x-2 text-stone-200 font-semibold text-xs">
            <Sparkles className="w-4 h-4 text-[var(--theme-primary)]" />
            <span>Triangular Fuzzy Membership Curves &amp; Input Locations</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {renderTriangularSVG(reasoningScore, 'DeepSeek-R1 Intent Reasoning', '#38bdf8')}
            {renderTriangularSVG(precisionScore, 'Llama-3.3 Shell Precision', '#00ff66')}
            {renderTriangularSVG(safetyScore, 'Mistral-Nemo Safety Guardrail', '#f59e0b')}
          </div>
        </div>

        {/* Inference Rule Base Table */}
        <div className="bg-black/50 border border-[var(--theme-border)] rounded-lg p-4 space-y-3">
          <div className="flex items-center space-x-2 text-stone-200 font-semibold text-xs">
            <ShieldCheck className="w-4 h-4 text-[var(--theme-primary)]" />
            <span>Mamdani Inference Rule Base Evaluation</span>
          </div>

          <div className="border border-[var(--theme-border)] rounded overflow-hidden">
            <table className="w-full text-left text-[11px]">
              <thead className="bg-black/70 text-stone-400 border-b border-[var(--theme-border)]">
                <tr>
                  <th className="p-2.5">Rule ID</th>
                  <th className="p-2.5">Proposition</th>
                  <th className="p-2.5">Degree (&alpha;-Cut)</th>
                  <th className="p-2.5">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--theme-border)]/50 bg-black/30">
                {consensus.rules.map((r) => (
                  <tr key={r.id} className={r.fired ? 'bg-emerald-950/25' : 'opacity-60'}>
                    <td className="p-2.5 font-bold text-[var(--theme-primary)]">{r.id}</td>
                    <td className="p-2.5 text-stone-200">{r.rule}</td>
                    <td className="p-2.5 font-mono text-stone-300">{(r.weight * 100).toFixed(0)}%</td>
                    <td className="p-2.5">
                      {r.fired ? (
                        <span className="text-emerald-400 font-bold px-1.5 py-0.5 rounded bg-emerald-950 border border-emerald-800">
                          FIRED
                        </span>
                      ) : (
                        <span className="text-stone-500 font-mono">SUPPRESSED</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Participating Local Models Hardware Status */}
        <div className="bg-black/50 border border-[var(--theme-border)] rounded-lg p-4 space-y-3">
          <div className="flex items-center space-x-2 text-stone-200 font-semibold text-xs">
            <Cpu className="w-4 h-4 text-[var(--theme-primary)]" />
            <span>Local Cluster Runtime Telemetry</span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {LOCAL_MODELS.map((m) => (
              <div key={m.id} className="p-3 rounded bg-black/60 border border-[var(--theme-border)] space-y-1.5">
                <div className="flex items-center justify-between">
                  <span className="font-bold text-xs" style={{ color: m.color }}>{m.name}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800">
                    ONLINE
                  </span>
                </div>
                <div className="text-[11px] text-stone-400">
                  Quantization: <span className="text-stone-200">{m.quantization}</span>
                </div>
                <div className="text-[11px] text-stone-400">
                  VRAM Allocation: <span className="text-stone-200">{m.vramUsageMB} MB</span>
                </div>
                <div className="text-[11px] text-stone-400">
                  Inference Latency: <span className="text-stone-200">{m.latencyMs} ms ({m.tokensPerSec} t/s)</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
};
