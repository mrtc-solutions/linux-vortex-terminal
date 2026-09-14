/* Tactical Map — renders the REAL asset graph from the sidecar:
   engagements -> targets, operations -> tools, sessions -> locations.
   No staged hosts, no invented CVEs. Empty graph = honest empty state. */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Crosshair, Database, Globe, MonitorSmartphone, RefreshCw, Server, ShieldAlert, Wrench, Zap } from 'lucide-react';
import { JsonRecord, getAssetGraph, listFindings } from '../services/vortexApi';
import { sound } from '../services/soundEffects';

interface TacticalMapProps {
  onExecuteCommand: (cmd: string) => void;
  onNavigateToOut?: () => void;
}

interface GraphNode extends JsonRecord {
  id: string;
  label: string;
  type: string;
}

interface GraphEdge extends JsonRecord {
  source: string;
  target: string;
  relationship: string;
}

const TYPE_ORDER = ['engagement', 'ip', 'target', 'operation', 'tool', 'session', 'location'];

function nodeColor(type: string): string {
  switch (type) {
    case 'engagement': return '#c084fc';
    case 'ip':
    case 'target': return '#f59e0b';
    case 'operation': return '#00f0ff';
    case 'tool': return '#00ff66';
    case 'session': return '#ff3366';
    default: return '#a8a29e';
  }
}

function TypeIcon({ type }: { type: string }) {
  const cls = 'w-3.5 h-3.5';
  switch (type) {
    case 'engagement': return <Crosshair className={cls} />;
    case 'ip':
    case 'target': return <Globe className={cls} />;
    case 'operation': return <Zap className={cls} />;
    case 'tool': return <Wrench className={cls} />;
    case 'session': return <MonitorSmartphone className={cls} />;
    case 'location': return <Database className={cls} />;
    default: return <Server className={cls} />;
  }
}

export const TacticalMap: React.FC<TacticalMapProps> = ({ onExecuteCommand }) => {
  const [nodes, setNodes] = useState<GraphNode[]>([]);
  const [edges, setEdges] = useState<GraphEdge[]>([]);
  const [findings, setFindings] = useState<JsonRecord[]>([]);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    setError('');
    try {
      const [graphPayload, findingsPayload] = await Promise.all([getAssetGraph(), listFindings()]);
      const graph = (graphPayload.graph || {}) as JsonRecord;
      setNodes((Array.isArray(graph.nodes) ? graph.nodes : []) as GraphNode[]);
      setEdges((Array.isArray(graph.edges) ? graph.edges : []) as GraphEdge[]);
      setFindings(Array.isArray(findingsPayload.findings) ? findingsPayload.findings as JsonRecord[] : []);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const positions = useMemo(() => {
    const map = new Map<string, { x: number; y: number }>();
    const groups = new Map<string, GraphNode[]>();
    for (const node of nodes) {
      const list = groups.get(node.type) || [];
      list.push(node);
      groups.set(node.type, list);
    }
    const ordered = [...groups.entries()].sort(
      ([a], [b]) => TYPE_ORDER.indexOf(a) - TYPE_ORDER.indexOf(b),
    );
    const width = 900;
    const height = 520;
    ordered.forEach(([type, list], column) => {
      const x = 90 + column * ((width - 160) / Math.max(1, ordered.length - 1 || 1));
      list.forEach((node, row) => {
        const y = 60 + (row + 0.5) * ((height - 120) / list.length);
        void type;
        map.set(node.id, { x, y });
      });
    });
    return map;
  }, [nodes]);

  const selectedEdges = useMemo(() => {
    if (!selected) return [];
    return edges.filter((edge) => edge.source === selected.id || edge.target === selected.id);
  }, [edges, selected]);

  const assess = (label: string) => {
    sound.playExecute();
    onExecuteCommand(`Assess ${label} — plan only what my engagement scope authorizes`);
  };

  return (
    <div className="flex-1 flex flex-col lg:flex-row overflow-hidden bg-[var(--theme-bg)] font-mono text-xs">
      {/* Graph canvas */}
      <div className="flex-1 flex flex-col overflow-hidden relative">
        <div className="flex items-center gap-2 px-4 py-2 border-b border-[var(--theme-border)] bg-[var(--theme-surface)]/70">
          <span className="font-bold text-stone-200">ASSET GRAPH</span>
          <span className="text-stone-500">
            {nodes.length} nodes · {edges.length} links · {findings.length} findings
          </span>
          <span className="flex-1" />
          <button
            onClick={() => { setLoading(true); void refresh(); sound.playRadarBlip(); }}
            className="flex items-center gap-1 px-2 py-0.5 rounded border border-[var(--theme-border)] text-stone-300 hover:text-[var(--theme-primary)] cursor-pointer"
          >
            <RefreshCw className="w-3 h-3" />
            <span>Refresh</span>
          </button>
        </div>

        {error && (
          <div className="m-4 p-2.5 rounded bg-rose-950/20 border border-rose-900/40 text-rose-400 whitespace-pre-wrap">
            {error}
          </div>
        )}

        {loading && nodes.length === 0 ? (
          <div className="flex-1 flex items-center justify-center text-stone-500">Reading the asset graph…</div>
        ) : nodes.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center gap-2 text-center p-6">
            <Globe className="w-8 h-8 text-stone-700" />
            <div className="font-bold text-stone-300">No assets recorded yet</div>
            <div className="text-stone-500 max-w-md leading-relaxed">
              The graph grows from real work: authorize targets in Scope, run turns in the terminal, open shells.
              Nothing is drawn until it actually exists.
            </div>
          </div>
        ) : (
          <div className="flex-1 overflow-auto p-4">
            <svg viewBox="0 0 900 520" className="w-full h-full min-h-[420px] select-none">
              {edges.map((edge, index) => {
                const from = positions.get(edge.source);
                const to = positions.get(edge.target);
                if (!from || !to) return null;
                const active = selected && (edge.source === selected.id || edge.target === selected.id);
                return (
                  <g key={index} opacity={selected && !active ? 0.25 : 1}>
                    <line
                      x1={from.x} y1={from.y} x2={to.x} y2={to.y}
                      stroke={active ? 'var(--theme-primary)' : '#44403c'}
                      strokeWidth={active ? 2 : 1}
                    />
                    <text
                      x={(from.x + to.x) / 2} y={(from.y + to.y) / 2 - 4}
                      fill={active ? 'var(--theme-primary)' : '#57534e'}
                      fontSize="9" textAnchor="middle" fontFamily="monospace"
                    >
                      {String(edge.relationship || '')}
                    </text>
                  </g>
                );
              })}
              {nodes.map((node) => {
                const pos = positions.get(node.id);
                if (!pos) return null;
                const color = nodeColor(node.type);
                const active = selected?.id === node.id;
                return (
                  <g
                    key={node.id}
                    transform={`translate(${pos.x},${pos.y})`}
                    onClick={() => { setSelected(node); sound.playKeypress(); }}
                    className="cursor-pointer"
                    opacity={selected && !active && !selectedEdges.some((e) => e.source === node.id || e.target === node.id) ? 0.35 : 1}
                  >
                    <circle r={active ? 22 : 17} fill="#000" stroke={color} strokeWidth={active ? 2.5 : 1.5} />
                    <circle r={5} fill={color} opacity={0.9} />
                    <text y={34} fill={active ? '#fff' : '#a8a29e'} fontSize="10" textAnchor="middle" fontFamily="monospace">
                      {node.label.slice(0, 22)}
                    </text>
                    <text y={46} fill="#57534e" fontSize="8" textAnchor="middle" fontFamily="monospace">
                      {node.type}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>
        )}
      </div>

      {/* Detail panel */}
      <div className="w-full lg:w-80 shrink-0 border-t lg:border-t-0 lg:border-l border-[var(--theme-border)] bg-[var(--theme-surface)]/60 overflow-y-auto p-4 space-y-3">
        <div className="text-[10px] uppercase tracking-wider text-stone-500 font-semibold">Node detail</div>
        {!selected ? (
          <div className="text-stone-500 text-[11px] leading-relaxed">
            Click any node to inspect what the sidecar actually recorded about it.
          </div>
        ) : (
          <div className="p-2.5 rounded bg-black/60 border border-[var(--theme-border)] space-y-1.5">
            <div className="flex items-center gap-2">
              <span style={{ color: nodeColor(selected.type) }}><TypeIcon type={selected.type} /></span>
              <span className="font-bold text-stone-100 break-all">{selected.label}</span>
            </div>
            <div className="text-[11px] text-stone-400 space-y-0.5">
              <div><span className="text-stone-600">type:</span> {selected.type}</div>
              <div className="break-all"><span className="text-stone-600">id:</span> {selected.id}</div>
              {selected.status ? <div><span className="text-stone-600">status:</span> {String(selected.status)}</div> : null}
              {selected.count != null ? <div><span className="text-stone-600">observations:</span> {String(selected.count)}</div> : null}
            </div>
            {selectedEdges.length > 0 && (
              <div className="text-[10px] text-stone-500 space-y-0.5 pt-1 border-t border-[var(--theme-border)]/50">
                {selectedEdges.slice(0, 12).map((edge, index) => (
                  <div key={index} className="break-all">
                    {edge.source === selected.id ? '→' : '←'} {String(edge.relationship)}{' '}
                    {String(edge.source === selected.id ? edge.target : edge.source).slice(0, 40)}
                  </div>
                ))}
              </div>
            )}
            {(selected.type === 'ip' || selected.type === 'target') && (
              <button
                onClick={() => assess(selected.label)}
                className="w-full mt-1 px-2 py-1.5 rounded bg-[var(--theme-primary)] text-black font-bold hover:opacity-90 cursor-pointer"
              >
                Plan assessment of {selected.label.slice(0, 24)}
              </button>
            )}
          </div>
        )}

        <div className="text-[10px] uppercase tracking-wider text-stone-500 font-semibold pt-2">
          Findings ({findings.length})
        </div>
        {findings.length === 0 ? (
          <div className="text-stone-500 text-[11px] flex items-start gap-1.5">
            <ShieldAlert className="w-3.5 h-3.5 mt-0.5 shrink-0" />
            <span>No findings recorded. Completed assessments file them here.</span>
          </div>
        ) : (
          <div className="space-y-1.5">
            {findings.slice(0, 50).map((finding, index) => (
              <div key={index} className="p-2 rounded bg-black/60 border border-[var(--theme-border)] text-[11px] text-stone-300">
                <div className="font-bold text-stone-100">{String(finding.title || finding.kind || `finding ${index + 1}`)}</div>
                {finding.severity ? <div className="text-amber-300">severity: {String(finding.severity)}</div> : null}
                {finding.detail ? <div className="text-stone-400 whitespace-pre-wrap">{String(finding.detail).slice(0, 400)}</div> : null}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
