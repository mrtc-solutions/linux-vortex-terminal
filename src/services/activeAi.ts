/* Active AI tracker: which provider/model actually answered the most
 * recent turn (never a guess). TerminalView publishes after each real
 * response; the header badge subscribes so the operator always knows
 * whether an answer came from LOCAL (Qwen via Ollama) or CLOUD
 * (Gemini #1/#2/#3, Groq, OpenRouter, …). */

export interface ActiveAi {
  provider: string;       // e.g. "ollama-local", "gemini-1", "groq"
  providerName: string;   // e.g. "Local Ollama (Qwen 2.5 3B)", "Gemini #1"
  model: string;          // e.g. "qwen2.5:3b", "gemini-2.5-flash"
  mode: 'local' | 'cloud' | '';
  free: boolean | null;
  fallbackNote: string;   // e.g. "Local Qwen unavailable → Using Gemini #1"
}

let current: ActiveAi | null = null;
const listeners = new Set<(ai: ActiveAi | null) => void>();

export function setActiveAi(ai: ActiveAi | null): void {
  current = ai;
  listeners.forEach((listener) => {
    try { listener(current); } catch { /* subscriber errors never break turns */ }
  });
}

export function activeAi(): ActiveAi | null {
  return current;
}

export function onActiveAiChange(listener: (ai: ActiveAi | null) => void): () => void {
  listeners.add(listener);
  listener(current);
  return () => listeners.delete(listener);
}
