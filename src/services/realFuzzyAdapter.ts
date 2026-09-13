/* Honest bridge: real sidecar turn data -> FuzzyConsensusResult for display.
   The Mamdani/centroid MATH is the existing engine; every INPUT below comes
   from the live turn (plan status, Guardian verdict, real model responses).
   Nothing here invents deliberation text or scores. */
import { FuzzyConsensusResult } from '../types/terminal';
import { evaluateFuzzyConsensus } from './fuzzyLogicEngine';
import { JsonRecord } from './vortexApi';

function asRecord(value: unknown): JsonRecord {
  return (value && typeof value === 'object' ? value : {}) as JsonRecord;
}

function asList(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.filter((v): v is JsonRecord => !!v && typeof v === 'object') : [];
}

function clampScore(value: number): number {
  if (Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(100, Math.round(value)));
}

/** Reasoning score from the REAL advisory outcome (never guessed). */
function reasoningScore(localAi: JsonRecord): number {
  const fuzzy = asRecord(localAi.fuzzy);
  const responded = Number(fuzzy.models_responded ?? 0);
  if (!Number.isNaN(responded) && responded > 0) return 92;
  if (asRecord(localAi.fallback).used === true) return 58;
  if (asList(localAi.agents).some((agent) => String(agent.state || '') === 'installed')) return 45;
  return 22;
}

/** Precision score from the REAL plan shape. */
function precisionScore(plan: JsonRecord): number {
  const status = String(plan.status || '');
  const commands = asList(plan.commands);
  if (status === 'planned' && commands.length > 0) return 90;
  if (status === 'clarified') return 62;
  if (status === 'started') return 90;
  return 20;
}

/** Safety score from the REAL Guardian verdict. */
function safetyScore(guardian: JsonRecord): number {
  if (guardian.blocked === true) return 8;
  const risk = String(guardian.risk || 'unknown');
  if (risk === 'low') return 92;
  if (risk === 'medium') return 66;
  if (risk === 'high') return 35;
  return 50;
}

export interface FuzzyInput {
  plan: JsonRecord;
  guardian: JsonRecord;
  localAi: JsonRecord;
  council: JsonRecord;
  explanation: string;
}

/** Deliberation rows from REAL agent-council consultations, REAL model
 *  responses, or REAL installed-agent advisories — in that order of proof. */
function realDeliberations(input: FuzzyInput): FuzzyConsensusResult['deliberations'] {
  const consultations = asList(input.council.consultations);
  if (consultations.length > 0) {
    return consultations.slice(0, 3).map((item) => {
      const agent = String(item.agent || 'agent');
      const message = String(item.message || item.result || 'Consulted; no message text was retained.');
      const state = String(item.state || '');
      return {
        modelId: `council:${agent}`.slice(0, 80),
        modelName: `agent-council / ${agent}`.slice(0, 80),
        thought: message.slice(0, 500),
        rawOutput: `state=${state}`.slice(0, 200),
        confidence: state === 'responded' ? 72 : 30,
      };
    });
  }
  const responses = asList(input.localAi.responses);
  if (responses.length > 0) {
    return responses.slice(0, 3).map((item, index) => {
      const provider = String(item.provider || 'local');
      const model = String(item.model || provider);
      const thought = String(item.fact_summary || item.meaning || item.unknowns || item.error || 'No summary returned.');
      const raw = String(item.fact_summary || item.meaning || item.error || '');
      return {
        modelId: `${provider}:${model}`.slice(0, 80),
        modelName: `${provider} / ${model}`.slice(0, 80),
        thought: thought.slice(0, 500),
        rawOutput: (raw || thought).slice(0, 500),
        confidence: item.state === 'responded' ? 88 - index * 4 : 25,
      };
    });
  }
  const agents = asList(input.localAi.agents);
  if (agents.length > 0) {
    return agents.slice(0, 3).map((agent) => {
      const name = String(agent.name || agent.id || 'agent');
      const contribution = String(agent.contribution || 'Installed advisory agent; no model-backed output was produced.');
      return {
        modelId: `agent:${String(agent.id || name)}`.slice(0, 80),
        modelName: name.slice(0, 80),
        thought: contribution.slice(0, 500),
        rawOutput: `state=${String(agent.state || '')} availability=${String(agent.availability || '')}`.slice(0, 200),
        confidence: agent.healthy === true ? 55 : 25,
      };
    });
  }
  return [{
    modelId: 'deterministic-core',
    modelName: `Vortex Terminal deterministic core (${String(input.localAi.provider || 'no-model')})`,
    thought: String(input.localAi.message || input.explanation || 'No local model responded; planning continued deterministically.').slice(0, 500),
    rawOutput: `fallback_used=${String(asRecord(input.localAi.fallback).used !== false)}`.slice(0, 200),
    confidence: 50,
  }];
}

export function toFuzzyConsensus(input: FuzzyInput): FuzzyConsensusResult {
  const deliberations = realDeliberations(input);

  return evaluateFuzzyConsensus(
    reasoningScore(input.localAi),
    precisionScore(input.plan),
    safetyScore(input.guardian),
    deliberations,
  );
}

/** One-line honest summary of the advisory layer for the terminal. */
export function advisorySummary(localAi: JsonRecord): string {
  const provider = String(localAi.provider || 'none');
  const state = String(localAi.state || 'unavailable');
  const message = String(localAi.message || '').trim();
  const head = `Local AI: ${provider} [${state}]`;
  return message ? `${head} — ${message.slice(0, 280)}` : head;
}

export function guardianSummary(guardian: JsonRecord): string {
  const decision = String(guardian.decision || 'unknown');
  const risk = String(guardian.risk || 'unknown');
  const reasons = Array.isArray(guardian.reasons) ? guardian.reasons.map(String).slice(0, 3) : [];
  const head = `Guardian: ${decision.toUpperCase()} (risk: ${risk})`;
  return reasons.length > 0 ? `${head} — ${reasons.join('; ').slice(0, 300)}` : head;
}

export { clampScore, asRecord, asList };
