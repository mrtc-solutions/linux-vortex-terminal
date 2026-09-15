/* Authorized remote-desktop window — a REAL remote graphical session.
   The live framebuffer is decoded by noVNC and the RFB bytes travel over a
   same-origin, ticket-bound WebSocket owned by the Python sidecar. The browser
   never dials the target itself.

   Deliberate design decisions:
   * credentials live in this component's memory only, are never persisted, and
     are cleared as soon as the handshake finishes;
   * the noVNC "clipboard" event is ignored and clipboardPasteFrom is never
     called, so clipboard synchronization stays off;
   * keyboard capture is explicit and reversible (Escape twice, or the release
     button), and a banner states that keystrokes are going to the remote device. */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  AlertTriangle, Keyboard, KeyRound, Loader2, Maximize2, Minimize2, PlugZap, ShieldAlert, Unplug, X,
} from 'lucide-react';
import RFB from '@novnc/novnc';
import {
  JsonRecord, closeRemoteSession, disconnectRemoteSession, getRemoteSession, noteRemoteActivity,
  remoteDesktopStreamPath, reconnectRemoteSession, requestRemoteTicket,
} from '../services/vortexApi';
import { GhostButton, PrimaryButton, asRecord, inputCls } from './popups/common';

export const NOVNC_CLIENT_VERSION = '1.7.0';
const TICKET_SUBPROTOCOL_PREFIX = 'vortex-ticket.';
const RFB_SUBPROTOCOL = 'vortex.rfb.v1';

export interface RemoteDesktopViewProps {
  session: JsonRecord;
  /** Latest sidecar record for this session (progress counters, state changes). */
  pulse?: JsonRecord;
  /** Window close keeps the session (operator opt-in) or ends it (default). */
  keepSessionOnClose: boolean;
  onSessionChange?: (session: JsonRecord) => void;
  onClosed?: (sessionId: string) => void;
}

type Phase = 'preparing' | 'connecting' | 'awaiting-credentials' | 'connected' | 'disconnected' | 'failed';

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value ? value : fallback;
}

const RemoteDesktopView: React.FC<RemoteDesktopViewProps> = ({
  session, pulse: pulseProp, keepSessionOnClose, onSessionChange, onClosed,
}) => {
  const sessionId = text(session.id);
  const target = useMemo(() => asRecord(session.target), [session.target]);
  const host = text(target.host, 'unknown target');
  const port = Number(target.port || 0);
  const unencrypted = session.transport === 'unencrypted';

  const containerRef = useRef<HTMLDivElement | null>(null);
  const rfbRef = useRef<RFB | null>(null);
  const passwordRef = useRef('');
  const generationRef = useRef(0);
  const capturedRef = useRef(false);
  const escapeTimerRef = useRef(0);
  /** Set when this window already told the sidecar to end the session, so the
      unmount cleanup never issues a second close/disconnect. */
  const detachedRef = useRef(false);
  const [phase, setPhase] = useState<Phase>('preparing');
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState('Preparing the authorized connection…');
  const [failure, setFailure] = useState('');
  const [captured, setCaptured] = useState(false);
  const [scale, setScale] = useState(true);
  const [resolution, setResolution] = useState('');
  const [desktopName, setDesktopName] = useState('');
  const [pulse, setPulse] = useState<JsonRecord>({});
  // The freshest sidecar record available: live poll first, then the record the
  // manager opened this window with.
  const record = pulse && text(pulse.id) === sessionId ? pulse : (pulseProp || session);

  const setCapture = useCallback((next: boolean, reason: string) => {
    if (capturedRef.current === next) return;
    capturedRef.current = next;
    setCaptured(next);
    setStatus(reason);
    // Only the fact that input focus moved is recorded; never the keys.
    void noteRemoteActivity(sessionId, next ? 'input_begin' : 'input_end').catch(() => undefined);
  }, [sessionId]);

  const teardown = useCallback(() => {
    generationRef.current += 1;
    const rfb = rfbRef.current;
    rfbRef.current = null;
    if (rfb) {
      try {
        rfb.disconnect();
      } catch {
        /* already closed */
      }
    }
    passwordRef.current = '';
  }, []);

  const readResolution = useCallback(() => {
    const canvas = containerRef.current?.querySelector('canvas');
    if (canvas && canvas.width && canvas.height) setResolution(`${canvas.width} × ${canvas.height}`);
  }, []);

  const attach = useCallback((rfb: RFB, generation: number) => {
    const live = () => generation === generationRef.current;
    rfb.addEventListener('connect', () => {
      if (!live()) return;
      passwordRef.current = '';
      setPassword('');
      setPhase('connected');
      setStatus('Live remote desktop. Click the surface to send keyboard and mouse input.');
      setCapture(false, 'Live remote desktop. Click the surface to send keyboard and mouse input.');
      window.requestAnimationFrame(readResolution);
    });
    rfb.addEventListener('disconnect', (event: Event) => {
      if (!live()) return;
      const clean = Boolean(asRecord((event as CustomEvent).detail).clean);
      setCapture(false, 'Connection closed.');
      setPhase(clean ? 'disconnected' : 'failed');
      if (!clean) setFailure('The remote desktop connection ended unexpectedly. Reconnect under the approved policy.');
      setStatus('The remote desktop is no longer connected.');
    });
    rfb.addEventListener('securityfailure', (event: Event) => {
      if (!live()) return;
      const detail = asRecord((event as CustomEvent).detail);
      const reason = text(detail.reason);
      setCapture(false, 'Authentication was refused by the remote desktop.');
      setPhase('failed');
      setFailure(
        `Authentication failed on the remote desktop${reason ? `: ${reason}` : ' (the server rejected the credentials)'}. `
        + 'Check the account, then re-approve the connection. Vortex never retries credentials on its own.',
      );
    });
    rfb.addEventListener('credentialsrequired', () => {
      if (!live()) return;
      setPhase('awaiting-credentials');
      setStatus('The remote desktop requires credentials. They stay in this window and are never stored.');
    });
    rfb.addEventListener('desktopname', (event: Event) => {
      if (!live()) return;
      setDesktopName(text(asRecord((event as CustomEvent).detail).name));
      window.requestAnimationFrame(readResolution);
    });
    // No clipboard listener and no clipboardPasteFrom() call: clipboard
    // synchronization stays off until it becomes an explicitly authorized feature.
  }, [readResolution, setCapture]);

  const connect = useCallback(async (reconnect: boolean) => {
    if (!sessionId) return;
    teardown();
    const generation = ++generationRef.current;
    setFailure('');
    setPhase('connecting');
    setStatus(reconnect ? 'Requesting a fresh connection ticket…' : 'Requesting a connection ticket…');
    try {
      if (reconnect) {
        const response = await reconnectRemoteSession(sessionId);
        if (generation !== generationRef.current) return;
        onSessionChange?.(asRecord(response.session));
      }
      const ticketResponse = await requestRemoteTicket(sessionId);
      if (generation !== generationRef.current) return;
      const ticket = text(asRecord(ticketResponse.ticket).ticket);
      if (!ticket) throw new Error('The sidecar did not issue a connection ticket.');
      const container = containerRef.current;
      if (!container) throw new Error('The remote desktop surface is not mounted.');
      setStatus('Opening the authenticated RFB stream…');
      const rfb = new RFB(container, remoteDesktopStreamPath(sessionId), {
        credentials: passwordRef.current ? { password: passwordRef.current } : {},
        wsProtocols: [RFB_SUBPROTOCOL, `${TICKET_SUBPROTOCOL_PREFIX}${ticket}`],
        shared: true,
      });
      rfb.background = '#050807';
      rfb.scaleViewport = true;
      rfb.clipViewport = false;
      rfb.resizeSession = false; // fixed resolution unless the operator asks the target to resize
      rfb.showDotCursor = true;
      rfbRef.current = rfb;
      attach(rfb, generation);
    } catch (err) {
      if (generation !== generationRef.current) return;
      setPhase('failed');
      setFailure(err instanceof Error ? err.message : String(err));
      setStatus('The authorized connection could not be opened.');
    }
  }, [attach, onSessionChange, sessionId, teardown]);

  useEffect(() => {
    void connect(false);
    return () => {
      teardown();
    };
    // The connection lifecycle is bound to this window instance only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // The sidecar record is the single source of truth for lifecycle state and
  // byte counters. Polling keeps this window honest if the reaper, STOP ALL, or
  // an engagement revocation ends the session behind our back.
  useEffect(() => {
    if (!sessionId) return undefined;
    let cancelled = false;
    const tick = async () => {
      try {
        const payload = await getRemoteSession(sessionId);
        const record = asRecord(payload.session);
        if (cancelled || !text(record.id)) return;
        setPulse(record);
        const state = text(record.state);
        if (state === 'closed' || state === 'disconnected' || state === 'failed') {
          teardown();
          setCapture(false, 'The sidecar ended this session.');
          setPhase(state === 'closed' ? 'disconnected' : 'failed');
          if (state !== 'closed') {
            setFailure(text(record.failure_reason, 'The session is no longer connected.'));
          }
        }
      } catch {
        /* the window keeps its last measured state; the banner explains failures */
      }
    };
    const timer = window.setInterval(() => void tick(), 10000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [sessionId, setCapture, teardown]);

  // Window close vs session disconnect is explicit and visible in the UI.
  useEffect(() => {
    if (!sessionId) return undefined;
    return () => {
      const closing = rfbRef.current;
      rfbRef.current = null;
      generationRef.current += 1;
      passwordRef.current = '';
      try {
        closing?.disconnect();
      } catch {
        /* already closed */
      }
      if (!detachedRef.current) {
        detachedRef.current = true;
        const request = keepSessionOnClose
          ? disconnectRemoteSession(sessionId, 'window_closed')
          : closeRemoteSession(sessionId, 'window_closed');
        void request.catch(() => undefined);
      }
      onClosed?.(sessionId);
    };
    // Session identity is fixed for the lifetime of this window.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);

  const sendCredentials = () => {
    const rfb = rfbRef.current;
    if (!rfb || !password) return;
    passwordRef.current = password;
    rfb.sendCredentials({ password });
    setPassword('');
    setPhase('connecting');
    setStatus('Credentials sent to the remote desktop for authentication…');
  };

  const releaseKeyboard = useCallback(() => {
    setCapture(false, 'Keyboard released — Vortex has control again.');
    try {
      rfbRef.current?.blur();
    } catch {
      /* nothing focused */
    }
  }, [setCapture]);

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    // Escape passes through to the remote application. Two Escapes in quick
    // succession hand the keyboard back to Vortex, so the operator always has a
    // deterministic way out without a mouse or a hidden shortcut.
    if (event.key === 'Escape' && capturedRef.current) {
      event.preventDefault();
      if (escapeTimerRef.current) {
        window.clearTimeout(escapeTimerRef.current);
        escapeTimerRef.current = 0;
        releaseKeyboard();
      } else {
        escapeTimerRef.current = window.setTimeout(() => { escapeTimerRef.current = 0; }, 800);
      }
      return;
    }
    if (capturedRef.current) event.stopPropagation(); // never leak shortcuts to the workbench
  };

  const disconnect = async () => {
    teardown();
    detachedRef.current = true;
    setCapture(false, 'Disconnected by the operator.');
    try {
      const response = await disconnectRemoteSession(sessionId, 'operator_disconnected');
      onSessionChange?.(asRecord(response.session));
      setPhase('disconnected');
      setStatus('Disconnected. The session stays listed so an approved reconnect can be requested.');
    } catch (err) {
      setFailure(err instanceof Error ? err.message : String(err));
    }
  };

  const closeSession = async () => {
    teardown();
    detachedRef.current = true;
    try {
      await closeRemoteSession(sessionId, 'operator_closed');
    } catch {
      /* the window is going away regardless */
    }
    onClosed?.(sessionId);
  };

  const toggleScale = () => {
    const rfb = rfbRef.current;
    const next = !scale;
    setScale(next);
    if (rfb) {
      rfb.scaleViewport = next;
      rfb.clipViewport = !next;
    }
  };

  const phaseLabel: Record<Phase, string> = {
    preparing: 'PREPARING',
    connecting: 'CONNECTING',
    'awaiting-credentials': 'AUTHENTICATION REQUIRED',
    connected: 'CONNECTED',
    disconnected: 'DISCONNECTED',
    failed: 'FAILED',
  };

  return (
    <div className="h-full flex flex-col font-mono" data-remote-desktop="vnc" data-key-capture={captured ? 'active' : 'inactive'}>
      <div className="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-[var(--theme-border)] bg-black/50 text-[11px]">
        <span className="px-1.5 py-0.5 rounded border border-cyan-800 bg-cyan-950/40 text-cyan-300 font-bold">GRAPHICAL</span>
        <span className="px-1.5 py-0.5 rounded border border-[var(--theme-border)] text-stone-300 font-bold">VNC / RFB</span>
        <span
          data-remote-phase={phase}
          className={`px-1.5 py-0.5 rounded border font-bold ${
            phase === 'connected'
              ? 'border-emerald-800 bg-emerald-950/40 text-emerald-300'
              : phase === 'failed'
                ? 'border-rose-800 bg-rose-950/40 text-rose-300'
                : 'border-amber-800 bg-amber-950/40 text-amber-300'
          }`}
        >
          {phaseLabel[phase]}
        </span>
        <span className="text-stone-400 truncate">
          {host}{port ? `:${port}` : ''}{desktopName ? ` · ${desktopName}` : ''}
        </span>
        <span className="flex-1" />
        <span className="text-stone-500">{resolution ? `${resolution}${scale ? ' · scaled' : ' · fixed'}` : 'resolution pending'}</span>
      </div>

      {unencrypted && (
        <div className="flex items-center gap-2 px-3 py-1.5 bg-amber-950/40 border-b border-amber-900/60 text-[11px] text-amber-200">
          <ShieldAlert className="w-3.5 h-3.5 shrink-0" />
          <span>
            UNENCRYPTED TRANSPORT approved for this session. Screen contents and input are not protected by TLS —
            route this desktop through an approved protected path (VPN/SSH tunnel) or use a TLS endpoint.
          </span>
        </div>
      )}

      {captured && (
        <div
          role="status"
          data-remote-input-warning="active"
          className="flex items-center gap-2 px-3 py-1.5 bg-rose-950/50 border-b border-rose-900/60 text-[11px] text-rose-200"
        >
          <Keyboard className="w-3.5 h-3.5 shrink-0" />
          <span className="flex-1">
            KEYBOARD CAPTURED — keystrokes and mouse events are being sent to {host}. Press Escape twice or use
            RELEASE KEYBOARD to return control to Vortex.
          </span>
          <button
            onClick={releaseKeyboard}
            className="px-2 py-0.5 rounded border border-rose-700 text-rose-100 hover:bg-rose-900/60 cursor-pointer font-bold"
          >
            RELEASE KEYBOARD
          </button>
        </div>
      )}

      {failure && (
        <div role="alert" className="flex items-start gap-2 px-3 py-2 bg-rose-950/30 border-b border-rose-900/50 text-[11px] text-rose-300">
          <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
          <span className="whitespace-pre-wrap">{failure}</span>
        </div>
      )}

      <div className="relative flex-1 min-h-0 bg-black/70">
        <div
          ref={containerRef}
          data-remote-surface="vnc"
          tabIndex={0}
          onKeyDown={onKeyDown}
          onBlur={(event: React.FocusEvent<HTMLDivElement>) => {
            // Focus leaving the surface means keystrokes are no longer going to
            // the remote device, so the warning banner must stop claiming they
            // are. Focus moving *inside* the surface (canvas/gesture layer) is
            // not a release.
            const next = event.relatedTarget as Node | null;
            if (capturedRef.current && (!next || !containerRef.current?.contains(next))) {
              setCapture(false, 'Keyboard released — the remote desktop surface no longer has focus.');
            }
          }}
          onClick={() => {
            if (phase !== 'connected') return;
            // noVNC listens on its own canvas, so hand it the keyboard focus as
            // part of the same explicit capture step the operator just triggered.
            try {
              rfbRef.current?.focus();
            } catch {
              /* the surface is gone; the banner text below still tells the truth */
            }
            setCapture(true, `Keyboard captured — input is going to ${host}.`);
          }}
          className="absolute inset-0 [&_canvas]:outline-none"
        />
        {phase !== 'connected' && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 bg-black/80 text-center px-6">
            <div className="flex items-center gap-2 text-[12px] text-stone-300">
              {(phase === 'connecting' || phase === 'preparing') && <Loader2 className="w-4 h-4 animate-spin" />}
              {phase === 'failed' && <AlertTriangle className="w-4 h-4 text-rose-400" />}
              {phase === 'disconnected' && <Unplug className="w-4 h-4 text-stone-400" />}
              <span>{status}</span>
            </div>
            <div className="text-[10px] text-stone-500 max-w-md">
              Vortex dials {host}{port ? `:${port}` : ''} from the sidecar after re-checking this engagement&apos;s authorization.
              No placeholder desktop is ever drawn: this surface only shows what a real RFB server sends.
            </div>
            {(phase === 'awaiting-credentials' || phase === 'failed' || phase === 'disconnected') && (
              <div className="flex flex-wrap items-center justify-center gap-2">
                <label className="flex items-center gap-1 text-[11px] text-stone-300">
                  <KeyRound className="w-3 h-3" />
                  <input
                    type="password"
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    onKeyDown={(event) => { if (event.key === 'Enter') sendCredentials(); }}
                    placeholder="Remote desktop password (memory only)"
                    aria-label="Remote desktop password"
                    autoComplete="off"
                    spellCheck={false}
                    className={`${inputCls} w-64`}
                  />
                </label>
                <PrimaryButton onClick={sendCredentials} disabled={!password}>SEND CREDENTIALS</PrimaryButton>
                <GhostButton onClick={() => void connect(true)}>
                  <span className="flex items-center gap-1"><PlugZap className="w-3 h-3" />RECONNECT</span>
                </GhostButton>
              </div>
            )}
          </div>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2 px-3 py-2 border-t border-[var(--theme-border)] bg-[var(--theme-surface)]/90 text-[11px]">
        <span className="text-stone-500">
          Target {host}{port ? `:${port}` : ''} · engagement {text(session.engagement_id, '?')} · {Number(record.bytes_in || 0)} B received / {Number(record.bytes_out || 0)} B sent
        </span>
        <span className="flex-1" />
        <GhostButton onClick={toggleScale} title="Scale the remote framebuffer to this window">
          {scale
            ? <span className="flex items-center gap-1"><Minimize2 className="w-3 h-3" />FIT</span>
            : <span className="flex items-center gap-1"><Maximize2 className="w-3 h-3" />SCALE</span>}
        </GhostButton>
        <GhostButton
          onClick={() => { try { rfbRef.current?.sendCtrlAltDel(); } catch { /* not connected */ } }}
          title="Send Ctrl+Alt+Del to the remote desktop"
        >
          CTRL+ALT+DEL
        </GhostButton>
        <GhostButton onClick={() => void disconnect()} disabled={phase === 'disconnected'}>
          <span className="flex items-center gap-1"><Unplug className="w-3 h-3" />DISCONNECT</span>
        </GhostButton>
        <PrimaryButton onClick={() => void closeSession()}>
          <span className="flex items-center gap-1"><X className="w-3 h-3" />CLOSE SESSION</span>
        </PrimaryButton>
        <span className="w-full text-[10px] text-stone-600">
          Window close {keepSessionOnClose ? 'keeps this session for an approved reconnect' : 'ends this session and its socket'}.
          Clipboard, file transfer, audio redirection, and shared folders stay disabled; no screen or keystroke recording is enabled.
        </span>
      </div>
    </div>
  );
};

export default RemoteDesktopView;
