/* Raw host shell popup — a REAL Linux PTY owned by the Python sidecar.
   Keys go to the host shell; AI plans stay Guardian-gated and separate. */
import React, { useEffect, useRef, useState } from 'react';
import { TerminalSquare, PlugZap, Unplug, Loader2 } from 'lucide-react';
import {
  JsonRecord, killSession, listSessions, openSession, sendSessionInput, streamSession, StreamHandle,
} from '../../services/vortexApi';
import { sound } from '../../services/soundEffects';

const MAX_BUFFER = 200 * 1024;
/* eslint-disable-next-line no-control-regex */
const ANSI_PATTERN = /\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07|\x1b[()][0-9A-B]|\x1b[>=M78]|\r/g;

function stripAnsi(text: string): string {
  return text.replace(ANSI_PATTERN, '');
}

export const Shell: React.FC = () => {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [status, setStatus] = useState('connecting');
  const [buffer, setBuffer] = useState('');
  const [input, setInput] = useState('');
  const [error, setError] = useState('');
  const streamRef = useRef<StreamHandle | null>(null);
  const sessionIdRef = useRef<string | null>(null);
  const startedRef = useRef(false);
  const bottomRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const seqRef = useRef(0);

  const appendData = (data: string) => {
    if (!data) return;
    const clean = stripAnsi(data);
    if (!clean) return;
    setBuffer((prev) => {
      const next = prev + clean;
      return next.length > MAX_BUFFER ? next.slice(next.length - MAX_BUFFER) : next;
    });
  };

  const attach = (id: string) => {
    streamRef.current?.close();
    const handle = streamSession(
      id,
      (payload) => {
        const events = Array.isArray(payload.events) ? payload.events as JsonRecord[] : [];
        for (const event of events) {
          const seq = Number(event.seq || 0);
          if (seq > seqRef.current) {
            seqRef.current = seq;
            if (typeof event.data === 'string') appendData(event.data);
          }
        }
        const session = (payload.session || {}) as JsonRecord;
        if (typeof session.status === 'string') setStatus(session.status);
      },
      () => setStatus((prev) => (prev === 'running' ? 'stream-interrupted' : prev)),
    );
    streamRef.current = handle;
  };

  const connect = async () => {
    setError('');
    setStatus('connecting');
    sound.playExecute();
    try {
      const existing = await listSessions().catch(() => null);
      const sessions = (existing && Array.isArray((existing as JsonRecord).sessions)
        ? (existing as JsonRecord).sessions as JsonRecord[] : [])
        .filter((item) => item.status === 'running' || !item.status);
      const mine = sessionId ? sessions.find((item) => item.id === sessionId) : undefined;
      const target = mine || sessions[0];
      if (target && typeof target.id === 'string') {
        sessionIdRef.current = target.id as string;
        setSessionId(target.id as string);
        setStatus('running');
        attach(target.id as string);
        return;
      }
      const created = await openSession();
      const session = (created.session || {}) as JsonRecord;
      const id = String(session.id || '');
      if (!id) throw new Error('Sidecar did not return a session.');
      sessionIdRef.current = id;
      setSessionId(id);
      setStatus('running');
      attach(id);
    } catch (err) {
      sound.playAlert();
      setError(err instanceof Error ? err.message : String(err));
      setStatus('failed');
    }
  };

  const disconnect = async () => {
    streamRef.current?.close();
    streamRef.current = null;
    if (sessionId) {
      try {
        await killSession(sessionId);
      } catch {
        /* already gone — honest either way */
      }
    }
    setSessionId(null);
    setStatus('closed');
    sound.playKeypress();
  };

  useEffect(() => {
    if (startedRef.current) return;
    startedRef.current = true;
    void connect();
    return () => {
      streamRef.current?.close();
      streamRef.current = null;
      /* Popup closed: kill the sidecar session so no orphan shell survives. */
      const id = sessionIdRef.current;
      sessionIdRef.current = null;
      if (id) void killSession(id).catch(() => undefined);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'auto' });
  }, [buffer]);

  const send = async () => {
    if (!sessionId || status !== 'running') return;
    const data = `${input}\n`;
    setInput('');
    try {
      await sendSessionInput(sessionId, data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  return (
    <div className="h-full flex flex-col font-mono" onClick={() => inputRef.current?.focus()}>
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--theme-border)] bg-black/40 text-[11px]">
        <TerminalSquare className="w-3.5 h-3.5 text-[var(--theme-primary)]" />
        <span className={status === 'running' ? 'text-emerald-400' : 'text-stone-500'}>
          {status === 'running' ? '● LIVE PTY' : status.toUpperCase().replace('-', ' ')}
        </span>
        {sessionId && <span className="text-stone-600 truncate">id {sessionId.slice(0, 8)}</span>}
        <span className="flex-1" />
        {status === 'running' ? (
          <button
            onClick={disconnect}
            className="flex items-center gap-1 px-2 py-0.5 rounded border border-rose-900/60 text-rose-300 hover:bg-rose-950/40 cursor-pointer"
          >
            <Unplug className="w-3 h-3" />
            <span>STOP</span>
          </button>
        ) : (
          <button
            onClick={connect}
            className="flex items-center gap-1 px-2 py-0.5 rounded bg-[var(--theme-primary)] text-black font-bold hover:opacity-90 cursor-pointer"
          >
            {status === 'connecting' ? <Loader2 className="w-3 h-3 animate-spin" /> : <PlugZap className="w-3 h-3" />}
            <span>{status === 'connecting' ? 'OPENING…' : 'RECONNECT'}</span>
          </button>
        )}
      </div>

      <div className="flex-1 overflow-y-auto p-3 bg-black/60 text-[12px] leading-relaxed select-text">
        {buffer ? (
          <pre className="whitespace-pre-wrap break-all text-stone-200">{buffer}</pre>
        ) : (
          <div className="text-stone-600">
            {status === 'connecting' ? 'Opening a real shell on this host…' : 'No output yet. Type below and press Enter.'}
          </div>
        )}
        {error && <div className="text-rose-400 mt-2 whitespace-pre-wrap">{error}</div>}
        <div ref={bottomRef} />
      </div>

      <div className="border-t border-[var(--theme-border)] bg-[var(--theme-surface)]/90 px-3 py-2 flex items-center gap-2">
        <span className="text-[var(--theme-primary)] font-bold text-xs shrink-0">$</span>
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault();
              void send();
            }
          }}
          placeholder={status === 'running' ? 'Type into the live host shell…' : 'Shell is not connected.'}
          disabled={status !== 'running'}
          spellCheck={false}
          autoComplete="off"
          className="flex-1 bg-transparent text-white text-xs placeholder-stone-600 focus:outline-none caret-[var(--theme-primary)]"
        />
      </div>
    </div>
  );
};
