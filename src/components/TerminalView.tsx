import React, { useState, useEffect, useRef } from 'react';
import { TerminalLine, FuzzyConsensusResult } from '../types/terminal';
import { orchestrateCommand } from '../services/multiLLMOrchestrator';
import { sound } from '../services/soundEffects';
import { vfs } from '../services/virtualFileSystem';
import { 
  Sparkles, 
  Copy, 
  Check, 
  Scale, 
  FolderDown, 
  CornerDownLeft,
  Zap
} from 'lucide-react';

interface TerminalViewProps {
  onInspectFuzzy: (consensus: FuzzyConsensusResult) => void;
  onNavigateToOut: () => void;
  onNavigateToMap: () => void;
  onNavigateToReport: () => void;
  externalCommand?: string | null;
  onClearExternalCommand?: () => void;
  onArtifactCountChange?: () => void;
}

const INITIAL_GREETING: TerminalLine[] = [
  {
    id: 'boot-1',
    timestamp: '09:00:01',
    type: 'system',
    content: `NEO-HEX KERNEL v6.12.9-spectre-rt (x86_64) - PREEMPT_DYNAMIC
Multi-LLM Autonomous Agentic Shell initialized.
Linked Cluster: DeepSeek-R1 (7B) | Llama-3.3 (8B) | Mistral-Nemo (12B)
Fuzzy Consensus Arbiter: Mamdani Inference with Centroid Defuzzification [ONLINE]
Virtual Filesystem: Root mounted. Persistent artifacts store at '/out'.`,
  },
  {
    id: 'boot-2',
    timestamp: '09:00:02',
    type: 'output',
    content: `Type any natural language instruction (e.g. "Scan subnet 192.168.1.0/24" or "Find SUID binaries")
Or use standard Linux commands (ls, cat, pwd, nmap, tshark, help, map, report, out).`,
  },
];

export const TerminalView: React.FC<TerminalViewProps> = ({
  onInspectFuzzy,
  onNavigateToOut,
  onNavigateToMap,
  onNavigateToReport,
  externalCommand,
  onClearExternalCommand,
  onArtifactCountChange,
}) => {
  const [history, setHistory] = useState<TerminalLine[]>(INITIAL_GREETING);
  const [inputValue, setInputValue] = useState('');
  const [commandHistory, setCommandHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState<number>(-1);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);

  const bottomRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // Auto scroll to bottom
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [history, isProcessing]);

  // Execute external command if passed via props (e.g. from tactical map or quick prompt)
  useEffect(() => {
    if (externalCommand) {
      handleRun(externalCommand);
      if (onClearExternalCommand) onClearExternalCommand();
    }
  }, [externalCommand]);

  const handleRun = (cmdToRun: string) => {
    const trimmed = cmdToRun.trim();
    if (!trimmed) return;

    sound.playExecute();
    const timeStr = new Date().toLocaleTimeString();

    // Add command to history array
    setCommandHistory((prev) => [...prev, trimmed]);
    setHistoryIndex(-1);

    if (trimmed === 'clear') {
      setHistory([]);
      setInputValue('');
      return;
    }

    if (trimmed === 'map') {
      onNavigateToMap();
      setInputValue('');
      return;
    }

    if (trimmed === 'out') {
      onNavigateToOut();
      setInputValue('');
      return;
    }

    if (trimmed === 'report') {
      onNavigateToReport();
      setInputValue('');
      return;
    }

    // Append user input line
    const inputLine: TerminalLine = {
      id: `input-${Date.now()}`,
      timestamp: timeStr,
      type: 'input',
      content: trimmed,
    };

    setHistory((prev) => [...prev, inputLine]);
    setInputValue('');
    setIsProcessing(true);

    // Simulate multi-LLM consensus delay for realistic AI deliberation
    setTimeout(() => {
      const result = orchestrateCommand(trimmed);
      setIsProcessing(false);

      const outputLine: TerminalLine = {
        id: `output-${Date.now()}`,
        timestamp: new Date().toLocaleTimeString(),
        type: result.meta.exitCode === 0 ? 'output' : 'error',
        content: result.executionOutput,
        rawCommand: trimmed,
        translatedCommand: result.translatedCommand,
        orchestration: result.fuzzyConsensus,
        tableData: result.tableData,
        meta: result.meta,
      };

      setHistory((prev) => [...prev, outputLine]);

      if (result.meta.fileArtifactCreated && onArtifactCountChange) {
        onArtifactCountChange();
      }

      if (result.meta.exitCode === 0) {
        sound.playSuccess();
      } else {
        sound.playAlert();
      }
    }, 450);
  };

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
        'help', 'clear', 'ls', 'cd', 'pwd', 'cat', 'touch', 'mkdir', 'tree',
        'whoami', 'uname', 'top', 'ifconfig', 'map', 'report', 'out', 'fuzzy', 'models',
        'Scan subnet 192.168.1.0/24',
        'Find SUID binaries with privilege escalation',
        'Extract failed SSH logins from auth.log',
        'Sniff traffic on interface eth0',
      ];

      const match = commandCandidates.find((c) =>
        c.toLowerCase().startsWith(currentToken.toLowerCase())
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
    navigator.clipboard.writeText(cmd);
    setCopiedId(id);
    sound.playKeypress();
    setTimeout(() => setCopiedId(null), 2000);
  };

  const currentPwd = vfs.getPwd();

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
                  ghost@spectre-box:{currentPwd}$
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

            {/* 3. Multi-LLM Orchestration Card (When Natural Language Translated) */}
            {line.orchestration && line.translatedCommand && line.translatedCommand !== line.rawCommand && (
              <div className="p-3 rounded bg-black/70 border border-[var(--theme-border)] box-glow space-y-2.5">
                {/* Consensus Header */}
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--theme-border)]/50 pb-2">
                  <div className="flex items-center space-x-2">
                    <Sparkles className="w-4 h-4 text-[var(--theme-primary)]" />
                    <span className="font-bold text-xs text-[var(--theme-primary)] glow-primary">
                      MULTI-LLM TRANSLATION CONSENSUS
                    </span>
                    <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-400 border border-emerald-800">
                      R1 (Reason) + L3.3 (Shell) + Nemo (Safety)
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

                {/* Translated POSIX Shell Command */}
                <div className="space-y-1">
                  <div className="text-[10px] text-stone-500 uppercase tracking-wider font-semibold">
                    Synthesized POSIX Shell Command:
                  </div>
                  <div className="flex items-center justify-between p-2 rounded bg-black/90 border border-[var(--theme-border)] text-emerald-300 font-mono text-xs">
                    <code className="break-all font-semibold select-text">
                      $ {line.translatedCommand}
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

                {/* Security Reach & Artifact Link */}
                <div className="flex flex-wrap items-center justify-between gap-2 text-[10px] text-stone-400 pt-1">
                  <div className="flex items-center space-x-2">
                    <span className="text-stone-500">Reach Clearance:</span>
                    <span className="text-emerald-400 font-semibold font-mono">
                      {line.meta?.reachLevel || 'USERLAND_SANDBOX'}
                    </span>
                    <span className="text-stone-600">&bull;</span>
                    <span>Execution: {line.meta?.executionTimeMs}ms</span>
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

            {/* 4. Formatted Table (If command produced tabular telemetry) */}
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
            <span>Deliberating local models (DeepSeek-R1 + Llama-3.3 + Mistral-Nemo)... Calculating Mamdani Fuzzy Centroid...</span>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Terminal Input Bar */}
      <div className="border-t border-[var(--theme-border)] bg-[var(--theme-surface)]/90 px-3 py-2 flex items-center space-x-2">
        <span className="text-[var(--theme-primary)] font-bold flex items-center gap-1 shrink-0 font-mono text-xs">
          <span>ghost@spectre-box:{currentPwd}$</span>
        </span>

        <input
          ref={inputRef}
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Translate natural language (e.g. 'Scan subnet 192.168.1.0/24') or type Linux commands..."
          className="flex-1 bg-transparent text-white font-mono text-xs placeholder-stone-600 focus:outline-none caret-[var(--theme-primary)]"
          autoFocus
          spellCheck={false}
        />

        <div className="flex items-center space-x-1 shrink-0">
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
