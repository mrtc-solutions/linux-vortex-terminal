/* Tiny in-memory snapshot of the most recent terminal turn, so the AI Ops
   popup can show the real advisory trace. Never persisted, never fabricated:
   empty until a real turn completes. */
import { TurnResult } from './vortexApi';

let lastTurn: TurnResult | null = null;
let lastAt = '';

export function setLastTurn(turn: TurnResult): void {
  lastTurn = turn;
  lastAt = new Date().toLocaleTimeString();
}

export function getLastTurn(): { turn: TurnResult | null; at: string } {
  return { turn: lastTurn, at: lastAt };
}
