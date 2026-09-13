import React, { useState, useEffect, useRef } from 'react';
import { NetworkNode, NetworkLink } from '../types/terminal';
import { 
  ShieldAlert, 
  Terminal, 
  Crosshair, 
  Wifi, 
  RotateCcw, 
  Server, 
  Database, 
  Lock, 
  Zap,
  Radio
} from 'lucide-react';
import { sound } from '../services/soundEffects';

interface TacticalMapProps {
  onExecuteCommand: (cmd: string) => void;
  onNavigateToOut?: () => void;
}

const INITIAL_NODES: NetworkNode[] = [
  {
    id: 'node-attacker',
    ip: '192.168.1.80',
    hostname: 'spectre-workstation (Local)',
    subnet: '192.168.1.0/24',
    type: 'workstation',
    status: 'scanned',
    os: 'Linux 6.12.9-spectre-rt (x86_64)',
    ports: [22, 8080, 11434],
    services: [
      { port: 22, name: 'OpenSSH', version: '8.9p1' },
      { port: 11434, name: 'Ollama-Cluster', version: 'DeepSeek+Llama+Mistral' },
    ],
    x: 180,
    y: 280,
    isPivoted: false,
  },
  {
    id: 'node-gateway',
    ip: '192.168.1.1',
    hostname: 'edge-gw.corp.lan',
    subnet: '192.168.1.0/24',
    type: 'gateway',
    status: 'compromised',
    os: 'EdgeOS 2.0.9 (FreeBSD based)',
    ports: [22, 80, 443],
    services: [
      { port: 22, name: 'OpenSSH', version: '8.9p1' },
      { port: 80, name: 'Lighttpd', version: '1.4.59' },
      { port: 443, name: 'HTTPS WebUI', version: 'TLS 1.3', cve: 'CVE-2023-38606' },
    ],
    x: 380,
    y: 150,
    isPivoted: true,
  },
  {
    id: 'node-auth',
    ip: '192.168.1.15',
    hostname: 'auth-srv01.corp.lan',
    subnet: '192.168.1.0/24',
    type: 'target_server',
    status: 'vulnerable',
    os: 'Ubuntu 22.04 LTS',
    ports: [22, 8080, 8443],
    services: [
      { port: 8080, name: 'Spring Boot', version: '3.1.2 (Actuator Expose)', cve: 'CVE-2022-22965' },
      { port: 8443, name: 'OAuth2 IDP', version: 'Keycloak 21.0' },
    ],
    x: 620,
    y: 140,
    isPivoted: false,
  },
  {
    id: 'node-db',
    ip: '192.168.1.42',
    hostname: 'db-vault-primary.internal',
    subnet: '192.168.1.0/24',
    type: 'database',
    status: 'vulnerable',
    os: 'Debian 12 Bookworm',
    ports: [5432, 22],
    services: [
      { port: 5432, name: 'PostgreSQL', version: '14.5 (Weak Salt Hash)', cve: 'CVE-2022-41862' },
      { port: 22, name: 'SSH', version: 'OpenSSH 9.2' },
    ],
    x: 640,
    y: 350,
    isPivoted: false,
  },
  {
    id: 'node-dmz',
    ip: '192.168.1.99',
    hostname: 'dmz-ingress.corp.lan',
    subnet: '192.168.1.0/24',
    type: 'firewall',
    status: 'scanned',
    os: 'Alpine Linux 3.19',
    ports: [80, 443],
    services: [
      { port: 80, name: 'NGINX Reverse Proxy', version: '1.24.0' },
      { port: 443, name: 'TLS Proxy', version: '1.24.0' },
    ],
    x: 360,
    y: 380,
    isPivoted: false,
  },
  {
    id: 'node-external',
    ip: '198.51.100.44',
    hostname: 'tor-exit-inbound.ru',
    subnet: 'WAN / Untrusted',
    type: 'target_server',
    status: 'unreachable',
    os: 'Unknown Linux',
    ports: [22, 9001],
    services: [
      { port: 9001, name: 'Tor Relay Node', version: '0.4.7' },
    ],
    x: 140,
    y: 110,
    isPivoted: false,
  },
];

const LINKS: NetworkLink[] = [
  { source: 'node-attacker', target: 'node-gateway', type: 'exploited', latency: 4, activePackets: true },
  { source: 'node-gateway', target: 'node-auth', type: 'tunnel', latency: 2, activePackets: true },
  { source: 'node-gateway', target: 'node-dmz', type: 'ethernet', latency: 1, activePackets: true },
  { source: 'node-auth', target: 'node-db', type: 'ethernet', latency: 3, activePackets: true },
  { source: 'node-external', target: 'node-gateway', type: 'firewalled', latency: 68, activePackets: false },
];

export const TacticalMap: React.FC<TacticalMapProps> = ({ onExecuteCommand }) => {
  const [nodes, setNodes] = useState<NetworkNode[]>(INITIAL_NODES);
  const [selectedNode, setSelectedNode] = useState<NetworkNode | null>(INITIAL_NODES[1]);
  const [radarActive, setRadarActive] = useState<boolean>(true);
  const [draggingNodeId, setDraggingNodeId] = useState<string | null>(null);
  const [dragOffset, setDragOffset] = useState<{ x: number; y: number }>({ x: 0, y: 0 });
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  // Canvas animated packet trails
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    let animId: number;
    let packetT = 0;

    const render = () => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Draw Grid Background
      ctx.strokeStyle = 'rgba(0, 255, 102, 0.05)';
      ctx.lineWidth = 1;
      const gridSize = 40;
      for (let x = 0; x < canvas.width; x += gridSize) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, canvas.height);
        ctx.stroke();
      }
      for (let y = 0; y < canvas.height; y += gridSize) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(canvas.width, y);
        ctx.stroke();
      }

      // Draw Subnet Boundary Ellipse
      ctx.save();
      ctx.strokeStyle = 'rgba(0, 255, 102, 0.2)';
      ctx.setLineDash([6, 6]);
      ctx.beginPath();
      ctx.ellipse(460, 250, 310, 190, 0, 0, Math.PI * 2);
      ctx.stroke();
      ctx.fillStyle = 'rgba(0, 255, 102, 0.02)';
      ctx.fill();
      ctx.fillStyle = 'rgba(0, 255, 102, 0.4)';
      ctx.font = '10px monospace';
      ctx.fillText('SUBNET SCOPE: 192.168.1.0/24 (AUTHORIZED)', 180, 80);
      ctx.restore();

      // Draw Links between nodes
      LINKS.forEach((link) => {
        const src = nodes.find((n) => n.id === link.source);
        const tgt = nodes.find((n) => n.id === link.target);
        if (!src || !tgt) return;

        ctx.save();
        if (link.type === 'exploited') {
          ctx.strokeStyle = '#00ff66';
          ctx.lineWidth = 2.5;
          ctx.shadowColor = '#00ff66';
          ctx.shadowBlur = 8;
        } else if (link.type === 'tunnel') {
          ctx.strokeStyle = '#38bdf8';
          ctx.setLineDash([4, 4]);
          ctx.lineWidth = 1.8;
        } else if (link.type === 'firewalled') {
          ctx.strokeStyle = '#ef4444';
          ctx.setLineDash([2, 5]);
          ctx.lineWidth = 1.2;
        } else {
          ctx.strokeStyle = 'rgba(0, 255, 102, 0.35)';
          ctx.lineWidth = 1.5;
        }

        ctx.beginPath();
        ctx.moveTo(src.x, src.y);
        ctx.lineTo(tgt.x, tgt.y);
        ctx.stroke();
        ctx.restore();

        // Animated packet dots moving along link
        if (link.activePackets) {
          const step = (packetT + (src.x * 0.01)) % 1;
          const px = src.x + (tgt.x - src.x) * step;
          const py = src.y + (tgt.y - src.y) * step;

          ctx.save();
          ctx.fillStyle = link.type === 'exploited' ? '#ffffff' : '#38bdf8';
          ctx.shadowColor = '#00ff66';
          ctx.shadowBlur = 10;
          ctx.beginPath();
          ctx.arc(px, py, 3, 0, Math.PI * 2);
          ctx.fill();
          ctx.restore();
        }
      });

      // Rotating Radar Scanner
      if (radarActive) {
        ctx.save();
        ctx.translate(460, 250);
        const radarAngle = (Date.now() / 1500) % (Math.PI * 2);
        ctx.rotate(radarAngle);

        const grad = ctx.createLinearGradient(0, 0, 320, 0);
        grad.addColorStop(0, 'rgba(0, 255, 102, 0)');
        grad.addColorStop(1, 'rgba(0, 255, 102, 0.25)');

        ctx.beginPath();
        ctx.moveTo(0, 0);
        ctx.arc(0, 0, 310, 0, Math.PI / 4);
        ctx.closePath();
        ctx.fillStyle = grad;
        ctx.fill();
        ctx.restore();
      }

      packetT = (packetT + 0.008) % 1;
      animId = requestAnimationFrame(render);
    };

    render();

    return () => cancelAnimationFrame(animId);
  }, [nodes, radarActive]);

  const handleMouseDownNode = (e: React.MouseEvent, node: NetworkNode) => {
    setSelectedNode(node);
    setDraggingNodeId(node.id);
    const rect = (e.currentTarget.parentElement as HTMLElement).getBoundingClientRect();
    setDragOffset({
      x: e.clientX - rect.left - node.x,
      y: e.clientY - rect.top - node.y,
    });
    sound.playRadarBlip();
  };

  const handleMouseMoveContainer = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!draggingNodeId) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const newX = Math.max(30, Math.min(rect.width - 60, e.clientX - rect.left - dragOffset.x));
    const newY = Math.max(30, Math.min(rect.height - 60, e.clientY - rect.top - dragOffset.y));

    setNodes((prev) =>
      prev.map((n) => (n.id === draggingNodeId ? { ...n, x: newX, y: newY } : n))
    );
  };

  const handleMouseUpContainer = () => {
    setDraggingNodeId(null);
  };

  const getNodeIcon = (type: NetworkNode['type']) => {
    switch (type) {
      case 'database':
        return <Database className="w-4 h-4" />;
      case 'gateway':
      case 'firewall':
        return <Lock className="w-4 h-4" />;
      case 'workstation':
        return <Terminal className="w-4 h-4" />;
      default:
        return <Server className="w-4 h-4" />;
    }
  };

  const getStatusColor = (status: NetworkNode['status']) => {
    switch (status) {
      case 'compromised':
        return 'border-emerald-400 bg-emerald-950 text-emerald-300 shadow-[0_0_15px_rgba(0,255,102,0.6)]';
      case 'vulnerable':
        return 'border-amber-400 bg-amber-950 text-amber-300 shadow-[0_0_12px_rgba(245,158,11,0.5)]';
      case 'unreachable':
        return 'border-rose-500 bg-rose-950 text-rose-300';
      case 'scanned':
      default:
        return 'border-sky-400 bg-sky-950 text-sky-300';
    }
  };

  const triggerNodeScan = (node: NetworkNode) => {
    sound.playExecute();
    onExecuteCommand(`Scan the host ${node.ip} for open ports and services`);
  };

  const triggerNodeExploit = (node: NetworkNode) => {
    sound.playExecute();
    onExecuteCommand(`Find SUID binaries and audit vulnerabilities on ${node.ip}`);
  };

  return (
    <div className="flex-1 flex flex-col md:flex-row h-full bg-[var(--theme-bg)] font-mono text-xs overflow-hidden select-none">
      {/* Center Interactive Topology Canvas */}
      <div
        className="flex-1 relative overflow-hidden bg-black/60 flex flex-col"
        onMouseMove={handleMouseMoveContainer}
        onMouseUp={handleMouseUpContainer}
      >
        {/* Top Floating Controls */}
        <div className="absolute top-3 left-3 z-20 flex items-center space-x-2">
          <div className="px-3 py-1.5 rounded bg-black/80 border border-[var(--theme-border)] text-xs font-bold text-[var(--theme-primary)] flex items-center space-x-2 box-glow">
            <Radio className="w-4 h-4 text-[var(--theme-primary)] animate-pulse" />
            <span>TACTICAL RECON &amp; PIVOT TOPOLOGY</span>
          </div>

          <button
            onClick={() => setRadarActive(!radarActive)}
            className={`px-2.5 py-1.5 rounded border text-[11px] font-semibold transition-all cursor-pointer ${
              radarActive
                ? 'bg-[var(--theme-primary)] text-black border-[var(--theme-primary)]'
                : 'bg-black/60 border-[var(--theme-border)] text-stone-400 hover:text-white'
            }`}
          >
            Radar: {radarActive ? 'ACTIVE' : 'OFF'}
          </button>

          <button
            onClick={() => setNodes(INITIAL_NODES)}
            className="p-1.5 rounded bg-black/60 border border-[var(--theme-border)] text-stone-400 hover:text-white transition-colors cursor-pointer"
            title="Reset Coordinates"
          >
            <RotateCcw className="w-3.5 h-3.5" />
          </button>
        </div>

        {/* Legend */}
        <div className="absolute bottom-3 left-3 z-20 bg-black/85 border border-[var(--theme-border)] rounded p-2 text-[10px] space-y-1">
          <div className="text-stone-400 font-bold mb-1">LEGEND:</div>
          <div className="flex items-center space-x-2">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-400" />
            <span className="text-stone-300">Compromised / Pivoted Host</span>
          </div>
          <div className="flex items-center space-x-2">
            <span className="w-2.5 h-2.5 rounded-full bg-amber-400" />
            <span className="text-stone-300">Vulnerable Target</span>
          </div>
          <div className="flex items-center space-x-2">
            <span className="w-2.5 h-2.5 rounded-full bg-sky-400" />
            <span className="text-stone-300">Scanned Node</span>
          </div>
          <div className="flex items-center space-x-2">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-500" />
            <span className="text-stone-300">Untrusted / External</span>
          </div>
        </div>

        {/* Canvas for links, radar, grid */}
        <canvas
          ref={canvasRef}
          width={920}
          height={550}
          className="absolute inset-0 w-full h-full pointer-events-none"
        />

        {/* HTML Draggable Nodes Overlay */}
        <div className="absolute inset-0 w-full h-full pointer-events-auto">
          {nodes.map((node) => {
            const isSelected = selectedNode?.id === node.id;
            return (
              <div
                key={node.id}
                style={{ left: `${node.x}px`, top: `${node.y}px` }}
                onMouseDown={(e) => handleMouseDownNode(e, node)}
                className={`absolute -translate-x-1/2 -translate-y-1/2 p-2 rounded-lg border-2 cursor-grab active:cursor-grabbing transition-transform ${
                  isSelected ? 'scale-110 z-20 ring-2 ring-white/90' : 'z-10 hover:scale-105'
                } ${getStatusColor(node.status)}`}
              >
                <div className="flex items-center space-x-1.5">
                  {getNodeIcon(node.type)}
                  <span className="font-bold text-xs">{node.ip}</span>
                </div>
                <div className="text-[10px] opacity-80 truncate max-w-[130px]">{node.hostname}</div>
                {node.isPivoted && (
                  <div className="text-[9px] mt-0.5 px-1 rounded bg-black/60 text-emerald-400 font-bold uppercase tracking-wider text-center">
                    PIVOT BEACON
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Right Drawer: Node Telemetry & Attack Surface */}
      <div className="w-full md:w-80 border-l border-[var(--theme-border)] bg-[var(--theme-surface)]/95 flex flex-col p-4 overflow-y-auto">
        {selectedNode ? (
          <div className="space-y-4">
            {/* Header */}
            <div className="border-b border-[var(--theme-border)] pb-3">
              <div className="flex items-center justify-between">
                <span className="text-stone-400 text-[11px] font-mono">TARGET TELEMETRY</span>
                <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                  selectedNode.status === 'compromised' ? 'bg-emerald-950 text-emerald-400' : 'bg-amber-950 text-amber-400'
                }`}>
                  {selectedNode.status}
                </span>
              </div>
              <h3 className="text-base font-bold text-[var(--theme-primary)] glow-primary mt-1">
                {selectedNode.ip}
              </h3>
              <div className="text-xs text-stone-300 font-mono">{selectedNode.hostname}</div>
              <div className="text-[11px] text-stone-500 font-mono mt-0.5">OS: {selectedNode.os}</div>
            </div>

            {/* Services & Open Ports */}
            <div>
              <div className="flex items-center justify-between text-xs font-semibold text-stone-300 mb-2">
                <span>Discovered Services ({selectedNode.ports.length})</span>
                <Wifi className="w-3.5 h-3.5 text-[var(--theme-primary)]" />
              </div>
              <div className="space-y-1.5">
                {selectedNode.services.map((svc, i) => (
                  <div key={i} className="p-2 rounded bg-black/50 border border-[var(--theme-border)] text-xs">
                    <div className="flex items-center justify-between font-mono">
                      <span className="text-[var(--theme-primary)] font-bold">Port {svc.port}</span>
                      <span className="text-stone-300">{svc.name}</span>
                    </div>
                    <div className="text-[11px] text-stone-400 mt-0.5">{svc.version}</div>
                    {svc.cve && (
                      <div className="mt-1 flex items-center space-x-1 text-rose-400 font-bold text-[10px] bg-rose-950/60 p-1 rounded border border-rose-900/60">
                        <ShieldAlert className="w-3.5 h-3.5 shrink-0" />
                        <span>CVE: {svc.cve}</span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            {/* Quick Agent Actions */}
            <div className="border-t border-[var(--theme-border)] pt-3 space-y-2">
              <span className="text-stone-400 text-xs font-semibold block">Agent-Reach Directives:</span>
              
              <button
                onClick={() => triggerNodeScan(selectedNode)}
                className="w-full flex items-center justify-center space-x-2 py-2 rounded bg-black/50 border border-[var(--theme-border)] hover:bg-[var(--theme-border)] text-[var(--theme-primary)] font-semibold transition-all cursor-pointer"
              >
                <Crosshair className="w-3.5 h-3.5" />
                <span>AI SYN Scan Port Range</span>
              </button>

              <button
                onClick={() => triggerNodeExploit(selectedNode)}
                className="w-full flex items-center justify-center space-x-2 py-2 rounded bg-[var(--theme-primary)] text-black font-semibold hover:opacity-90 transition-opacity cursor-pointer"
              >
                <Zap className="w-3.5 h-3.5" />
                <span>Audit Vulnerabilities (AI Consensus)</span>
              </button>

              <button
                onClick={() => {
                  sound.playExecute();
                  onExecuteCommand(`tshark -i eth0 -a duration:10 -Y "ip.addr == ${selectedNode.ip}" -w /out/captures/${selectedNode.ip}-traffic.pcap`);
                }}
                className="w-full flex items-center justify-center space-x-2 py-2 rounded bg-black/40 border border-stone-700 text-stone-300 hover:text-white transition-colors cursor-pointer text-xs"
              >
                <Terminal className="w-3.5 h-3.5" />
                <span>Sniff Node Packets (.pcap)</span>
              </button>
            </div>
          </div>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-center text-stone-500">
            <Server className="w-10 h-10 mb-2 opacity-30 text-[var(--theme-primary)]" />
            <p className="text-xs">Click or drag any node on the radar topology to inspect attack surface telemetry</p>
          </div>
        )}
      </div>
    </div>
  );
};
