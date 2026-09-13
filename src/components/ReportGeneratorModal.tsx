import React, { useState } from 'react';
import { vfs } from '../services/virtualFileSystem';
import { 
  FileText, 
  Download, 
  Check, 
  ShieldAlert, 
  Printer, 
  Save, 
  Award,
  Layers
} from 'lucide-react';
import { sound } from '../services/soundEffects';

interface ReportGeneratorModalProps {
  onReportSaved?: () => void;
  onNavigateToOut?: () => void;
}

export const ReportGeneratorModal: React.FC<ReportGeneratorModalProps> = ({
  onReportSaved,
  onNavigateToOut,
}) => {
  const [activeTab, setActiveTab] = useState<'preview' | 'markdown' | 'json'>('preview');
  const [targetOrg, setTargetOrg] = useState('ACME Corporation');
  const [targetScope, setTargetScope] = useState('192.168.1.0/24 (DMZ & Internal LAN)');
  const [savedSuccess, setSavedSuccess] = useState(false);

  const findings = [
    {
      id: 'FIND-001',
      title: 'Spring Framework Actuator Environment Variable Leak',
      cve: 'CVE-2022-22965',
      cvss: 9.8,
      severity: 'CRITICAL',
      target: '192.168.1.15:8080 (/actuator/env)',
      description: 'The Spring Boot actuator endpoint is publicly accessible without authentication, exposing database credentials, API keys, and environment variables.',
      remediation: 'Disable management.endpoints.web.exposure.include=* in application.properties and implement Spring Security filter chain authentication.',
    },
    {
      id: 'FIND-002',
      title: 'Insecure SUID Permission Bit on Daemon Binary',
      cve: 'CWE-250',
      cvss: 8.4,
      severity: 'HIGH',
      target: 'spectre-workstation (/bin/agentctl)',
      description: 'The agentctl binary is owned by root and has the SUID bit set (-rwsr-xr-x). It executes system subroutines without sanitizing PATH or enforcing dropped privileges.',
      remediation: 'Strip SUID permissions using chmod u-s /bin/agentctl or enforce Linux capabilities (cap_net_admin) rather than full setuid root.',
    },
    {
      id: 'FIND-003',
      title: 'Unauthenticated Edge Gateway Remote Code Execution',
      cve: 'CVE-2023-38606',
      cvss: 8.6,
      severity: 'HIGH',
      target: '192.168.1.1:443 (EdgeOS WebUI)',
      description: 'Buffer overflow in WebUI daemon allows remote code execution prior to user authentication via malformed HTTP POST payload.',
      remediation: 'Upgrade EdgeOS firmware to version 2.0.9-hotfix.7 or restrict management port 443 to internal management VLAN.',
    },
    {
      id: 'FIND-004',
      title: 'PostgreSQL Database Password Hash Weak Salt Configuration',
      cve: 'CWE-326',
      cvss: 6.5,
      severity: 'MEDIUM',
      target: '192.168.1.42:5432',
      description: 'Database user hashes stored using legacy MD5 and weak salt instead of SCRAM-SHA-256, allowing offline dictionary recovery via Hashcat.',
      remediation: 'Set password_encryption = scram-sha-256 in postgresql.conf and force all service users to rotate credentials.',
    },
  ];

  const markdownContent = `# PENETRATION TESTING & ETHICAL AUDIT REPORT
**Target Organization**: ${targetOrg}
**Scope of Assessment**: ${targetScope}
**Date Generated**: ${new Date().toLocaleDateString()}
**Lead Auditor**: Ghost SecOps (AI Agentic Workstation v4.9.2)
**Classification**: STRICTLY CONFIDENTIAL // PRIVILEGED WORK PRODUCT

---

## 1. Executive Summary
During the Grey-Box assessment of ${targetOrg}'s internal infrastructure (${targetScope}), the autonomous Agentic Linux terminal and local LLM consensus cluster identified **4 critical and high-severity security vulnerabilities**. 

An attacker positioned on the internal network could escalate privileges to root, compromise database vaults, and leak production API tokens.

### Multi-LLM Consensus Certification
- **Reasoning Engine**: DeepSeek-R1-Distill-7B (Semantic intent verified)
- **Syntax Synthesizer**: Llama-3.3-Security-8B (POSIX non-destructive payloads)
- **Safety Auditor**: Mistral-Nemo-Audit-12B (Blast radius strictly confined)
- **Fuzzy Centroid Consensus**: 94.6% (Optimal Reliability Grade)

---

## 2. Risk Matrix & Severity Summary
- **Overall CVSS Score**: 8.8 / 10.0 (HIGH RISK)
- **Critical Vulnerabilities**: 1
- **High Severity Vulnerabilities**: 2
- **Medium Severity Vulnerabilities**: 1

---

## 3. Detailed Vulnerability Findings
${findings
  .map(
    (f) => `
### [${f.id}] ${f.title}
- **Severity**: ${f.severity} (CVSS ${f.cvss})
- **CVE / CWE**: ${f.cve}
- **Target Host**: \`${f.target}\`
- **Technical Description**: ${f.description}
- **Remediation Action**: ${f.remediation}
`
  )
  .join('\n')}

---

## 4. Methodological Compliance
This ethical penetration assessment adhered to **NIST SP 800-115** (Technical Guide to Information Security Testing and Assessment) and **OWASP Testing Guide v4**. All payloads were executed under simulated sandbox jail guards without disrupting business operations.

*Report automatically synthesized and logged to /out/reports/*`;

  const jsonContent = JSON.stringify(
    {
      metadata: {
        reportId: `PENTEST-${Date.now().toString().slice(-6)}`,
        targetOrganization: targetOrg,
        scope: targetScope,
        timestamp: new Date().toISOString(),
        auditor: 'Ghost SecOps',
        orchestration: {
          models: ['DeepSeek-R1-Distill-7B', 'Llama-3.3-Security-8B', 'Mistral-Nemo-Audit-12B'],
          fuzzyConsensusScore: 94.6,
          defuzzificationMethod: 'Mamdani_Centroid',
        },
      },
      metrics: {
        overallRiskScore: 8.8,
        criticalCount: 1,
        highCount: 2,
        mediumCount: 1,
      },
      findings,
    },
    null,
    2
  );

  const handleSaveToOut = () => {
    sound.playSuccess();
    const dateStr = new Date().toISOString().slice(0, 10);
    const mdPath = `/out/reports/pentest-${dateStr}-${targetOrg.toLowerCase().replace(/\s+/g, '-')}.md`;
    const jsonPath = `/out/reports/pentest-${dateStr}-${targetOrg.toLowerCase().replace(/\s+/g, '-')}.json`;

    vfs.writeFile(mdPath, markdownContent, 'reports', `Penetration audit for ${targetOrg}`);
    vfs.writeFile(jsonPath, jsonContent, 'reports', `Structured JSON findings for ${targetOrg}`);

    setSavedSuccess(true);
    setTimeout(() => setSavedSuccess(false), 3000);
    if (onReportSaved) onReportSaved();
  };

  const handleDownloadMarkdown = () => {
    sound.playExecute();
    const blob = new Blob([markdownContent], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `pentest-report-${targetOrg.toLowerCase().replace(/\s+/g, '-')}.md`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const handleDownloadJson = () => {
    sound.playExecute();
    const blob = new Blob([jsonContent], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `pentest-report-${targetOrg.toLowerCase().replace(/\s+/g, '-')}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const handlePrint = () => {
    window.print();
  };

  return (
    <div className="flex-1 flex flex-col h-full bg-[var(--theme-bg)] font-mono text-xs overflow-hidden select-text">
      {/* Top Controls Bar */}
      <div className="bg-[var(--theme-surface)]/90 border-b border-[var(--theme-border)] px-4 py-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center space-x-3">
          <div className="p-2 rounded bg-black/50 border border-[var(--theme-border)] text-[var(--theme-primary)]">
            <FileText className="w-5 h-5" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <span className="text-sm font-bold text-[var(--theme-primary)] glow-primary">
                AUTOMATED PENETRATION TESTING REPORT GENERATOR
              </span>
              <span className="text-[10px] px-2 py-0.5 rounded bg-emerald-950 text-emerald-300 border border-emerald-800 font-bold">
                NIST SP 800-115 COMPLIANT
              </span>
            </div>
            <div className="text-[11px] text-stone-400 mt-0.5">
              Auto-compiles terminal telemetry, discovered CVEs, and multi-LLM consensus into client-ready deliverables.
            </div>
          </div>
        </div>

        {/* Global Actions */}
        <div className="flex items-center space-x-2">
          <button
            onClick={handleSaveToOut}
            className={`flex items-center space-x-1.5 px-3 py-1.5 rounded transition-all cursor-pointer font-semibold ${
              savedSuccess
                ? 'bg-emerald-600 text-white'
                : 'bg-[var(--theme-primary)] text-black hover:opacity-90'
            }`}
          >
            {savedSuccess ? <Check className="w-4 h-4" /> : <Save className="w-4 h-4" />}
            <span>{savedSuccess ? 'Saved to /out!' : 'Save into /out/reports/'}</span>
          </button>

          <button
            onClick={handleDownloadMarkdown}
            className="flex items-center space-x-1.5 px-2.5 py-1.5 rounded bg-black/50 border border-[var(--theme-border)] text-stone-300 hover:text-white transition-colors cursor-pointer"
            title="Download Markdown"
          >
            <Download className="w-3.5 h-3.5" />
            <span>.md</span>
          </button>

          <button
            onClick={handleDownloadJson}
            className="flex items-center space-x-1.5 px-2.5 py-1.5 rounded bg-black/50 border border-[var(--theme-border)] text-stone-300 hover:text-white transition-colors cursor-pointer"
            title="Download JSON"
          >
            <Download className="w-3.5 h-3.5" />
            <span>.json</span>
          </button>

          <button
            onClick={handlePrint}
            className="p-1.5 rounded bg-black/50 border border-[var(--theme-border)] text-stone-300 hover:text-white transition-colors cursor-pointer"
            title="Print Clean PDF Dossier"
          >
            <Printer className="w-4 h-4" />
          </button>

          {onNavigateToOut && (
            <button
              onClick={onNavigateToOut}
              className="text-[11px] text-[var(--theme-primary)] underline hover:opacity-80 px-2 cursor-pointer"
            >
              View /out &rarr;
            </button>
          )}
        </div>
      </div>

      {/* Scope Settings & Tab Header */}
      <div className="bg-black/40 border-b border-[var(--theme-border)] px-4 py-2 flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center space-x-1.5">
            <span className="text-stone-400">Client Org:</span>
            <input
              type="text"
              value={targetOrg}
              onChange={(e) => setTargetOrg(e.target.value)}
              className="bg-black/60 border border-[var(--theme-border)] rounded px-2 py-0.5 text-stone-200 focus:outline-none focus:border-[var(--theme-primary)] w-40"
            />
          </div>
          <div className="flex items-center space-x-1.5">
            <span className="text-stone-400">Target Subnet:</span>
            <input
              type="text"
              value={targetScope}
              onChange={(e) => setTargetScope(e.target.value)}
              className="bg-black/60 border border-[var(--theme-border)] rounded px-2 py-0.5 text-stone-200 focus:outline-none focus:border-[var(--theme-primary)] w-64"
            />
          </div>
        </div>

        {/* View Switcher Tabs */}
        <div className="flex items-center space-x-1">
          <button
            onClick={() => setActiveTab('preview')}
            className={`px-3 py-1 rounded text-xs transition-colors cursor-pointer ${
              activeTab === 'preview'
                ? 'bg-[var(--theme-primary)] text-black font-semibold'
                : 'text-stone-400 hover:text-white'
            }`}
          >
            Formatted Dossier
          </button>
          <button
            onClick={() => setActiveTab('markdown')}
            className={`px-3 py-1 rounded text-xs transition-colors cursor-pointer ${
              activeTab === 'markdown'
                ? 'bg-[var(--theme-primary)] text-black font-semibold'
                : 'text-stone-400 hover:text-white'
            }`}
          >
            Markdown Source
          </button>
          <button
            onClick={() => setActiveTab('json')}
            className={`px-3 py-1 rounded text-xs transition-colors cursor-pointer ${
              activeTab === 'json'
                ? 'bg-[var(--theme-primary)] text-black font-semibold'
                : 'text-stone-400 hover:text-white'
            }`}
          >
            JSON Schema
          </button>
        </div>
      </div>

      {/* Main Report View Body */}
      <div className="flex-1 overflow-y-auto p-6 max-w-5xl mx-auto w-full select-text">
        {activeTab === 'preview' && (
          <div className="space-y-6 bg-black/60 border border-[var(--theme-border)] rounded-lg p-6 box-glow">
            {/* Report Header Title Block */}
            <div className="border-b border-[var(--theme-border)] pb-4">
              <div className="flex justify-between items-start">
                <div>
                  <span className="text-[10px] font-bold tracking-widest text-emerald-400 uppercase bg-emerald-950/80 px-2 py-0.5 rounded border border-emerald-800">
                    CONFIDENTIAL PENETRATION AUDIT
                  </span>
                  <h1 className="text-2xl font-black text-[var(--theme-primary)] glow-primary mt-2">
                    {targetOrg} &mdash; CYBER THREAT AUDIT
                  </h1>
                  <p className="text-xs text-stone-400 mt-1">
                    Evaluated Target Scope: <code className="text-emerald-300 font-bold">{targetScope}</code>
                  </p>
                </div>
                <div className="text-right text-[11px] text-stone-400 space-y-0.5">
                  <div>Date: {new Date().toLocaleDateString()}</div>
                  <div>Auditor: <span className="text-[var(--theme-primary)] font-semibold">Ghost SecOps</span></div>
                  <div>Station: <span className="text-stone-300">NEO-HEX v4.9.2</span></div>
                </div>
              </div>

              {/* Multi-LLM Consensus Certification Badge */}
              <div className="mt-4 p-3 rounded bg-black/80 border border-[var(--theme-border)] flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center space-x-2">
                  <Award className="w-5 h-5 text-[var(--theme-primary)]" />
                  <div>
                    <span className="font-bold text-xs text-stone-200">
                      Multi-LLM Consensus Engine Verification
                    </span>
                    <div className="text-[11px] text-stone-400 flex items-center space-x-2 mt-0.5">
                      <span>DeepSeek-R1 (Reasoning)</span>
                      <span>&bull;</span>
                      <span>Llama-3.3 (Shell)</span>
                      <span>&bull;</span>
                      <span>Mistral-Nemo (Guardrail)</span>
                    </div>
                  </div>
                </div>
                <div className="flex items-center space-x-2">
                  <div className="text-right">
                    <div className="text-[10px] text-stone-400">Centroid Defuzzification</div>
                    <div className="text-lg font-black text-[var(--theme-primary)]">94.6% OPTIMAL</div>
                  </div>
                </div>
              </div>
            </div>

            {/* Risk Summary Metrics */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <div className="bg-black/50 border border-rose-900/60 rounded p-3 text-center">
                <div className="text-[10px] text-rose-400 font-bold uppercase">Critical Findings</div>
                <div className="text-2xl font-black text-rose-500 mt-1">1</div>
                <div className="text-[10px] text-stone-500">CVSS 9.0 - 10.0</div>
              </div>
              <div className="bg-black/50 border border-amber-900/60 rounded p-3 text-center">
                <div className="text-[10px] text-amber-400 font-bold uppercase">High Severity</div>
                <div className="text-2xl font-black text-amber-400 mt-1">2</div>
                <div className="text-[10px] text-stone-500">CVSS 7.0 - 8.9</div>
              </div>
              <div className="bg-black/50 border border-sky-900/60 rounded p-3 text-center">
                <div className="text-[10px] text-sky-400 font-bold uppercase">Medium Severity</div>
                <div className="text-2xl font-black text-sky-400 mt-1">1</div>
                <div className="text-[10px] text-stone-500">CVSS 4.0 - 6.9</div>
              </div>
              <div className="bg-black/50 border border-emerald-900/60 rounded p-3 text-center">
                <div className="text-[10px] text-emerald-400 font-bold uppercase">Overall Risk Rating</div>
                <div className="text-2xl font-black text-[var(--theme-primary)] mt-1">8.8</div>
                <div className="text-[10px] text-stone-500">HIGH RISK SCOPE</div>
              </div>
            </div>

            {/* Detailed Findings Table */}
            <div>
              <h2 className="text-sm font-bold text-[var(--theme-primary)] flex items-center space-x-2 mb-3">
                <ShieldAlert className="w-4 h-4" />
                <span>Identified Vulnerability Findings</span>
              </h2>

              <div className="space-y-3">
                {findings.map((f) => (
                  <div
                    key={f.id}
                    className="p-3 rounded bg-black/40 border border-[var(--theme-border)] space-y-2"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center space-x-2">
                        <span className="font-bold text-xs text-[var(--theme-primary)]">{f.id}:</span>
                        <span className="font-bold text-xs text-stone-200">{f.title}</span>
                      </div>
                      <div className="flex items-center space-x-2">
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-black font-mono text-stone-300 border border-stone-800">
                          {f.cve}
                        </span>
                        <span
                          className={`text-[10px] px-2 py-0.5 rounded font-bold uppercase ${
                            f.severity === 'CRITICAL'
                              ? 'bg-rose-950 text-rose-400 border border-rose-800'
                              : f.severity === 'HIGH'
                              ? 'bg-amber-950 text-amber-400 border border-amber-800'
                              : 'bg-sky-950 text-sky-400 border border-sky-800'
                          }`}
                        >
                          {f.severity} (CVSS {f.cvss})
                        </span>
                      </div>
                    </div>

                    <div className="text-[11px] text-stone-400 font-mono">
                      Target Host/Endpoint: <span className="text-emerald-400">{f.target}</span>
                    </div>

                    <p className="text-[11px] text-stone-300 leading-relaxed">
                      {f.description}
                    </p>

                    <div className="p-2 rounded bg-black/60 border border-stone-800 text-[11px] text-stone-300">
                      <span className="text-[var(--theme-primary)] font-bold">Remediation Action: </span>
                      <span>{f.remediation}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Remediation Priority Roadmap */}
            <div className="border-t border-[var(--theme-border)] pt-4">
              <h2 className="text-sm font-bold text-[var(--theme-primary)] flex items-center space-x-2 mb-2">
                <Layers className="w-4 h-4" />
                <span>Executive Remediation Roadmap</span>
              </h2>
              <ol className="list-decimal list-inside space-y-1.5 text-stone-300 text-xs">
                <li><strong className="text-rose-400">Immediate (24 hours):</strong> Disable Spring Boot actuator <code className="text-emerald-400">/actuator/env</code> to halt API key exfiltration.</li>
                <li><strong className="text-amber-400">Urgent (48 hours):</strong> Update Edge gateway firmware to address CVE-2023-38606 remote code execution.</li>
                <li><strong className="text-amber-400">Urgent (72 hours):</strong> Revoke setuid permissions on <code className="text-emerald-400">/bin/agentctl</code> to seal root privilege escalation vector.</li>
                <li><strong className="text-stone-300">Scheduled (14 days):</strong> Migrate PostgreSQL password storage hashes to SCRAM-SHA-256.</li>
              </ol>
            </div>
          </div>
        )}

        {activeTab === 'markdown' && (
          <div className="bg-black/70 border border-[var(--theme-border)] rounded-lg p-4 font-mono text-xs text-stone-200">
            <pre className="whitespace-pre-wrap">{markdownContent}</pre>
          </div>
        )}

        {activeTab === 'json' && (
          <div className="bg-black/70 border border-[var(--theme-border)] rounded-lg p-4 font-mono text-xs text-emerald-400">
            <pre className="whitespace-pre-wrap">{jsonContent}</pre>
          </div>
        )}
      </div>
    </div>
  );
};
