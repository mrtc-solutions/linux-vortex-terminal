/* Shared popup primitives — Vortex Terminal theme, no mock data anywhere. */
import React from 'react';

export function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <div className="text-[10px] uppercase tracking-wider text-stone-500 font-semibold">{title}</div>
      {children}
    </div>
  );
}

export function StateBadge({ state }: { state: string }) {
  const s = state.toLowerCase();
  const cls = s === 'available' || s === 'installed' || s === 'active' || s === 'running' || s === 'responded' || s === 'completed' || s === 'succeeded'
    ? 'text-emerald-400 border-emerald-800 bg-emerald-950/40'
    : s === 'unavailable' || s === 'absent' || s === 'failed' || s === 'blocked' || s === 'disabled' || s === 'stopped' || s === 'missing'
      ? 'text-stone-400 border-stone-700 bg-stone-900/40'
      : 'text-amber-300 border-amber-800 bg-amber-950/40';
  return (
    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${cls}`}>
      {state.toUpperCase()}
    </span>
  );
}

export function ErrorLine({ message }: { message: string }) {
  if (!message) return null;
  return (
    <div className="text-[11px] text-rose-400 p-2 rounded bg-rose-950/20 border border-rose-900/40 whitespace-pre-wrap">
      {message}
    </div>
  );
}

export function EmptyLine({ message }: { message: string }) {
  return <div className="text-[11px] text-stone-500 p-2">{message}</div>;
}

export function asRecord(value: unknown): Record<string, unknown> {
  return (value && typeof value === 'object' ? value : {}) as Record<string, unknown>;
}

export function PrimaryButton(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const { className, ...rest } = props;
  return (
    <button
      {...rest}
      className={`px-2.5 py-1 rounded bg-[var(--theme-primary)] text-black font-bold text-[11px] hover:opacity-90 disabled:opacity-40 transition-opacity cursor-pointer ${className || ''}`}
    />
  );
}

export function GhostButton(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const { className, ...rest } = props;
  return (
    <button
      {...rest}
      className={`px-2.5 py-1 rounded border border-[var(--theme-border)] text-stone-300 font-semibold text-[11px] hover:text-[var(--theme-primary)] disabled:opacity-40 transition-colors cursor-pointer ${className || ''}`}
    />
  );
}

export function DangerButton(props: React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const { className, ...rest } = props;
  return (
    <button
      {...rest}
      className={`px-2.5 py-1 rounded border border-rose-900/60 text-rose-300 font-semibold text-[11px] hover:bg-rose-950/40 disabled:opacity-40 transition-colors cursor-pointer ${className || ''}`}
    />
  );
}

export const inputCls =
  'w-full bg-black/60 border border-[var(--theme-border)] rounded px-2 py-1 text-[12px] text-stone-200 placeholder-stone-600 focus:outline-none focus:border-[var(--theme-primary)]';
