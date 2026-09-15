import { useEffect, useState, type CSSProperties } from 'react';

interface WindowState { maximized: boolean; minimizable?: boolean; maximizable?: boolean; closable?: boolean }
interface WindowBridge {
  minimize: () => void;
  toggleMaximize: () => void;
  close: () => void;
  getState: () => Promise<WindowState>;
  onStateChange: (callback: (state: WindowState) => void) => (() => void) | void;
}

export function NativeTitleBar() {
  const bridge = (window as unknown as { vortexWindow?: WindowBridge }).vortexWindow;
  const [state, setState] = useState<WindowState>({ maximized: false });
  const [error, setError] = useState('');
  useEffect(() => {
    if (!bridge) return;
    let alive = true;
    void bridge.getState().then(s => { if (alive) setState(s); }).catch(() => { if (alive) setError('Native window state unavailable'); });
    const unsubscribe = bridge.onStateChange(s => { if (alive) setState(s); });
    return () => { alive = false; unsubscribe?.(); };
  }, [bridge]);
  if (!bridge) return null;
  return <div className="flex items-center justify-between px-3 py-1 bg-black text-stone-300 text-xs shrink-0 z-50"
    style={{ WebkitAppRegion: 'drag' } as CSSProperties} onDoubleClick={() => bridge.toggleMaximize()}>
    <span>Vortex Terminal {error && `— ${error}`}</span>
    <div className="flex gap-1" style={{ WebkitAppRegion: 'no-drag' } as CSSProperties} onDoubleClick={e => e.stopPropagation()}>
      <button aria-label="Minimize application" disabled={state.minimizable === false} onClick={() => bridge.minimize()} className="px-3 py-1 hover:bg-stone-700">—</button>
      <button aria-label={state.maximized ? 'Restore application' : 'Maximize application'} disabled={state.maximizable === false} onClick={() => bridge.toggleMaximize()} className="px-3 py-1 hover:bg-stone-700">{state.maximized ? '❐' : '□'}</button>
      <button aria-label="Close application" disabled={state.closable === false} onClick={() => bridge.close()} className="px-3 py-1 hover:bg-red-800">×</button>
    </div>
  </div>;
}
