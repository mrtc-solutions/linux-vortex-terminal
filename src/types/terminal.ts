export type ThemeMode = 'matrix' | 'amber' | 'cyan' | 'crimson' | 'violet';

export interface LocalModel {
  id: string;
  name: string;
  tag: string;
  parameters: string;
  quantization: string;
  role: 'reasoning' | 'translator' | 'auditor';
  vramUsageMB: number;
  latencyMs: number;
  tokensPerSec: number;
  status: 'online' | 'inferring' | 'idle';
  color: string;
}

export interface FuzzyMembership {
  label: string;
  range: [number, number, number]; // [a, b, c] for triangular
  value: number; // membership degree 0-1
}

export interface FuzzyVariable {
  name: string;
  score: number; // raw input 0-100
  memberships: FuzzyMembership[];
}

export interface FuzzyRule {
  id: string;
  rule: string;
  weight: number;
  fired: boolean;
}

export interface FuzzyConsensusResult {
  confidenceVar: FuzzyVariable;
  precisionVar: FuzzyVariable;
  safetyVar: FuzzyVariable;
  rules: FuzzyRule[];
  centroid: number; // Defuzzified score 0 - 100
  recommendation: 'EXECUTE_OPTIMAL' | 'EXECUTE_SANDBOXED' | 'SAFETY_INTERLOCK_REQUIRED' | 'REJECT';
  explanation: string;
  deliberations: {
    modelId: string;
    modelName: string;
    thought: string;
    rawOutput: string;
    confidence: number;
  }[];
}

export interface AgentReachCapability {
  name: string;
  level: 'RESTRICTED' | 'SANDBOX_JAIL' | 'USERLAND' | 'RAW_SOCKETS' | 'ROOT_CAP_SYS_ADMIN';
  active: boolean;
  blastRadius: 'NEGLIGIBLE' | 'LOW' | 'MEDIUM' | 'HIGH';
}

export interface TerminalLine {
  id: string;
  timestamp: string;
  type: 'input' | 'output' | 'ai_orchestration' | 'error' | 'warning' | 'success' | 'system' | 'table';
  content: string;
  rawCommand?: string;
  translatedCommand?: string;
  orchestration?: FuzzyConsensusResult;
  tableData?: { headers: string[]; rows: (string | number)[][] };
  meta?: {
    modelName?: string;
    executionTimeMs?: number;
    exitCode?: number;
    reachLevel?: string;
    fileArtifactCreated?: string;
  };
}

export interface OutFileArtifact {
  id: string;
  path: string;
  filename: string;
  category: 'reports' | 'scans' | 'captures' | 'creds' | 'payloads' | 'logs';
  size: number; // in bytes
  createdAt: string;
  content: string;
  description: string;
  tags: string[];
}

export interface NetworkNode {
  id: string;
  ip: string;
  hostname: string;
  subnet: string;
  type: 'gateway' | 'target_server' | 'database' | 'pivot_host' | 'workstation' | 'firewall';
  status: 'scanned' | 'vulnerable' | 'compromised' | 'unreachable';
  os: string;
  ports: number[];
  services: { port: number; name: string; version: string; cve?: string }[];
  x: number;
  y: number;
  isPivoted?: boolean;
}

export interface NetworkLink {
  source: string;
  target: string;
  type: 'ethernet' | 'tunnel' | 'firewalled' | 'exploited';
  latency: number;
  activePackets?: boolean;
}

export interface VulnerabilityFinding {
  id: string;
  title: string;
  severity: 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO';
  cvss: number;
  target: string;
  port?: number;
  cve?: string;
  description: string;
  remediation: string;
  discoveredVia: string;
}

export interface PentestReport {
  id: string;
  title: string;
  targetScope: string;
  generatedAt: string;
  auditor: string;
  orchestrationEngines: string[];
  executiveSummary: string;
  riskScore: number;
  findings: VulnerabilityFinding[];
  commandsExecuted: string[];
  artifactsGenerated: string[];
}
