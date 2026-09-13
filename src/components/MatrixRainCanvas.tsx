import React, { useEffect, useRef } from 'react';
import { ThemeMode } from '../types/terminal';

interface MatrixRainCanvasProps {
  theme: ThemeMode;
  enabled: boolean;
  opacity?: number;
}

export const MatrixRainCanvas: React.FC<MatrixRainCanvasProps> = ({ theme, enabled, opacity = 0.15 }) => {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    if (!enabled) return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animationFrameId: number;
    let width = (canvas.width = window.innerWidth);
    let height = (canvas.height = window.innerHeight);

    const handleResize = () => {
      if (!canvas) return;
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    };
    window.addEventListener('resize', handleResize);

    // Characters: Katakana, hex numbers, mathematical symbols
    const chars = '0123456789ABCDEFｦｱｳｴｵｶｷｹｺｻｼｽｾｿﾀﾂﾃﾅﾆﾇﾈﾊﾋﾎﾏﾐﾑﾒﾓﾔﾕﾗﾘﾜ'.split('');
    const fontSize = 14;
    const columns = Math.floor(width / fontSize);
    const drops: number[] = Array.from({ length: columns }, () => Math.floor(Math.random() * -50));

    // Theme color mapping
    const getColor = (isHead: boolean) => {
      if (isHead) return '#ffffff';
      switch (theme) {
        case 'amber':
          return '#ffb000';
        case 'cyan':
          return '#00f0ff';
        case 'crimson':
          return '#ff3366';
        case 'violet':
          return '#c084fc';
        case 'matrix':
        default:
          return '#00ff66';
      }
    };

    const render = () => {
      // Dark semi-transparent fade
      ctx.fillStyle = 'rgba(5, 11, 7, 0.18)';
      ctx.fillRect(0, 0, width, height);

      ctx.font = `${fontSize}px monospace`;

      for (let i = 0; i < drops.length; i++) {
        const char = chars[Math.floor(Math.random() * chars.length)];
        const x = i * fontSize;
        const y = drops[i] * fontSize;

        // Glowing head
        ctx.fillStyle = getColor(drops[i] > 1 && Math.random() > 0.85);
        ctx.fillText(char, x, y);

        if (y > height && Math.random() > 0.975) {
          drops[i] = 0;
        }
        drops[i]++;
      }

      animationFrameId = requestAnimationFrame(render);
    };

    render();

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener('resize', handleResize);
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
