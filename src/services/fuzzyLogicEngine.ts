import { FuzzyConsensusResult, FuzzyMembership, FuzzyRule, FuzzyVariable } from '../types/terminal';

// Triangular membership function evaluator: max(0, min((x-a)/(b-a), (c-x)/(c-b)))
export function triangular(x: number, a: number, b: number, c: number): number {
  if (x <= a || x >= c) return 0;
  if (x === b) return 1;
  if (x > a && x < b) return (x - a) / (b - a);
  return (c - x) / (c - b);
}

// Trapezoidal membership function evaluator
export function trapezoidal(x: number, a: number, b: number, c: number, d: number): number {
  if (x <= a || x >= d) return 0;
  if (x >= b && x <= c) return 1;
  if (x > a && x < b) return (x - a) / (b - a);
  return (d - x) / (d - c);
}

export function computeFuzzyVariable(
  name: string,
  score: number,
  definitions: { label: string; range: [number, number, number] }[]
): FuzzyVariable {
  const memberships: FuzzyMembership[] = definitions.map((def) => {
    const val = triangular(score, def.range[0], def.range[1], def.range[2]);
    return {
      label: def.label,
      range: def.range,
      value: Math.round(val * 100) / 100,
    };
  });

  return {
    name,
    score,
    memberships,
  };
}

export function evaluateFuzzyConsensus(
  reasoningScore: number, // 0 - 100 (DeepSeek-R1)
  precisionScore: number, // 0 - 100 (Llama-3.3)
  safetyScore: number,    // 0 - 100 (Mistral-Nemo)
  deliberations: {
    modelId: string;
    modelName: string;
    thought: string;
    rawOutput: string;
    confidence: number;
  }[]
): FuzzyConsensusResult {
  // 1. Build Fuzzy Variables
  const confidenceVar = computeFuzzyVariable('Intent Reasoning (DeepSeek-R1)', reasoningScore, [
    { label: 'Low', range: [0, 15, 45] },
    { label: 'Moderate', range: [35, 60, 80] },
    { label: 'High', range: [65, 90, 100] },
  ]);

  const precisionVar = computeFuzzyVariable('Command Precision (Llama-3.3)', precisionScore, [
    { label: 'Ambiguous', range: [0, 20, 50] },
    { label: 'Sound', range: [40, 65, 85] },
    { label: 'Optimal', range: [75, 92, 100] },
  ]);

  const safetyVar = computeFuzzyVariable('Blast Radius Safety (Mistral-Nemo)', safetyScore, [
    { label: 'Hazardous', range: [0, 20, 45] },
    { label: 'Sandboxed', range: [35, 65, 85] },
    { label: 'Ethical', range: [70, 95, 100] },
  ]);

  // Extract degrees
  const cHigh = confidenceVar.memberships.find(m => m.label === 'High')?.value || 0;
  const cMod = confidenceVar.memberships.find(m => m.label === 'Moderate')?.value || 0;
  const cLow = confidenceVar.memberships.find(m => m.label === 'Low')?.value || 0;

  const pOpt = precisionVar.memberships.find(m => m.label === 'Optimal')?.value || 0;
  const pSound = precisionVar.memberships.find(m => m.label === 'Sound')?.value || 0;
  const pAmb = precisionVar.memberships.find(m => m.label === 'Ambiguous')?.value || 0;

  const sEthical = safetyVar.memberships.find(m => m.label === 'Ethical')?.value || 0;
  const sSandbox = safetyVar.memberships.find(m => m.label === 'Sandboxed')?.value || 0;
  const sHazard = safetyVar.memberships.find(m => m.label === 'Hazardous')?.value || 0;

  // 2. Evaluate Rule Base
  const rules: FuzzyRule[] = [
    {
      id: 'R1',
      rule: 'IF Intent is High AND Precision is Optimal AND Safety is Ethical THEN Execution is Optimal',
      weight: Math.min(cHigh, pOpt, sEthical),
      fired: Math.min(cHigh, pOpt, sEthical) > 0.15,
    },
    {
      id: 'R2',
      rule: 'IF Intent is High AND Precision is Sound AND Safety is Ethical THEN Execution is Optimal',
      weight: Math.min(cHigh, pSound, sEthical),
      fired: Math.min(cHigh, pSound, sEthical) > 0.15,
    },
    {
      id: 'R3',
      rule: 'IF Precision is Sound AND Safety is Sandboxed THEN Execution is Sandboxed',
      weight: Math.min(pSound, sSandbox),
      fired: Math.min(pSound, sSandbox) > 0.15,
    },
    {
      id: 'R4',
      rule: 'IF Intent is Moderate AND Precision is Optimal AND Safety is Sandboxed THEN Execution is Sandboxed',
      weight: Math.min(cMod, pOpt, sSandbox),
      fired: Math.min(cMod, pOpt, sSandbox) > 0.15,
    },
    {
      id: 'R5',
      rule: 'IF Safety is Hazardous OR Precision is Ambiguous THEN Interlock Required',
      weight: Math.max(sHazard, pAmb),
      fired: Math.max(sHazard, pAmb) > 0.2,
    },
    {
      id: 'R6',
      rule: 'IF Intent is Low AND Safety is Hazardous THEN Reject Execution',
      weight: Math.min(cLow, sHazard),
      fired: Math.min(cLow, sHazard) > 0.25,
    },
  ];

  // 3. Centroid Defuzzification:
  // Target output spaces:
  // Optimal: 95
  // Sandboxed: 75
  // Interlock: 40
  // Reject: 15
  let numerator = 0;
  let denominator = 0;

  // Discrete sampling from 0 to 100 with step of 2
  for (let z = 0; z <= 100; z += 2) {
    // Evaluate output membership for z:
    const muOptimal = triangular(z, 70, 95, 100);
    const muSandboxed = triangular(z, 50, 75, 90);
    const muInterlock = triangular(z, 20, 42, 65);
    const muReject = triangular(z, 0, 15, 35);

    // Rule aggregated strengths:
    const weightOpt = Math.max(rules[0].weight, rules[1].weight);
    const weightSand = Math.max(rules[2].weight, rules[3].weight);
    const weightInter = rules[4].weight;
    const weightRej = rules[5].weight;

    const aggregatedMu = Math.max(
      Math.min(muOptimal, weightOpt),
      Math.min(muSandboxed, weightSand),
      Math.min(muInterlock, weightInter),
      Math.min(muReject, weightRej),
      0.02 // baseline epsilon
    );

    numerator += z * aggregatedMu;
    denominator += aggregatedMu;
  }

  const centroid = denominator > 0 ? Math.round((numerator / denominator) * 10) / 10 : 85;

  let recommendation: 'EXECUTE_OPTIMAL' | 'EXECUTE_SANDBOXED' | 'SAFETY_INTERLOCK_REQUIRED' | 'REJECT';
  let explanation = '';

  if (centroid >= 78) {
    recommendation = 'EXECUTE_OPTIMAL';
    explanation = 'Full multi-LLM consensus verified. High semantic fidelity, accurate POSIX grammar, and strict ethical non-destructive boundaries.';
  } else if (centroid >= 55) {
    recommendation = 'EXECUTE_SANDBOXED';
    explanation = 'Moderate ambiguity or elevated system touch. Agent-Reach restricted to isolated userland sandbox container with non-persistent RAM overlay.';
  } else if (centroid >= 30) {
    recommendation = 'SAFETY_INTERLOCK_REQUIRED';
    explanation = 'Blast radius flags detected by Mistral-Nemo or ambiguous syntax parameters from Llama-3. Requires manual confirmation.';
  } else {
    recommendation = 'REJECT';
    explanation = 'Fuzzy defuzzification consensus failed safety threshold. Destructive or unsafe operation prevented by Ethical Guardrails.';
  }

  return {
    confidenceVar,
    precisionVar,
    safetyVar,
    rules,
    centroid,
    recommendation,
    explanation,
    deliberations,
  };
}
