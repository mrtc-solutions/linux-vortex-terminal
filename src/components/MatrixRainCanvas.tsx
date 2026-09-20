import React, { useEffect, useRef } from 'react';
import { ThemeMode } from '../types/terminal';

interface MatrixRainCanvasProps {
  theme: ThemeMode;
  enabled: boolean;
  opacity?: number;
}

const THEME_COLORS: Record<ThemeMode, string> = {
  matrix: '#00ff66',
  amber: '#ffb000',
  cyan: '#00f0ff',
  crimson: '#ff3366',
  violet: '#c084fc',
};
const HEAD_COLOR = '#ffffff';
const FONT_SIZE = 14;
// Characters: Katakana, hex numbers, mathematical symbols
const CHARS = '0123456789ABCDEFｦｱｳｴｵｶｷｹｺｻｼｽｾｿﾀﾂﾃﾅﾆﾇﾈﾊﾋﾎﾏﾐﾑﾒﾓﾔﾕﾗﾘﾜ'.split('');

export const MatrixRainCanvas: React.FC<MatrixRainCanvasProps> = ({ theme, enabled, opacity = 0.15 }) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const color = THEME_COLORS[theme] ?? THEME_COLORS.matrix;
    let width = 0;
    let height = 0;
    let drops: number[] = [];

    // Resize rebuilds the drop column count, preserving each column's fall
    // progress so a wider window rains across its full width (a stale column
    // count used to leave the right side dry after maximizing).
    const resize = () => {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
      const columns = Math.max(1, Math.floor(width / FONT_SIZE));
      const next: number[] = new Array(columns);
      for (let i = 0; i < columns; i++) {
        next[i] = i < drops.length ? drops[i] : Math.floor(Math.random() * -50);
      }
      drops = next;
      ctx.font = `${FONT_SIZE}px monospace`;
    };
    resize();
    window.addEventListener('resize', resize);

    let raf = 0;
    let suspended = document.hidden;
    let tick = 0;
    // Render every 2nd frame (~30fps): identical look, half the CPU. When a
    // frame takes too long (software rendering on a VM), drop to every 3rd
    // instead of stacking up work the compositor can never show.
    let stride = 2;
    let last = performance.now();

    const loop = (now: number) => {
      if (suspended) return;
      raf = requestAnimationFrame(loop);
      tick += 1;
      const delta = now - last;
      last = now;
      if (delta > 80) stride = 3;
      else if (delta < 40 && stride > 2) stride = 2;
      if (tick % stride !== 0) return;

      // Dark semi-transparent fade
      ctx.fillStyle = 'rgba(5, 11, 7, 0.18)';
      ctx.fillRect(0, 0, width, height);

      ctx.fillStyle = color;
      for (let i = 0; i < drops.length; i++) {
        const y = drops[i] * FONT_SIZE;
        // Deterministic twinkle: the glowing head walks across columns with
        // the tick counter instead of rolling RNG per drop per frame.
        const head = (i + tick) % 9 === 0;
        if (head) ctx.fillStyle = HEAD_COLOR;
        ctx.fillText(CHARS[(Math.random() * CHARS.length) | 0], i * FONT_SIZE, y);
        if (head) ctx.fillStyle = color;

        if (y > height && Math.random() > 0.975) {
          drops[i] = 0;
        } else {
          drops[i] += 1;
        }
      }
    };

    const suspend = () => {
      if (suspended) return;
      suspended = true;
      cancelAnimationFrame(raf);
    };
    const resume = () => {
      if (!suspended || document.hidden) return;
      suspended = false;
      last = performance.now();
      raf = requestAnimationFrame(loop);
    };
    // A hidden tab, a minimized window, or a blurred window never needs fresh
    // rain: pausing drops the decoration's background CPU cost to zero.
    const onVisibility = () => {
      if (document.hidden) suspend();
      else resume();
    };
    document.addEventListener('visibilitychange', onVisibility);
    window.addEventListener('blur', suspend);
    window.addEventListener('focus', resume);

    if (!suspended) raf = requestAnimationFrame(loop);

    return () => {
      suspended = true;
      cancelAnimationFrame(raf);
      document.removeEventListener('visibilitychange', onVisibility);
      window.removeEventListener('blur', suspend);
      window.removeEventListener('focus', resume);
      window.removeEventListener('resize', resize);
    };
  }, [enabled, theme]);

  if (!enabled) return null;

  return (
    <canvas
      ref={canvasRef}
      className="fixed inset-0 pointer-events-none z-0 transition-opacity duration-700"
      style={{ opacity }}
    />
  );
};
