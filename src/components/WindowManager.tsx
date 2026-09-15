/* Vortex Terminal popup window manager — every secondary surface opens here.
   Minimize / maximize / close + restore tray + focus order + Esc to close.
   Windows are lazy: content mounts only while the popup is open. */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';

export interface PopupSpec {
  id: string;
  title: string;
  icon?: React.ReactNode;
  content: React.ReactNode;
  width?: number;
  height?: number;
}

interface WindowManagerProps {
  popups: PopupSpec[];
  onClose: (id: string) => void;
}

type WindowState = 'normal' | 'minimized' | 'maximized';

interface FrameState {
  windowState: WindowState;
  z: number;
  x?: number;
  y?: number;
}

const CASCADE_DX = 36;
const CASCADE_DY = 30;

export const WindowManager: React.FC<WindowManagerProps> = ({ popups, onClose }) => {
  const [frames, setFrames] = useState<Record<string, FrameState>>({});
  const [viewport, setViewport] = useState({ width: window.innerWidth, height: window.innerHeight });
  useEffect(() => {
    const resize = () => setViewport({ width: window.innerWidth, height: window.innerHeight });
    window.addEventListener('resize', resize);
    return () => window.removeEventListener('resize', resize);
  }, []);
  const drag = useRef<{ id: string; x: number; y: number; left: number; top: number } | null>(null);
  const zCounter = useRef(50);

  const bringToFront = useCallback((id: string) => {
    zCounter.current += 1;
    const z = zCounter.current;
    setFrames((prev) => ({
      ...prev,
      [id]: { ...prev[id], windowState: prev[id]?.windowState || 'normal', z },
    }));
  }, []);

  // New popups arrive on top; drop state for closed ones.
  useEffect(() => {
    setFrames((prev) => {
      const next: Record<string, FrameState> = {};
      for (const popup of popups) {
        if (prev[popup.id]) {
          next[popup.id] = prev[popup.id];
        } else {
          zCounter.current += 1;
          next[popup.id] = { windowState: 'normal', z: zCounter.current };
        }
      }
      return next;
    });
  }, [popups]);

  // Esc closes the topmost normal/maximized window.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.defaultPrevented || popups.length === 0) return;
      if (event.target instanceof Element && event.target.closest('input, textarea, select, [contenteditable="true"]')) return;
      const ordered = [...popups].sort(
        (a, b) => (frames[b.id]?.z || 0) - (frames[a.id]?.z || 0),
      );
      const top = ordered.find((popup) => frames[popup.id]?.windowState !== 'minimized');
      if (top) onClose(top.id);
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [popups, frames, onClose]);

  const setState = useCallback((id: string, windowState: WindowState) => {
    if (windowState === 'minimized') {
      setFrames((prev) => ({
        ...prev,
        [id]: { ...prev[id], windowState, z: prev[id]?.z || 50 },
      }));
      return;
    }
    zCounter.current += 1;
    const z = zCounter.current;
    setFrames((prev) => ({ ...prev, [id]: { ...prev[id], windowState, z } }));
  }, []);

  const minimized = useMemo(
    () => popups.filter((popup) => frames[popup.id]?.windowState === 'minimized'),
    [popups, frames],
  );

  if (popups.length === 0) return null;

  return (
    <>
      {popups.map((popup, index) => {
        const frame = frames[popup.id] || { windowState: 'normal' as WindowState, z: 50 + index };
        const isMinimized = frame.windowState === 'minimized';
        const maximized = frame.windowState === 'maximized';
        const offsetX = (index % 6) * CASCADE_DX;
        const offsetY = (index % 6) * CASCADE_DY;
        const width = Math.min(popup.width || 640, viewport.width - 32);
        const height = Math.min(popup.height || 480, viewport.height - 32);
        const left = Math.max(16, Math.min(frame.x ?? (viewport.width - width) / 2 + offsetX, viewport.width - width - 16));
        const top = Math.max(16, Math.min(frame.y ?? viewport.height * .46 - height / 2 + offsetY, viewport.height - height - 16));
        return (
          <div
            key={popup.id}
            role="dialog"
            aria-modal="false"
            aria-label={popup.title}
            className="fixed inset-0 z-50 pointer-events-none"
            style={{ zIndex: 50 + frame.z, display: isMinimized ? 'none' : 'block' }}
            onMouseDown={() => bringToFront(popup.id)}
          >
            <div
              className="pointer-events-auto absolute flex flex-col rounded-lg overflow-hidden bg-[var(--theme-surface)] border border-[var(--theme-border)] box-glow-strong font-mono"
              style={maximized
                ? { left: 12, right: 12, top: 12, bottom: 12 }
                : {
                    left,
                    top,
                    width: `${width}px`,
                    height: `${height}px`,
                    maxWidth: 'calc(100vw - 32px)',
                    maxHeight: 'calc(100vh - 32px)',
                  }}
            >
              {/* Titlebar */}
              <div
                onPointerDown={(event) => {
                  if (maximized || event.button !== 0 || (event.target as Element).closest('button')) return;
                  event.currentTarget.setPointerCapture(event.pointerId);
                  drag.current = { id: popup.id, x: event.clientX, y: event.clientY, left, top };
                  bringToFront(popup.id);
                }}
                onPointerMove={(event) => {
                  const d = drag.current;
                  if (!d || d.id !== popup.id) return;
                  const x = Math.max(16, Math.min(d.left + event.clientX - d.x, viewport.width - width - 16));
                  const y = Math.max(16, Math.min(d.top + event.clientY - d.y, viewport.height - height - 16));
                  setFrames(prev => ({ ...prev, [popup.id]: { ...prev[popup.id], x, y } }));
                }}
                onPointerUp={() => { drag.current = null; }}
                onPointerCancel={() => { drag.current = null; }}
                style={{ touchAction: 'none' }}
                className="flex items-center justify-between px-3 py-2 border-b border-[var(--theme-border)] bg-black/40 select-none shrink-0">
                <div className="flex items-center gap-2 min-w-0 text-xs font-bold tracking-wider text-[var(--theme-primary)]">
                  {popup.icon}
                  <span className="glow-primary truncate">{popup.title}</span>
                </div>
                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={() => setState(popup.id, 'minimized')}
                    title="Minimize"
                    aria-label="Minimize window"
                    className="w-7 h-6 rounded text-stone-400 hover:text-[var(--theme-primary)] hover:bg-[var(--theme-border)] transition-colors cursor-pointer text-sm leading-none"
                  >
                    —
                  </button>
                  <button
                    onClick={() => setState(popup.id, maximized ? 'normal' : 'maximized')}
                    title={maximized ? 'Restore' : 'Maximize'}
                    aria-label={maximized ? 'Restore window' : 'Maximize window'}
                    aria-pressed={maximized}
                    className="w-7 h-6 rounded text-stone-400 hover:text-[var(--theme-primary)] hover:bg-[var(--theme-border)] transition-colors cursor-pointer text-xs leading-none"
                  >
                    {maximized ? '❐' : '□'}
                  </button>
                  <button
                    onClick={() => onClose(popup.id)}
                    title="Close"
                    aria-label="Close window"
                    className="w-7 h-6 rounded text-stone-400 hover:text-rose-400 hover:bg-rose-950/40 transition-colors cursor-pointer text-sm leading-none"
                  >
                    ×
                  </button>
                </div>
              </div>
              {/* Content */}
              <div className="flex-1 overflow-y-auto text-xs">
                {popup.content}
              </div>
            </div>
          </div>
        );
      })}

      {/* Restore tray for minimized windows */}
      {minimized.length > 0 && (
        <div className="fixed bottom-3 left-1/2 -translate-x-1/2 z-[500] max-w-[calc(100vw-24px)] max-h-[30vh] overflow-auto flex flex-wrap items-center gap-1.5 px-2 py-1.5 rounded-lg bg-black/80 border border-[var(--theme-border)] box-glow font-mono">
          {minimized.map((popup) => (
            <button
              key={popup.id}
              onClick={() => setState(popup.id, 'normal')}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded text-[11px] text-stone-300 hover:text-[var(--theme-primary)] hover:bg-[var(--theme-border)] transition-colors cursor-pointer"
              title={`Restore ${popup.title}`}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--theme-primary)] animate-soft-pulse" />
              {popup.icon}
              <span>{popup.title}</span>
            </button>
          ))}
        </div>
      )}
    </>
  );
};
