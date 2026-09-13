/* Vortex Terminal — REAL orchestration surface. Every run calls the loopback
   Python sidecar (plan -> Guardian -> execute -> observe). Nothing is staged. */
import React, { useState, useEffect, useRef } from 'react';
import { TerminalLine, FuzzyConsensusResult } from '../types/terminal';
import { sound } from '../services/soundEffects';
import {
  Sparkles,
  Copy,
  Check,
  Scale,
  FolderDown,
  CornerDownLeft,
  Zap,
  OctagonX,
} from 'lucide-react';
import {
  ApiError, JsonRecord, OperationDocument, TurnResult,
  getModels, getSystemHealth, stopAll,
} from '../services/vortexApi';
import { startTurn, watchOperation } from '../services/turnRunner';
import { setLastTurn } from '../services/lastTurnStore';
import { advisorySummary, guardianSummary, toFuzzyConsensus } from '../services/realFuzzyAdapter';

interface TerminalViewProps {
  onInspectFuzzy: (consensus: FuzzyConsensusResult) => void;
  onNavigateToOut: () => void;
  onNavigateToMap: () => void;
  onNavigateToReport: () => void;
  onOpenPopup: (kind: string, props?: JsonRecord) => void;
  externalCommand?: string | null;
  onClearExternalCommand?: () => void;
  onArtifactCountChange?: () => void;
}

const HELP_TEXT = `Vortex Terminal // REAL COMMANDS (sidecar-backed, nothing simulated)

  Just type what you want — \"check disk usage\", \"whoami\", \"list listening ports\".
  Vortex Terminal builds a typed plan, the Guardian reviews it, and low-risk plans run
  under your policy. Anything else opens an approval review first.

  Terminal:  clear, help, stop, retry   Stop = STOP ALL (kills running work)
  Shell:     shell                      Open a raw host PTY (no Guardian, your keys)
  Views:     map, out, report
  Popups:    tasks, scope, tools, models, system, history, memory, settings,
             launcher (start menu), aiops (advisory trace), about (app + downloads)`;

function shortCwd(cwd: string): string {
  const clean = cwd.replace(/\/+$/, '') || '/';
  const parts = clean.split('/');
  const base = parts[parts.length - 1] || '/';
  return base === '/' ? '/' : base;
}

function asRecord(value: unknown): JsonRecord {
  return (value && typeof value === 'object' ? value : {}) as JsonRecord;
}

function commandOutput(operation: OperationDocument): { text: string; exitCode: number; table?: { headers: string[]; rows: (string | number)[][] } } {
  const commands = Array.isArray(operation.commands) ? operation.commands as JsonRecord[] : [];
  const chunks: string[] = [];
  const rows: (string | number)[][] = [];
  let exitCode = 0;
  for (const command of commands) {
    const display = String(command.display || '');
    const code = Number(command.exit_code ?? 0);
    if (code !== 0) exitCode = code;
    const output = String(command.output ?? command.stdout ?? '');
    chunks.push(`$ ${display}  [exit ${Number.isNaN(code) ? '?' : code}]`);
    if (output.trim()) chunks.push(output.trimEnd().slice(0, 4000));
    rows.push([display.slice(0, 60), Number.isNaN(code) ? '?' : code, String(command.status || (code === 0 ? 'succeeded' : 'failed'))]);
  }
  const analysis = asRecord(operation.analysis);
  const fact = String(analysis.fact || '').trim();
  if (fact) chunks.push(`\n${fact.slice(0, 1200)}`);
  const digest = String(operation.output_digest || '');
  if (digest) chunks.push(`evidence sha256: ${digest.slice(0, 32)}…`);
  const artifacts = Array.isArray(operation.artifacts) ? operation.artifacts.length : 0;
  if (artifacts > 0) chunks.push(`artifacts: ${artifacts} (see /out)`);
  return {
    text: chunks.join('\n').slice(0, 8000) || `Operation ${String(operation.status || 'finished')} — no command output was retained.`,
    exitCode,
    table: rows.length > 0 ? { headers: ['Command', 'Exit', 'Status'], rows: rows.slice(0, 24) } : undefined,
  };
}

export const TerminalView: React.FC<TerminalViewProps> = ({
  onInspectFuzzy,
  onNavigateToOut,
  onNavigateToMap,
  onNavigateToReport,
  onOpenPopup,
  externalCommand,
  onClearExternalCommand,
  onArtifactCountChange,
}) => {
  const [history, setHistory] = useState<TerminalLine[]>([]);
  const [inputValue, setInputValue] = useState('');
  const [commandHistory, setCommandHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState<number>(-1);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [stage, setStage] = useState('');
  const [promptUser, setPromptUser] = useState('operator');
  const [promptCwd, setPromptCwd] = useState('~');
  const [connected, setConnected] = useState(false);

  const bottomRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const busyRef = useRef(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const appendLines = (lines: TerminalLine[]) => {
    setHistory((prev) => [...prev, ...lines].slice(-400));
  };

  // Boot: real sidecar handshake, then a greeting built from live facts.
  // Also reused by the `retry` command after a failed handshake.
  const boot = async (isRetry = false) => {
    appendLines([{
      id: `boot-${Date.now()}`, timestamp: new Date().toLocaleTimeString(),
      type: 'system',
      content: isRetry ? 'Vortex Terminal — retrying the sidecar handshake…' : 'Vortex Terminal — connecting to the local sidecar…',
    }]);
    try {
      const [healthPayload, modelsPayload] = await Promise.all([getSystemHealth(), getModels()]);
      if (!mountedRef.current) return;
        const health = asRecord(healthPayload.health);
        const host = asRecord(health.host);
        const uid = host.uid;
        const user = (uid && typeof uid === 'object' ? String((uid as JsonRecord).name || (uid as JsonRecord).user || '') : '') || 'operator';
        const distro = asRecord(host.distribution).pretty_name || host.kernel || '';
        const cwd = String(host.cwd || '');
        setPromptUser(user);
        if (cwd) setPromptCwd(shortCwd(cwd));
        const model = asRecord(modelsPayload.model);
        const fuzzy = asRecord(model.fuzzy);
        const providers = asRecord(model.providers);
        const states = ['llamafile', 'gguf', 'ollama']
          .map((name) => `${name}:${String(asRecord(providers[name]).state || 'unknown')}`)
          .join(' ');
        setConnected(true);
        appendLines([
          {
            id: `greet-1-${Date.now()}`, timestamp: new Date().toLocaleTimeString(), type: 'system',
            content: `Vortex Terminal v0.3.0 — live sidecar connected.\nHost: ${String(distro || 'this machine')} · ${String(host.architecture || '')}\nLocal AI routing: ${states} · winner: ${String(fuzzy.winner || 'deterministic')}\nGuardian: ARMED · Audit chain: ON · PTY: available via 'shell'.`,
          },
          {
            id: `greet-2-${Date.now()}`, timestamp: new Date().toLocaleTimeString(), type: 'output',
            content: `Type what you want (e.g. "check disk usage" or "whoami").\nLow-risk plans auto-run under your policy; everything else asks first.\nType 'help' for commands.`,
          },
        ]);
    } catch (err) {
      if (!mountedRef.current) return;
      appendLines([{
        id: `boot-fail-${Date.now()}`, timestamp: new Date().toLocaleTimeString(), type: 'error',
        content: `Sidecar unreachable: ${err instanceof Error ? err.message : String(err)}\nStart it with: ./vortex serve --bind-host 127.0.0.1 --bind-port 8765\nThen type 'retry' or reload.`,
      }]);
    }
  };

  useEffect(() => {
    void boot();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Auto scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [history, isProcessing]);

  const appendOperationLines = (operation: OperationDocument, rawCommand: string) => {
    const rendered = commandOutput(operation);
    appendLines([{
      id: `output-${Date.now()}-${Math.floor(Math.random() * 100000)}`,
      timestamp: new Date().toLocaleTimeString(),
      type: rendered.exitCode === 0 ? 'output' : 'error',
      content: rendered.text,
      rawCommand,
      tableData: rendered.table,
      meta: {
        modelName: `operation ${String(operation.status || 'finished')}`,
        executionTimeMs: 0,
        exitCode: rendered.exitCode,
        reachLevel: 'OBSERVED EVIDENCE',
      },
    }]);
    if (Array.isArray(operation.artifacts) && operation.artifacts.length > 0 && onArtifactCountChange) {
      onArtifactCountChange();
    }
    if (rendered.exitCode === 0) sound.playSuccess();
    else sound.playAlert();
  };

  const runRealTurn = async (trimmed: string) => {
    const started = Date.now();
    setStage('Planning with the sidecar…');
    let turn: TurnResult;
    try {
      turn = await startTurn(trimmed);
    } catch (err) {
      setIsProcessing(false);
      setStage('');
      const message = err instanceof ApiError && err.code === 'network'
        ? `Sidecar unreachable. Start it with: ./vortex serve --bind-host 127.0.0.1 --bind-port 8765`
        : (err instanceof Error ? err.message : String(err));
      appendLines([{
        id: `err-${Date.now()}`, timestamp: new Date().toLocaleTimeString(),
        type: 'error', content: message, rawCommand: trimmed,
      }]);
      sound.playAlert();
      return;
    }
    if (!mountedRef.current) return;
    setLastTurn(turn);
    const plan = asRecord(turn.plan);
    const guardian = asRecord(turn.guardian);
    const localAi = asRecord(turn.local_ai);
    const explanation = String(turn.explanation || '');
    const planCommands = Array.isArray(plan.commands) ? plan.commands as JsonRecord[] : [];
    const planCwd = String(plan.cwd || '');
    if (planCwd) setPromptCwd(shortCwd(planCwd));

    const translated = planCommands.length > 0
      ? planCommands.map((command) => `$ ${String(command.display || '')}`).join('\n')
      : '(no commands planned)';
    const consensus = toFuzzyConsensus({ plan, guardian, localAi, council: asRecord(turn.council), explanation });

    appendLines([{
      id: `plan-${Date.now()}`,
      timestamp: new Date().toLocaleTimeString(),
      type: 'output',
      content: `${explanation}\n${guardianSummary(guardian)}\n${advisorySummary(localAi)}`,
      rawCommand: trimmed,
      translatedCommand: translated,
      orchestration: consensus,
      tableData: planCommands.length > 0 ? {
        headers: ['Command', 'Adapter', 'Purpose'],
        rows: planCommands.slice(0, 12).map((command) => [
          String(command.display || '').slice(0, 60),
          String(command.adapter_id || ''),
          String(command.explanation || '').slice(0, 80),
        ]),
      } : undefined,
      meta: {
        modelName: `Guardian ${String(guardian.decision || 'review')} · ${String(localAi.provider || 'no-model')}`,
        executionTimeMs: Date.now() - started,
        exitCode: 0,
        reachLevel: `RISK_${String(guardian.risk || 'unknown').toUpperCase()}`,
      },
    }]);

    const operation = (turn.operation && typeof turn.operation === 'object'
      ? turn.operation as OperationDocument : null);
    const task = asRecord(turn.task);
    const waiting = String(task.state || '') === 'WAITING_FOR_APPROVAL'
      || (plan.approval_required === true && String(plan.status || '') === 'planned' && !operation);

    if (operation && operation.id) {
      setStage('Streaming real execution output…');
      try {
        const final = await watchOperation(String(operation.id), turn);
        if (!mountedRef.current) return;
        if (String(final.status) === 'awaiting_confirmation') {
          setIsProcessing(false);
          setStage('');
          appendLines([{
            id: `preflight-${Date.now()}`, timestamp: new Date().toLocaleTimeString(),
            type: 'warning',
            content: 'Operation paused at a mutation preflight — review opened. Confirm the mutation to continue, or leave it paused.',
            rawCommand: trimmed,
          }]);
          onOpenPopup('approvals', {
            plan: plan as JsonRecord, guardian,
            mutation: { operation: final as JsonRecord, approvalToken: String(plan.approval_token || '') },
            onApproved: (done: OperationDocument) => appendOperationLines(done, trimmed),
            onRejected: () => appendLines([{
              id: `rej-${Date.now()}`, timestamp: new Date().toLocaleTimeString(),
              type: 'warning', content: 'Plan rejected by operator. Nothing was executed.', rawCommand: trimmed,
            }]),
          });
          return;
        }
        appendOperationLines(final, trimmed);
      } catch (err) {
        appendLines([{
          id: `watch-${Date.now()}`, timestamp: new Date().toLocaleTimeString(),
          type: 'error', content: `Execution watch failed: ${err instanceof Error ? err.message : String(err)}`,
          rawCommand: trimmed,
        }]);
        sound.playAlert();
      }
      setIsProcessing(false);
      setStage('');
      return;
    }

    if (waiting && planCommands.length > 0) {
      setIsProcessing(false);
      setStage('');
      appendLines([{
        id: `wait-${Date.now()}`, timestamp: new Date().toLocaleTimeString(),
        type: 'warning', content: 'Guardian requires recorded approval — review opened. Approve to execute, or reject to discard.',
        rawCommand: trimmed,
      }]);
      onOpenPopup('approvals', {
        plan: plan as JsonRecord, guardian,
        onApproved: (final: OperationDocument) => appendOperationLines(final, trimmed),
        onRejected: () => appendLines([{
          id: `rej-${Date.now()}`, timestamp: new Date().toLocaleTimeString(),
          type: 'warning', content: 'Plan rejected by operator. Nothing was executed.', rawCommand: trimmed,
        }]),
      });
      return;
    }

    setIsProcessing(false);
    setStage('');
    if (guardian.blocked === true) sound.playAlert();
    else sound.playSuccess();
  };

  const handleRun = (cmdToRun: string) => {
    const trimmed = cmdToRun.trim();
    if (!trimmed) return;
    const timeStr = new Date().toLocaleTimeString();

    setCommandHistory((prev) => [...prev, trimmed].slice(-200));
    setHistoryIndex(-1);

    if (trimmed === 'clear') {
      setHistory([]);
      setInputValue('');
      return;
    }
    if (trimmed === 'map') { onNavigateToMap(); setInputValue(''); return; }
    if (trimmed === 'out') { onNavigateToOut(); setInputValue(''); return; }
    if (trimmed === 'report') { onNavigateToReport(); setInputValue(''); return; }
    if (trimmed === 'help') {
      appendLines([
        { id: `input-${Date.now()}`, timestamp: timeStr, type: 'input', content: trimmed },
        { id: `help-${Date.now()}`, timestamp: timeStr, type: 'output', content: HELP_TEXT },
      ]);
      setInputValue('');
      return;
    }
    if (trimmed === 'shell') {
      appendLines([{ id: `input-${Date.now()}`, timestamp: timeStr, type: 'input', content: trimmed }]);
      onOpenPopup('shell', {});
      setInputValue('');
      return;
    }
    if (trimmed === 'retry') {
      appendLines([{ id: `input-${Date.now()}`, timestamp: timeStr, type: 'input', content: trimmed }]);
      setConnected(false);
      void boot(true);
      setInputValue('');
      return;
    }
    if (trimmed === 'stop') {
      appendLines([{ id: `input-${Date.now()}`, timestamp: timeStr, type: 'input', content: trimmed }]);
      void stopAll()
        .then(() => appendLines([{ id: `stop-${Date.now()}`, timestamp: new Date().toLocaleTimeString(), type: 'warning', content: 'STOP ALL sent — running operations and sessions were signalled.' }]))
        .catch((err: unknown) => appendLines([{ id: `stop-${Date.now()}`, timestamp: new Date().toLocaleTimeString(), type: 'error', content: err instanceof Error ? err.message : String(err) }]));
      setInputValue('');
      return;
    }
    for (const popup of ['tasks', 'scope', 'tools', 'models', 'system', 'history', 'memory', 'settings', 'launcher', 'aiops', 'about']) {
      if (trimmed === popup) {
        appendLines([{ id: `input-${Date.now()}`, timestamp: timeStr, type: 'input', content: trimmed }]);
        onOpenPopup(popup, {});
        setInputValue('');
        return;
      }
    }

    if (busyRef.current) {
      appendLines([{
        id: `busy-${Date.now()}`, timestamp: timeStr, type: 'warning',
        content: 'A turn is already running. Wait for it to finish, or type "stop".',
      }]);
      return;
    }

    sound.playExecute();
    appendLines([{ id: `input-${Date.now()}`, timestamp: timeStr, type: 'input', content: trimmed }]);
    setInputValue('');
    setIsProcessing(true);
    busyRef.current = true;
    void runRealTurn(trimmed).finally(() => {
      busyRef.current = false;
      if (mountedRef.current) {
        setIsProcessing(false);
        setStage('');
      }
    });
  };

  // Execute external command if passed via props (e.g. from tactical map or quick prompt)
  useEffect(() => {
    if (externalCommand) {
      handleRun(externalCommand);
      if (onClearExternalCommand) onClearExternalCommand();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalCommand]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    sound.playKeypress();

    // History navigation with Up/Down arrows
    if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (commandHistory.length > 0) {
        const nextIndex = historyIndex === -1 ? commandHistory.length - 1 : Math.max(0, historyIndex - 1);
        setHistoryIndex(nextIndex);
        setInputValue(commandHistory[nextIndex] || '');
      }
      return;
    }

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (historyIndex !== -1) {
        const nextIndex = historyIndex + 1;
        if (nextIndex < commandHistory.length) {
          setHistoryIndex(nextIndex);
          setInputValue(commandHistory[nextIndex]);
        } else {
          setHistoryIndex(-1);
          setInputValue('');
        }
      }
      return;
    }

    // Tab Autocompletion
    if (e.key === 'Tab') {
      e.preventDefault();
      const tokens = inputValue.split(' ');
      const currentToken = tokens[tokens.length - 1];

      const commandCandidates = [
        'help', 'clear', 'stop', 'shell', 'map', 'report', 'out',
        'tasks', 'scope', 'tools', 'models', 'system', 'history', 'memory', 'settings', 'launcher', 'retry', 'aiops', 'about',
        'whoami', 'check disk usage', 'list listening ports', 'show system health',
      ];

      const match = commandCandidates.find((c) =>
        c.toLowerCase().startsWith(currentToken.toLowerCase()),
      );

      if (match) {
        tokens[tokens.length - 1] = match;
        setInputValue(tokens.join(' '));
      }
      return;
    }

    // Ctrl+L to clear screen
    if (e.ctrlKey && e.key.toLowerCase() === 'l') {
      e.preventDefault();
      setHistory([]);
      return;
    }

    // Enter to submit
    if (e.key === 'Enter') {
      e.preventDefault();
      handleRun(inputValue);
    }
  };

  const handleCopyCommand = (cmd: string, id: string) => {
    try {
      void navigator.clipboard?.writeText(cmd).catch(() => {
        /* clipboard unavailable */
      });
    } catch {
      /* clipboard unavailable */
    }
    setCopiedId(id);
    sound.playKeypress();
    setTimeout(() => setCopiedId(null), 2000);
  };

  const handleStopAll = () => {
    sound.playAlert();
    void stopAll()
      .then(() => appendLines([{ id: `stop-${Date.now()}`, timestamp: new Date().toLocaleTimeString(), type: 'warning', content: 'STOP ALL sent — running operations and sessions were signalled.' }]))
      .catch((err: unknown) => appendLines([{ id: `stop-${Date.now()}`, timestamp: new Date().toLocaleTimeString(), type: 'error', content: err instanceof Error ? err.message : String(err) }]));
  };

  return (
    <div
      className="flex-1 flex flex-col h-full bg-[var(--theme-bg)] font-mono text-xs overflow-hidden select-text relative"
      onClick={() => inputRef.current?.focus()}
    >
      {/* Terminal Output Area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3.5 select-text">
        {history.map((line) => (
          <div key={line.id} className="space-y-2">
            {/* 1. Input Line */}
            {line.type === 'input' && (
              <div className="flex items-center space-x-2 text-stone-200">
                <span className="text-[var(--theme-dim)] font-bold">
                  {promptUser}@vortex:{promptCwd}$
                </span>
                <span className="font-semibold text-white">{line.content}</span>
              </div>
            )}

            {/* 2. System Banner Line */}
            {line.type === 'system' && (
              <div className="p-3 rounded bg-black/60 border border-[var(--theme-border)] text-[var(--theme-primary)] box-glow leading-relaxed whitespace-pre-wrap">
                {line.content}
              </div>
            )}

            {/* 3. Plan / Guardian Consensus Card */}
            {line.orchestration && line.translatedCommand && line.translatedCommand !== line.rawCommand && (
              <div className="p-3 rounded bg-black/70 border border-[var(--theme-border)] box-glow space-y-2.5">
                {/* Consensus Header */}
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--theme-border)]/50 pb-2">
                  <div className="flex items-center space-x-2">
                    <Sparkles className="w-4 h-4 text-[var(--theme-primary)]" />
                    <span className="font-bold text-xs text-[var(--theme-primary)] glow-primary">
                      PLAN + GUARDIAN CONSENSUS
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800">
                      {line.meta?.modelName || 'sidecar'}
                    </span>
                  </div>

                  <div className="flex items-center space-x-2">
                    <span className="text-[11px] text-stone-400">
                      Fuzzy Defuzzified Centroid:
                    </span>
                    <span className="text-xs font-black text-[var(--theme-primary)] glow-primary">
                      {line.orchestration.centroid.toFixed(1)}%
                    </span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        sound.playFuzzyArbiter();
                        onInspectFuzzy(line.orchestration!);
                      }}
                      className="flex items-center space-x-1 px-2 py-0.5 rounded bg-black/50 border border-[var(--theme-border)] text-stone-300 hover:text-[var(--theme-primary)] transition-colors cursor-pointer text-[10px]"
                    >
                      <Scale className="w-3 h-3 text-[var(--theme-primary)]" />
                      <span>Inspect Fuzzy Math</span>
                    </button>
                  </div>
                </div>

                {/* Typed Shell Commands */}
                <div className="space-y-1">
                  <div className="text-[10px] text-stone-500 uppercase tracking-wider font-semibold">
                    Typed Plan Commands:
                  </div>
                  <div className="flex items-start justify-between p-2 rounded bg-black/90 border border-[var(--theme-border)] text-emerald-300 font-mono text-xs">
                    <code className="break-all font-semibold select-text whitespace-pre-wrap">
                      {line.translatedCommand}
                    </code>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleCopyCommand(line.translatedCommand!, line.id);
                      }}
                      className="p-1 rounded text-stone-400 hover:text-white cursor-pointer ml-2 shrink-0"
                      title="Copy command"
                    >
                      {copiedId === line.id ? (
                        <Check className="w-3.5 h-3.5 text-emerald-400" />
                      ) : (
                        <Copy className="w-3.5 h-3.5" />
                      )}
                    </button>
                  </div>
                </div>

                {/* Risk & Timing */}
                <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-stone-400 pt-1">
                  <div className="flex items-center space-x-2">
                    <span className="text-stone-500">Guardian:</span>
                    <span className="text-emerald-400 font-semibold font-mono">
                      {line.meta?.reachLevel || 'REVIEW'}
                    </span>
                    <span className="text-stone-600">&bull;</span>
                    <span>Plan: {line.meta?.executionTimeMs}ms</span>
                  </div>

                  {line.meta?.fileArtifactCreated && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onNavigateToOut();
                      }}
                      className="flex items-center space-x-1 text-[var(--theme-primary)] hover:underline cursor-pointer"
                    >
                      <FolderDown className="w-3 h-3" />
                      <span>Saved in /out: {line.meta.fileArtifactCreated}</span>
                    </button>
                  )}
                </div>
              </div>
            )}

            {/* 4. Formatted Table (real command telemetry) */}
            {line.tableData && (
              <div className="border border-[var(--theme-border)] rounded overflow-x-auto bg-black/40 my-2">
                <table className="w-full text-left text-[11px] font-mono">
                  <thead className="bg-black/80 text-[var(--theme-primary)] border-b border-[var(--theme-border)]">
                    <tr>
                      {line.tableData.headers.map((h, idx) => (
                        <th key={idx} className="p-2 font-bold whitespace-nowrap">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--theme-border)]/40">
                    {line.tableData.rows.map((row, rIdx) => (
                      <tr key={rIdx} className="hover:bg-white/5">
                        {row.map((cell, cIdx) => (
                          <td key={cIdx} className="p-2 text-stone-300 whitespace-nowrap">
                            {String(cell)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {/* 5. Standard Output / Execution Result */}
            {line.content && line.type !== 'system' && (
              <div
                className={`whitespace-pre-wrap leading-relaxed select-text font-mono ${
                  line.type === 'error'
                    ? 'text-rose-400 bg-rose-950/20 p-2.5 rounded border border-rose-900/40'
                    : line.type === 'warning'
                      ? 'text-amber-300 bg-amber-950/20 p-2.5 rounded border border-amber-900/40'
                      : line.type === 'success'
                        ? 'text-emerald-300'
                        : 'text-stone-300'
                }`}
              >
                {line.content}
              </div>
            )}
          </div>
        ))}

        {/* Live Processing Indicator */}
        {isProcessing && (
          <div className="flex items-center space-x-2 text-stone-400 font-mono text-xs p-2 rounded bg-black/40 border border-[var(--theme-border)] animate-pulse">
            <Zap className="w-4 h-4 text-[var(--theme-primary)] animate-spin" />
            <span>{stage || 'Working with the sidecar…'} {connected ? '' : '(connecting)'}</span>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Terminal Input Bar */}
      <div className="border-t border-[var(--theme-border)] bg-[var(--theme-surface)]/90 px-3 py-2 flex items-center space-x-2">
        <span className="text-[var(--theme-primary)] font-bold flex items-center gap-1 shrink-0 font-mono text-xs">
          <span className="w-1.5 h-1.5 rounded-full inline-block" style={{ backgroundColor: connected ? 'var(--theme-primary)' : '#525252' }} title={connected ? 'Sidecar connected' : 'Sidecar unreachable'} />
          <span>{promptUser}@vortex:{promptCwd}$</span>
        </span>

        <input
          ref={inputRef}
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask Vortex Terminal anything (e.g. 'check disk usage') or type 'help'..."
          className="flex-1 bg-transparent text-white font-mono text-xs placeholder-stone-600 focus:outline-none caret-[var(--theme-primary)]"
          autoFocus
          spellCheck={false}
        />

        <div className="flex items-center space-x-1 shrink-0">
          <button
            onClick={handleStopAll}
            className="flex items-center space-x-1 px-2 py-1 rounded border border-rose-900/60 text-rose-300 font-semibold text-xs hover:bg-rose-950/40 transition-colors cursor-pointer"
            title="STOP ALL running work"
          >
            <OctagonX className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Stop</span>
          </button>
          <button
            onClick={() => handleRun(inputValue)}
            disabled={!inputValue.trim()}
            className="flex items-center space-x-1 px-2.5 py-1 rounded bg-[var(--theme-primary)] text-black font-semibold text-xs hover:opacity-90 disabled:opacity-40 transition-opacity cursor-pointer"
            title="Execute (Enter)"
          >
            <span>Run</span>
            <CornerDownLeft className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
};
