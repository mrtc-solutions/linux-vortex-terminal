import React from 'react';
import { FuzzyConsensusResult } from '../types/terminal';
import { X, Scale, Cpu, ShieldCheck, CheckCircle2, AlertTriangle, XCircle, Sparkles } from 'lucide-react';
import { sound } from '../services/soundEffects';

interface FuzzyOrchestrationModalProps {
  consensus: FuzzyConsensusResult | null;
  onClose: () => void;
  onSelectCommand?: (cmd: string) => void;
}

export const FuzzyOrchestrationModal: React.FC<FuzzyOrchestrationModalProps> = ({
  consensus,
  onClose,
}) => {
  if (!consensus) return null;

  const getStatusBadge = (rec: FuzzyConsensusResult['recommendation']) => {
    switch (rec) {
      case 'EXECUTE_OPTIMAL':
        return (
          <span className="flex items-center gap-1.5 px-3 py-1 rounded bg-emerald-950/80 border border-emerald-500/60 text-emerald-400 text-xs font-semibold">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            EXECUTE_OPTIMAL (Auto-Authorized)
          </span>
        );
      case 'EXECUTE_SANDBOXED':
        return (
          <span className="flex items-center gap-1.5 px-3 py-1 rounded bg-amber-950/80 border border-amber-500/60 text-amber-400 text-xs font-semibold">
            <AlertTriangle className="w-4 h-4 text-amber-400" />
            EXECUTE_SANDBOXED (RAM Isolation)
          </span>
        );
      case 'SAFETY_INTERLOCK_REQUIRED':
        return (
          <span className="flex items-center gap-1.5 px-3 py-1 rounded bg-orange-950/80 border border-orange-500/60 text-orange-400 text-xs font-semibold">
            <AlertTriangle className="w-4 h-4 text-orange-400" />
            INTERLOCK CONFIRMATION REQUIRED
          </span>
        );
      case 'REJECT':
      default:
        return (
          <span className="flex items-center gap-1.5 px-3 py-1 rounded bg-rose-950/80 border border-rose-500/60 text-rose-400 text-xs font-semibold">
            <XCircle className="w-4 h-4 text-rose-400" />
            REJECTED BY ETHICAL GUARDRAIL
          </span>
        );
    }
  };

  // Helper to draw triangular membership curves on SVG
  const renderTriangularSVG = (score: number, label: string) => {
    // 3 curves: Left, Mid, Right
    return (
      <div className="bg-black/60 rounded p-2 border border-[var(--theme-border)]">
        <div className="flex justify-between items-center text-xs mb-1">
          <span className="font-semibold text-stone-300">{label}</span>
          <span className="text-[var(--theme-primary)] font-mono font-bold">{score}%</span>
        </div>
        <svg viewBox="0 0 100 40" className="w-full h-14 overflow-visible">
          {/* Grid lines */}
          <line x1="0" y1="35" x2="100" y2="35" stroke="#333" strokeWidth="0.8" />
          <line x1="0" y1="5" x2="100" y2="5" stroke="#222" strokeDasharray="2" strokeWidth="0.5" />

          {/* Curve 1: Low (0, 15, 45) */}
          <polygon points="0,5 15,5 45,35 0,35" fill="rgba(239, 68, 68, 0.15)" stroke="#ef4444" strokeWidth="1" />
          {/* Curve 2: Medium (35, 60, 80) */}
          <polygon points="35,35 60,5 80,35" fill="rgba(245, 158, 11, 0.15)" stroke="#f59e0b" strokeWidth="1" />
          {/* Curve 3: High (65, 90, 100) */}
          <polygon points="65,35 90,5 100,5 100,35" fill="rgba(0, 255, 102, 0.15)" stroke="#00ff66" strokeWidth="1" />

          {/* Current Score Indicator Needle */}
          <line x1={score} y1="0" x2={score} y2="35" stroke="#ffffff" strokeWidth="1.5" strokeDasharray="1 1" />
          <circle cx={score} cy="10" r="2.5" fill="#ffffff" />
        </svg>
        <div className="flex justify-between text-[10px] text-stone-500 font-mono mt-1">
          <span className="text-rose-400">Low (0-40)</span>
          <span className="text-amber-400">Moderate (40-75)</span>
          <span className="text-emerald-400">Optimal (75-100)</span>
        </div>
      </div>
    );
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="bg-[var(--theme-surface)] border border-[var(--theme-border)] rounded-lg w-full max-w-4xl max-h-[92vh] flex flex-col box-glow shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--theme-border)] bg-black/40">
          <div className="flex items-center space-x-2">
            <Scale className="w-5 h-5 text-[var(--theme-primary)]" />
            <h2 className="text-sm font-bold tracking-wider text-[var(--theme-primary)] glow-primary">
              MULTI-LLM FUZZY LOGIC CONSENSUS ARBITER
            </h2>
            <span className="text-[11px] px-2 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800">
              Mamdani Centroid Defuzzification
            </span>
          </div>
          <button
            onClick={() => {
              sound.playKeypress();
              onClose();
            }}
            className="text-stone-400 hover:text-white p-1 rounded hover:bg-white/10 transition-colors cursor-pointer"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content Body */}
        <div className="p-4 space-y-4 overflow-y-auto text-xs font-mono">
          {/* Top Banner: Defuzzification Result */}
          <div className="bg-black/50 border border-[var(--theme-border)] rounded p-4 flex flex-wrap items-center justify-between gap-4">
            <div>
              <div className="text-stone-400 text-xs mb-1">Defuzzified Consensus Score (Centroid):</div>
              <div className="flex items-baseline space-x-2">
                <span className="text-3xl font-extrabold text-[var(--theme-primary)] glow-primary">
                  {consensus.centroid.toFixed(1)}%
                </span>
                <span className="text-stone-400 text-xs">/ 100.0</span>
              </div>
              <p className="text-stone-400 text-[11px] mt-1 max-w-md">
                {consensus.explanation}
              </p>
            </div>
            <div>{getStatusBadge(consensus.recommendation)}</div>
          </div>

          {/* Section 1: The 3 Local LLM Deliberations */}
          <div>
            <div className="flex items-center gap-1.5 text-stone-300 font-semibold mb-2">
              <Cpu className="w-4 h-4 text-[var(--theme-primary)]" />
              <span>Participating Local Models &amp; Chain-of-Thought</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {consensus.deliberations.map((d) => (
                <div key={d.modelId} className="bg-black/40 border border-[var(--theme-border)] rounded p-3 flex flex-col justify-between">
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-bold text-[var(--theme-primary)] text-xs">{d.modelName}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-stone-800 text-stone-300">
                        Conf: {d.confidence}%
                      </span>
                    </div>
                    <p className="text-stone-300 text-[11px] leading-relaxed mb-2 italic">
                      "{d.thought}"
                    </p>
                  </div>
                  <div className="mt-2 pt-2 border-t border-stone-800 text-[10px] text-stone-400">
                    <span className="text-stone-500 font-mono">Output token stream:</span>
                    <div className="mt-0.5 bg-black/80 p-1.5 rounded text-emerald-400 font-mono text-[10px] break-all max-h-16 overflow-y-auto">
                      {d.rawOutput}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Section 2: Fuzzy Membership Curves */}
          <div>
            <div className="flex items-center gap-1.5 text-stone-300 font-semibold mb-2">
              <Sparkles className="w-4 h-4 text-[var(--theme-primary)]" />
              <span>Triangular Membership Functions &amp; Degree of Truth ($\mu$)</span>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
              {renderTriangularSVG(consensus.confidenceVar.score, 'Reasoning Fidelity (R1)')}
              {renderTriangularSVG(consensus.precisionVar.score, 'Syntax Precision (L3.3)')}
              {renderTriangularSVG(consensus.safetyVar.score, 'Blast Radius Safety (Nemo)')}
            </div>
          </div>

          {/* Section 3: Rule Base & Firing Table */}
          <div>
            <div className="flex items-center gap-1.5 text-stone-300 font-semibold mb-2">
              <ShieldCheck className="w-4 h-4 text-[var(--theme-primary)]" />
              <span>Inference Rule Base Evaluation</span>
            </div>
            <div className="border border-[var(--theme-border)] rounded overflow-hidden">
              <table className="w-full text-left text-[11px]">
                <thead className="bg-black/60 text-stone-400 border-b border-[var(--theme-border)]">
                  <tr>
                    <th className="p-2">Rule ID</th>
                    <th className="p-2">Logical Proposition</th>
                    <th className="p-2">Weight ($\alpha$-Cut)</th>
                    <th className="p-2">State</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--theme-border)] bg-black/30">
                  {consensus.rules.map((r) => (
                    <tr key={r.id} className={r.fired ? 'bg-emerald-950/20' : 'opacity-60'}>
                      <td className="p-2 font-bold text-[var(--theme-primary)]">{r.id}</td>
                      <td className="p-2 text-stone-300">{r.rule}</td>
                      <td className="p-2 font-mono text-stone-400">{(r.weight * 100).toFixed(0)}%</td>
                      <td className="p-2">
                        {r.fired ? (
                          <span className="text-emerald-400 font-semibold">ACTIVATED</span>
                        ) : (
                          <span className="text-stone-500">INACTIVE</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Mathematical Centroid Formula Explanation */}
          <div className="p-3 bg-black/60 rounded border border-[var(--theme-border)] text-stone-400 text-[11px] leading-relaxed">
            <span className="text-[var(--theme-primary)] font-bold">Defuzzification Centroid Formula: </span>
            <code className="text-emerald-300 bg-black/80 px-2 py-0.5 rounded ml-1">
              Z* = &int; z &middot; &mu;_C(z) dz / &int; &mu;_C(z) dz = {consensus.centroid.toFixed(2)}
            </code>
            <p className="mt-1">
              The consensus arbiter aggregates the membership grades of the reasoning, syntax, and guardrail LLMs, evaluates Mamdani minimum-norm implication, and defuzzifies the output space into a deterministic execution threshold.
            </p>
          </div>
        </div>

        {/* Modal Footer */}
        <div className="px-4 py-2 border-t border-[var(--theme-border)] bg-black/40 flex justify-end">
          <button
            onClick={() => {
              sound.playKeypress();
              onClose();
            }}
            className="px-4 py-1.5 rounded bg-[var(--theme-primary)] text-black font-semibold text-xs hover:opacity-90 transition-opacity cursor-pointer"
          >
            Acknowledge &amp; Return
          </button>
        </div>
      </div>
    </div>
  );
};
