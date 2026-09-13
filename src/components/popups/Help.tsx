/* Help popup — the real operator reference: pipeline, commands, shortcuts.
   Static text, but every claim matches the actual app behavior. */
import React from 'react';
import { CircleHelp } from 'lucide-react';
import { Section } from './common';

interface HelpProps {
  onOpenPopup: (kind: string) => void;
}

function Row({ keys, what }: { keys: string; what: string }) {
  return (
    <div className="flex items-start gap-2 text-[11px]">
      <span className="text-[var(--theme-primary)] font-mono font-bold shrink-0 min-w-28">{keys}</span>
      <span className="text-stone-300">{what}</span>
    </div>
  );
}

export const Help: React.FC<HelpProps> = ({ onOpenPopup }) => {
  return (
    <div className="p-4 space-y-4 text-stone-300">
      <div className="flex items-center gap-2">
        <CircleHelp className="w-4 h-4 text-[var(--theme-primary)]" />
        <span className="text-[12px] font-bold text-stone-200">Vortex Terminal operator help</span>
      </div>

      <Section title="How a turn works">
        <div className="text-[11px] text-stone-400 leading-relaxed p-2 rounded bg-black/50 border border-[var(--theme-border)]">
          You type what you want → the sidecar builds a <span className="text-stone-200">typed plan</span> over
          reviewed adapters → local AI / the agent council <span className="text-stone-200">advise</span> →
          the independent <span className="text-stone-200">Guardian</span> recomputes risk →
          low-risk plans auto-run under your policy, everything else waits in a
          <span className="text-stone-200"> plan review</span> → execution streams live →
          evidence is hashed, audit-chained, and filed under /out and Reports.
        </div>
      </Section>

      <Section title="Terminal commands">
        <div className="space-y-1 p-2 rounded bg-black/50 border border-[var(--theme-border)]">
          <Row keys="clear" what="Clear the terminal scrollback." />
          <Row keys="help" what="Print the command reference in the terminal." />
          <Row keys="stop" what="STOP ALL — signal every running operation and session." />
          <Row keys="retry" what="Retry the sidecar handshake after a disconnect." />
          <Row keys="shell" what="Open a raw host PTY (your keys, no Guardian)." />
          <Row keys="map · out · report" what="Jump to the Tactical Map, /out evidence, or Reports tab." />
          <Row keys="tasks · scope · tools" what="Open the task ledger, engagement scope, or tool inventory." />
          <Row keys="models · system" what="Open local-AI models or system health." />
          <Row keys="history · memory" what="Open conversations or durable memory." />
          <Row keys="settings · aiops" what="Open policy settings or the AI Ops advisory trace." />
          <Row keys="launcher" what="Open the Vortex Terminal start menu." />
          <Row keys="about" what="Open About: version, MIT license, Android APK and Linux DEB downloads." />
        </div>
      </Section>

      <Section title="Keyboard">
        <div className="space-y-1 p-2 rounded bg-black/50 border border-[var(--theme-border)]">
          <Row keys="Enter" what="Run the typed turn." />
          <Row keys="Tab" what="Autocomplete the current token." />
          <Row keys="↑ / ↓" what="Walk command history." />
          <Row keys="Ctrl+L" what="Clear the terminal scrollback." />
          <Row keys="Esc" what="Close the topmost popup window." />
        </div>
      </Section>

      <Section title="Safety model">
        <div className="text-[11px] text-stone-400 leading-relaxed p-2 rounded bg-black/50 border border-[var(--theme-border)]">
          Safe profile: every plan asks first. Standard/Expert: low-risk read-only plans auto-run.
          Medium-risk plans always ask (Guardian invariant). Assessment work needs an authorized
          engagement in <button onClick={() => onOpenPopup('scope')} className="text-[var(--theme-primary)] hover:underline cursor-pointer">Scope</button>.
          The raw <button onClick={() => onOpenPopup('shell')} className="text-[var(--theme-primary)] hover:underline cursor-pointer">Host Shell</button> bypasses
          the Guardian entirely — it is your keys on your machine.
        </div>
      </Section>
    </div>
  );
};
