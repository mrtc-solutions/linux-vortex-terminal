/* Remote Sessions — the operator surface for authorized remote desktops.
   Everything here talks to the REAL sidecar: engagements, endpoint probes,
   session records, approvals, and the STOP ALL control. Nothing is staged:
   an unavailable endpoint is reported as unavailable, and a session only
   reaches the window after the operator approves it. */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Activity, Crosshair, Globe, Loader2, Monitor, PlugZap, RefreshCw, ShieldAlert, Unplug, Wrench, X,
} from 'lucide-react';
import {
  JsonRecord, RemoteProbeRequest, approveRemoteSession, closeRemoteSession, createRemoteSession,
  disconnectRemoteSession, getRemoteDesktop, listEngagements, listRemoteSessions, probeRemoteDesktop,
  reconnectRemoteSession, stopAll,
} from '../../services/vortexApi';
import { DangerButton, EmptyLine, ErrorLine, GhostButton, PrimaryButton, Section, StateBadge, asRecord, inputCls } from './common';

const OPEN_WHEN_READY_KEY = 'vortex.remote.openWhenReady.v1';

export interface RemoteSessionsProps {
  /** Pre-fill from an asset/target detail surface (host only; scope still decides). */
  initialHost?: string;
  initialEngagementId?: string;
  /** Session ids that already have a window; opening again focuses it instead. */
  openSessionIds: string[];
  keepSessionOnClose: boolean;
  onToggleKeepSessionOnClose: (value: boolean) => void;
  onOpenSession: (session: JsonRecord) => void;
  onFocusSession: (sessionId: string) => void;
  onOpenDependencies: () => void;
}

function readOpenWhenReady(): Record<string, boolean> {
  try {
    const raw = window.localStorage.getItem(OPEN_WHEN_READY_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' ? parsed as Record<string, boolean> : {};
  } catch {
    return {};
  }
}

function writeOpenWhenReady(value: Record<string, boolean>) {
  try {
    window.localStorage.setItem(OPEN_WHEN_READY_KEY, JSON.stringify(value));
  } catch {
    /* preference is best-effort and per browser profile */
  }
}

export const RemoteSessions: React.FC<RemoteSessionsProps> = ({
  initialHost, initialEngagementId, openSessionIds, keepSessionOnClose, onToggleKeepSessionOnClose,
  onOpenSession, onFocusSession, onOpenDependencies,
}) => {
  const [capabilities, setCapabilities] = useState<JsonRecord>({});
  const [engagements, setEngagements] = useState<JsonRecord[]>([]);
  const [sessions, setSessions] = useState<JsonRecord[]>([]);
  const [selectedEngagement, setSelectedEngagement] = useState(initialEngagementId || '');
  const [host, setHost] = useState(initialHost || '');
  const [display, setDisplay] = useState('0');
  const [transport, setTransport] = useState<'tls' | 'unencrypted'>('tls');
  const [privateAck, setPrivateAck] = useState(false);
  const [probe, setProbe] = useState<JsonRecord | null>(null);
  const [pending, setPending] = useState<JsonRecord | null>(null);
  const [approval, setApproval] = useState({ confirm: false, unencryptedApproved: false, protectedPath: false });
  const [openWhenReady, setOpenWhenReady] = useState<Record<string, boolean>>(readOpenWhenReady);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const refreshSessions = useCallback(async () => {
    try {
      const payload = await listRemoteSessions();
      setSessions((Array.isArray(payload.sessions) ? payload.sessions : []) as JsonRecord[]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [caps, eng] = await Promise.all([getRemoteDesktop(), listEngagements()]);
        if (cancelled) return;
        setCapabilities(asRecord(caps.remote_desktop));
        const list = (Array.isArray(eng.engagements) ? eng.engagements : []) as JsonRecord[];
        setEngagements(list);
        setSessions((Array.isArray(caps.sessions) ? caps.sessions : []) as JsonRecord[]);
        setSelectedEngagement((current) => current || String(list[0]?.id || ''));
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err));
      }
    })();
    const timer = window.setInterval(refreshSessions, 4000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [refreshSessions]);

  const active = useMemo(() => engagements.filter((item) => {
    const status = String(item.effective_status || item.status || '').toLowerCase();
    return status === 'active' || status === 'running' || status === '';
  }), [engagements]);

  const engagement = useMemo(
    () => active.find((item) => String(item.id) === selectedEngagement) || null,
    [active, selectedEngagement],
  );
  const limits = asRecord(capabilities.limits);
  const liveSessions = sessions.filter((item) => !item.retained && String(item.state) !== 'closed');
  const dependencies = (Array.isArray(capabilities.dependencies) ? capabilities.dependencies : []) as JsonRecord[];
  const clientReady = dependencies.every((item) => item.id !== 'capability:remote-desktop.novnc' || item.installed === true);
  const openWhenReadyKey = `${selectedEngagement}|${host}:${display}`;
  const autoOpen = Boolean(openWhenReady[openWhenReadyKey]);

  const protocols = (Array.isArray(capabilities.protocols) ? capabilities.protocols : []) as JsonRecord[];
  const vnc = protocols.find((item) => item.id === 'vnc') || {};
  const rdp = protocols.find((item) => item.id === 'rdp') || {};

  const probeRequest = useCallback((): RemoteProbeRequest => ({
    engagement_id: selectedEngagement,
    host: host.trim(),
    protocol: 'vnc',
    display: Number(display),
    transport,
    private_address_ack: privateAck,
  }), [display, host, privateAck, selectedEngagement, transport]);

  const runProbe = async () => {
    setError('');
    setNotice('');
    setProbe(null);
    setBusy('probe');
    try {
      const response = await probeRemoteDesktop(probeRequest());
      setProbe(asRecord(response.probe));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('');
    }
  };

  const openDesktop = async () => {
    setError('');
    setNotice('');
    setBusy('create');
    try {
      const created = await createRemoteSession({
        ...probeRequest(),
        label: `desktop ${host.trim()}:${5900 + Number(display)}`,
        client_library: 'noVNC',
      });
      const session = asRecord(created.session);
      setPending(session);
      setApproval({ confirm: false, unencryptedApproved: false, protectedPath: false });
      setNotice('Session created and waiting for your explicit approval.');
      await refreshSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('');
    }
  };

  const approvePending = async () => {
    if (!pending) return;
    setError('');
    setBusy('approve');
    try {
      const response = await approveRemoteSession(String(pending.id), {
        confirm: approval.confirm,
        unencrypted_approved: approval.unencryptedApproved,
        protected_path_ack: approval.protectedPath,
        private_address_ack: privateAck,
      });
      const session = asRecord(response.session);
      setPending(null);
      setNotice(
        autoOpen
          ? 'Approved. Opening the desktop window because "open desktop when ready" is enabled for this target.'
          : 'Approved. The desktop window opens now; it renders only what the RFB server sends.',
      );
      await refreshSessions();
      onOpenSession(session);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('');
    }
  };

  const act = async (label: string, run: () => Promise<unknown>) => {
    setError('');
    setBusy(label);
    try {
      await run();
      await refreshSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('');
    }
  };

  const runStopAll = async () => {
    setError('');
    setNotice('');
    setBusy('stopall');
    try {
      const result = await stopAll();
      const stop = asRecord(result.stop);
      setNotice(`STOP ALL closed ${Number(stop.remote_sessions_closed || 0)} remote session(s) and killed ${Number(stop.sessions_killed || 0)} shell session(s).`);
      await refreshSessions();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy('');
    }
  };

  const transportIsUnencrypted = transport === 'unencrypted';
  const unencryptedAllowed = capabilities.settings ? Boolean(asRecord(capabilities.settings).remote_desktop_allow_unencrypted) : false;
  const probeAvailable = probe ? Boolean(probe.available) : false;
  const submitDisabled = !selectedEngagement || !host.trim() || busy !== '' || !clientReady;

  return (
    <div className="h-full overflow-y-auto p-3 space-y-4 text-stone-200">
      {error && <ErrorLine message={error} />}
      {notice && (
        <div className="text-[11px] text-emerald-300 p-2 rounded bg-emerald-950/20 border border-emerald-900/40">{notice}</div>
      )}

      <Section title="Remote desktop capability (measured, not assumed)">
        <div className="flex flex-wrap items-center gap-2 text-[11px]">
          <span data-protocol-status="vnc" className="px-1.5 py-0.5 rounded border border-cyan-900 bg-cyan-950/30 text-cyan-300 font-bold">
            VNC / RFB · {String(vnc.status || 'supported')}
          </span>
          <span data-protocol-status="rdp" className="px-1.5 py-0.5 rounded border border-stone-700 bg-stone-900/40 text-stone-400 font-bold">
            RDP · {String(rdp.status || 'not_implemented')}
          </span>
          <span className="text-stone-500">
            bridge {String(asRecord(capabilities.bridge).implementation || 'sidecar')} · subprotocol {String(asRecord(capabilities.bridge).subprotocol || 'vortex.rfb.v1')} ·
            {' '}ports {JSON.stringify(asRecord(capabilities.bridge).port_range || [5900, 5999])}
          </span>
        </div>
        <div className="text-[10px] text-stone-500">
          {String(rdp.reason || 'RDP is intentionally not implemented: no maintained, self-contained gateway is available in this build.')}
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-1 text-[10px] text-stone-400">
          <div>max sessions: {String(limits.max_sessions ?? '?')} · idle timeout: {String(limits.idle_timeout_seconds ?? '?')}s</div>
          <div>ticket TTL: {String(limits.ticket_ttl_seconds ?? '?')}s · per session: {String(limits.ticket_max_per_session ?? '?')}</div>
        </div>
        <div className="space-y-1">
          {dependencies.map((item) => (
            <div key={String(item.id)} className="flex flex-wrap items-center gap-2 text-[10px] text-stone-400">
              <StateBadge state={String(item.installed ? 'installed' : 'unavailable')} />
              <span className="text-stone-300 font-semibold">{String(item.title || item.name || item.id)}</span>
              <span>{String(item.version || '')}</span>
              <span className="text-stone-500">{String(item.license || '')}</span>
              <span className="text-stone-500">{String(item.source || '')}</span>
              {!item.installed && <span className="text-amber-300">{String(item.installation || 'review the dependency plan')}</span>}
            </div>
          ))}
          {!clientReady && (
            <div className="flex items-center gap-2 text-[11px] text-amber-300">
              <Wrench className="w-3.5 h-3.5" />
              The bundled noVNC client assets are missing, so no desktop window can be rendered.
              <GhostButton onClick={onOpenDependencies}>OPEN DEPENDENCIES</GhostButton>
            </div>
          )}
        </div>
        <label className="flex items-center gap-2 text-[11px] text-stone-400">
          <input type="checkbox" checked={keepSessionOnClose} onChange={(event) => onToggleKeepSessionOnClose(event.target.checked)} />
          Window close keeps the session for an approved reconnect (default: close the session and its socket)
        </label>
      </Section>

      <Section title="1 · Authorized target">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <label className="text-[10px] text-stone-500 space-y-1">
            <span className="flex items-center gap-1"><Crosshair className="w-3 h-3" />ENGAGEMENT (active only)</span>
            <select value={selectedEngagement} onChange={(event) => setSelectedEngagement(event.target.value)} className={inputCls}>
              <option value="">select an engagement…</option>
              {active.map((item) => (
                <option key={String(item.id)} value={String(item.id)}>
                  {String(item.name || item.id)} — {((item.targets as unknown[]) || []).length} target(s)
                </option>
              ))}
            </select>
          </label>
          <label className="text-[10px] text-stone-500 space-y-1">
            <span className="flex items-center gap-1"><Globe className="w-3 h-3" />TARGET HOST (must be in scope)</span>
            <input value={host} onChange={(event) => setHost(event.target.value)} placeholder="10.20.0.15 or desktop.internal" className={inputCls} spellCheck={false} />
          </label>
          <label className="text-[10px] text-stone-500 space-y-1">
            <span>VNC DISPLAY (port 5900 + display)</span>
            <input value={display} onChange={(event) => setDisplay(event.target.value.replace(/[^0-9]/g, ''))} className={inputCls} inputMode="numeric" />
          </label>
          <label className="text-[10px] text-stone-500 space-y-1">
            <span>TRANSPORT SECURITY</span>
            <select value={transport} onChange={(event) => setTransport(event.target.value as 'tls' | 'unencrypted')} className={inputCls}>
              <option value="tls">TLS with certificate verification</option>
              <option value="unencrypted">Unencrypted RFB (needs an approved protected path)</option>
            </select>
          </label>
        </div>
        {engagement && (
          <div className="text-[10px] text-stone-500">
            scope: {String(engagement.name || engagement.id)} · targets {JSON.stringify((engagement.targets as unknown[]) || [])} ·
            {' '}expires {String(engagement.expires_at || 'n/a')} · status {String(engagement.effective_status || engagement.status || 'active')}
          </div>
        )}
        <label className="flex items-center gap-2 text-[11px] text-stone-400">
          <input type="checkbox" checked={privateAck} onChange={(event) => setPrivateAck(event.target.checked)} />
          This engagement explicitly authorizes the private/CGNAT address space for this target
        </label>
        <div className="flex flex-wrap items-center gap-2">
          <PrimaryButton onClick={() => void runProbe()} disabled={!selectedEngagement || !host.trim() || busy !== ''}>
            <span className="flex items-center gap-1">
              {busy === 'probe' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Activity className="w-3 h-3" />}
              CHECK ENDPOINT / PROTOCOL AVAILABILITY
            </span>
          </PrimaryButton>
          {transportIsUnencrypted && !unencryptedAllowed && (
            <span className="text-[10px] text-amber-300">
              This deployment forbids unencrypted transports; a TLS endpoint is required.
            </span>
          )}
        </div>
      </Section>

      {probe && (
        <Section title="2 · Endpoint check result (recorded as audit evidence)">
          <div className="p-2 rounded bg-black/50 border border-[var(--theme-border)] space-y-1 text-[11px]">
            <div className="flex flex-wrap items-center gap-2">
              <StateBadge state={probeAvailable ? 'available' : 'unavailable'} />
              <span className="text-stone-300">
                {String(asRecord(probe.endpoint).identity || `${host}:${5900 + Number(display)}`)}
              </span>
              {Boolean(probe.protocol_version) && <span className="text-stone-500">RFB {String(probe.protocol_version)}</span>}
              {probe.security_types != null && <span className="text-stone-500">security types {JSON.stringify(probe.security_types)}</span>}
            </div>
            {!probeAvailable && (
              <div className="text-amber-200 flex items-start gap-2">
                <ShieldAlert className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                <span data-remote-guidance="unavailable">{String(probe.guidance || '')}</span>
              </div>
            )}
            {probeAvailable && <div className="text-stone-400">{String(probe.guidance || '')}</div>}
            <div className="text-[10px] text-stone-500">
              shell evidence: {String(asRecord(probe.shell_evidence).detail || 'not checked')} ·
              {' '}matched target {String(probe.matched_target || asRecord(probe.scope).matched_target || 'n/a')}
            </div>
          </div>
        </Section>
      )}

      <Section title="3 · Open a desktop under this approval">
        <div className="flex flex-wrap items-center gap-2">
          <PrimaryButton onClick={() => void openDesktop()} disabled={submitDisabled || liveSessions.length >= Number(limits.max_sessions ?? 4)}>
            <span className="flex items-center gap-1">
              {busy === 'create' ? <Loader2 className="w-3 h-3 animate-spin" /> : <Monitor className="w-3 h-3" />}
              OPEN REMOTE DESKTOP
            </span>
          </PrimaryButton>
          <label className="flex items-center gap-2 text-[11px] text-stone-400">
            <input
              type="checkbox"
              data-open-when-ready="opt-in"
              checked={autoOpen}
              disabled={!selectedEngagement || !host.trim()}
              onChange={(event) => {
                const next = { ...openWhenReady, [openWhenReadyKey]: event.target.checked };
                if (!event.target.checked) delete next[openWhenReadyKey];
                setOpenWhenReady(next);
                writeOpenWhenReady(next);
              }}
            />
            Open desktop when ready for this approved target (default off)
          </label>
          {!probe && <span className="text-[10px] text-stone-500">Sessions are created whether or not you probed first; the desktop only renders once a real RFB server answers.</span>}
          {liveSessions.length >= Number(limits.max_sessions ?? 4) && (
            <span className="text-[10px] text-amber-300">Session limit reached — close a session before opening another.</span>
          )}
        </div>

        {pending && (
          <div data-approval-pending="true" className="p-2 rounded border border-amber-900/60 bg-amber-950/20 space-y-2 text-[11px]">
            <div className="font-bold text-amber-200">Approval required for {String(asRecord(pending.target).identity || pending.id)}</div>
            <div className="text-stone-400">
              Protocol {String(pending.protocol || 'vnc')} · transport {String(pending.transport || 'tls')} ·
              {' '}state {String(pending.state || 'awaiting_approval')}
            </div>
            <label className="flex items-start gap-2">
              <input type="checkbox" checked={approval.confirm} onChange={(event) => setApproval({ ...approval, confirm: event.target.checked })} />
              <span>I confirm this target is authorized by the engagement scope above and I am approved to open a desktop on it.</span>
            </label>
            {String(pending.transport) === 'unencrypted' && (
              <>
                <label className="flex items-start gap-2">
                  <input type="checkbox" checked={approval.protectedPath} onChange={(event) => setApproval({ ...approval, protectedPath: event.target.checked })} />
                  <span>This connection travels an approved protected path (VPN or SSH tunnel I control).</span>
                </label>
                <label className="flex items-start gap-2">
                  <input type="checkbox" checked={approval.unencryptedApproved} onChange={(event) => setApproval({ ...approval, unencryptedApproved: event.target.checked })} />
                  <span>I accept the unencrypted RFB transport for this specific session.</span>
                </label>
              </>
            )}
            <div className="flex items-center gap-2">
              <PrimaryButton
                disabled={!approval.confirm || busy === 'approve' || (String(pending.transport) === 'unencrypted' && (!approval.unencryptedApproved || !approval.protectedPath))}
                onClick={() => void approvePending()}
              >
                APPROVE AND OPEN
              </PrimaryButton>
              <GhostButton onClick={() => void act('cancel', () => closeRemoteSession(String(pending.id), 'operator_cancelled'))}>
                CANCEL
              </GhostButton>
            </div>
          </div>
        )}
      </Section>

      <Section title={`4 · Remote sessions (${liveSessions.length})`}>
        <div className="flex items-center gap-2">
          <GhostButton onClick={() => void refreshSessions()}><span className="flex items-center gap-1"><RefreshCw className="w-3 h-3" />REFRESH</span></GhostButton>
          <DangerButton onClick={() => void runStopAll()} disabled={busy === 'stopall'}>
            <span className="flex items-center gap-1"><X className="w-3 h-3" />STOP ALL</span>
          </DangerButton>
          <span className="text-[10px] text-stone-500">The workbench STOP ALL control also closes every remote session and its socket.</span>
        </div>
        {sessions.length === 0 && <EmptyLine message="No remote-desktop sessions recorded yet." />}
        <div className="space-y-1">
          {sessions.map((session) => {
            const id = String(session.id);
            const isOpen = openSessionIds.includes(id);
            const state = String(session.state || 'created');
            const transportLabel = session.transport_secure ? 'TLS' : 'UNENCRYPTED';
            return (
              <div key={id} data-remote-session={id} className="p-2 rounded bg-black/50 border border-[var(--theme-border)] text-[11px] space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="px-1.5 py-0.5 rounded border border-[var(--theme-border)] text-stone-300 font-bold">{String(session.protocol || 'vnc').toUpperCase()}</span>
                  <StateBadge state={state} />
                  <span className={`px-1.5 py-0.5 rounded border font-bold ${session.transport_secure ? 'border-emerald-900 bg-emerald-950/30 text-emerald-300' : 'border-amber-800 bg-amber-950/30 text-amber-300'}`}>
                    {transportLabel}
                  </span>
                  <span className="text-stone-300">{String(asRecord(session.target).identity || '')}</span>
                  <span className="flex-1" />
                  {Boolean(session.retained) && <span className="text-[10px] text-stone-500">retained record</span>}
                  {numberOf(session.bytes_in) + numberOf(session.bytes_out) > 0 && (
                    <span className="text-[10px] text-stone-500">{numberOf(session.bytes_in)} B in / {numberOf(session.bytes_out)} B out</span>
                  )}
                </div>
                <div className="text-[10px] text-stone-500">
                  engagement {String(session.engagement_name || session.engagement_id || '')} ·
                  {' '}created {String(session.created_at || '')} · last activity {String(session.last_activity || '')}
                  {session.failure_reason ? ` · failure: ${String(session.failure_reason)}` : ''}
                  {session.disconnect_reason ? ` · disconnect: ${String(session.disconnect_reason)}` : ''}
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {state === 'closed'
                    ? <span className="text-[10px] text-stone-500">closed — create a new approved session to reconnect</span>
                    : (
                      <>
                        {state === 'failed'
                          ? (
                            <PrimaryButton onClick={() => void act(`reconnect-${id}`, () => reconnectRemoteSession(id))}>
                              <span className="flex items-center gap-1"><PlugZap className="w-3 h-3" />RECONNECT</span>
                            </PrimaryButton>
                          )
                          : (
                            <PrimaryButton
                              onClick={() => (isOpen ? onFocusSession(id) : onOpenSession(session))}
                              disabled={state === 'awaiting_approval'}
                            >
                              <span className="flex items-center gap-1">
                                <Monitor className="w-3 h-3" />{isOpen ? 'FOCUS WINDOW' : state === 'awaiting_approval' ? 'AWAITING APPROVAL' : 'OPEN WINDOW'}
                              </span>
                            </PrimaryButton>
                          )}
                        <GhostButton onClick={() => void act(`disconnect-${id}`, () => disconnectRemoteSession(id))} disabled={state === 'disconnected'}>
                          <span className="flex items-center gap-1"><Unplug className="w-3 h-3" />DISCONNECT</span>
                        </GhostButton>
                        <DangerButton onClick={() => void act(`close-${id}`, () => closeRemoteSession(id))}>
                          <span className="flex items-center gap-1"><X className="w-3 h-3" />CLOSE + CLEAN UP</span>
                        </DangerButton>
                      </>
                    )}
                </div>
              </div>
            );
          })}
        </div>
      </Section>
    </div>
  );
};

function numberOf(value: unknown): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

export default RemoteSessions;
