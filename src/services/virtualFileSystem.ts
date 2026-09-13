import { OutFileArtifact } from '../types/terminal';

export interface VFile {
  name: string;
  type: 'file' | 'directory';
  content?: string;
  size?: number;
  permissions: string;
  owner: string;
  modified: string;
  children?: { [key: string]: VFile };
  category?: OutFileArtifact['category'];
  description?: string;
}

export class VirtualFileSystem {
  private root: VFile;
  private currentPath: string = '/home/ghost';

  constructor() {
    this.root = this.initializeDefaultFS();
  }

  private initializeDefaultFS(): VFile {
    return {
      name: '/',
      type: 'directory',
      permissions: 'drwxr-xr-x',
      owner: 'root',
      modified: '2025-05-14 09:00',
      children: {
        bin: {
          name: 'bin',
          type: 'directory',
          permissions: 'drwxr-xr-x',
          owner: 'root',
          modified: '2025-05-10 12:00',
          children: {
            bash: { name: 'bash', type: 'file', permissions: '-rwxr-xr-x', owner: 'root', size: 1218000, modified: '2025-04-01 10:00' },
            nmap: { name: 'nmap', type: 'file', permissions: '-rwxr-xr-x', owner: 'root', size: 5410000, modified: '2025-04-12 11:20' },
            tshark: { name: 'tshark', type: 'file', permissions: '-rwxr-xr-x', owner: 'root', size: 3200000, modified: '2025-04-10 14:15' },
            hydra: { name: 'hydra', type: 'file', permissions: '-rwxr-xr-x', owner: 'root', size: 890000, modified: '2025-04-05 08:30' },
            sqlmap: { name: 'sqlmap', type: 'file', permissions: '-rwxr-xr-x', owner: 'root', size: 2100000, modified: '2025-04-18 16:40' },
            hashcat: { name: 'hashcat', type: 'file', permissions: '-rwxr-xr-x', owner: 'root', size: 4800000, modified: '2025-04-02 09:10' },
            agentctl: { name: 'agentctl', type: 'file', permissions: '-rwsr-xr-x', owner: 'root', size: 1420000, modified: '2025-05-12 15:30' },
          },
        },
        etc: {
          name: 'etc',
          type: 'directory',
          permissions: 'drwxr-xr-x',
          owner: 'root',
          modified: '2025-05-12 10:11',
          children: {
            passwd: {
              name: 'passwd',
              type: 'file',
              permissions: '-rw-r--r--',
              owner: 'root',
              size: 2154,
              modified: '2025-05-10 08:00',
              content: `root:x:0:0:root:/root:/bin/bash\ndaemon:x:1:1:daemon:/usr/sbin:/usr/sbin/nologin\nbin:x:2:2:bin:/bin:/usr/sbin/nologin\nsys:x:3:3:sys:/dev:/usr/sbin/nologin\nghost:x:1000:1000:Ghost SecOps Auditor,,,:/home/ghost:/bin/bash\nollama:x:998:998:Ollama Local LLM Daemon:/usr/share/ollama:/bin/false\nagent:x:999:999:Autonomous Reach Agent:/var/lib/agent:/bin/bash`,
            },
            'hosts': {
              name: 'hosts',
              type: 'file',
              permissions: '-rw-r--r--',
              owner: 'root',
              size: 320,
              modified: '2025-05-10 08:00',
              content: `127.0.0.1 localhost\n127.0.1.1 spectre-workstation\n192.168.1.1 gateway.corp.lan\n192.168.1.15 auth-srv01.corp.lan\n192.168.1.42 db-vault-primary.internal\n192.168.1.99 dmz-proxy.corp.lan`,
            },
            'shadow': {
              name: 'shadow',
              type: 'file',
              permissions: '-rw-r-----',
              owner: 'root',
              size: 1420,
              modified: '2025-05-10 08:00',
              content: `root:$6$X9qW4z8...:19840:0:99999:7:::\nghost:$6$98KqLmP...:19840:0:99999:7:::\nagent:$6$7F2aa9C...:19840:0:99999:7:::`,
            },
          },
        },
        var: {
          name: 'var',
          type: 'directory',
          permissions: 'drwxr-xr-x',
          owner: 'root',
          modified: '2025-05-12 10:11',
          children: {
            log: {
              name: 'log',
              type: 'directory',
              permissions: 'drwxr-xr-x',
              owner: 'root',
              modified: '2025-05-14 09:30',
              children: {
                'auth.log': {
                  name: 'auth.log',
                  type: 'file',
                  permissions: '-rw-r-----',
                  owner: 'root',
                  size: 8940,
                  modified: '2025-05-14 09:44',
                  content: `May 14 09:21:04 spectre sshd[2841]: Failed password for invalid user admin from 198.51.100.44 port 48211 ssh2\nMay 14 09:21:07 spectre sshd[2844]: Failed password for invalid user test from 198.51.100.44 port 48218 ssh2\nMay 14 09:21:12 spectre sshd[2850]: Failed password for root from 198.51.100.44 port 48226 ssh2\nMay 14 09:22:15 spectre sudo: ghost : TTY=pts/1 ; PWD=/home/ghost ; USER=root ; COMMAND=/bin/agentctl --status\nMay 14 09:35:10 spectre sshd[3102]: Accepted publickey for ghost from 192.168.1.80 port 52104 ssh2`,
                },
                'agent_reach.log': {
                  name: 'agent_reach.log',
                  type: 'file',
                  permissions: '-rw-r--r--',
                  owner: 'agent',
                  size: 4520,
                  modified: '2025-05-14 09:45',
                  content: `[2025-05-14 09:30:01] AGENT_REACH: Local LLM cluster linked. DeepSeek-R1 [OK], Llama-3.3 [OK], Mistral-Nemo [OK].\n[2025-05-14 09:31:14] AGENT_REACH: Fuzzy consensus engine armed. Centroid threshold: 75.0%.\n[2025-05-14 09:35:00] AGENT_REACH: Out folder initialized at /out with auto-archive write-through.`,
                },
              },
            },
          },
        },
        home: {
          name: 'home',
          type: 'directory',
          permissions: 'drwxr-xr-x',
          owner: 'root',
          modified: '2025-05-10 10:00',
          children: {
            ghost: {
              name: 'ghost',
              type: 'directory',
              permissions: 'drwxr-xr-x',
              owner: 'ghost',
              modified: '2025-05-14 09:50',
              children: {
                'targets.txt': {
                  name: 'targets.txt',
                  type: 'file',
                  permissions: '-rw-r--r--',
                  owner: 'ghost',
                  size: 198,
                  modified: '2025-05-14 08:30',
                  content: `# Authorized Engagement Scope - ACME Corp Internal Network\n192.168.1.1/24\n192.168.1.1    # Edge Firewall & Gateway\n192.168.1.15   # Corp Active Directory & LDAP\n192.168.1.42   # Financial DB (Postgres)\n192.168.1.99   # Public NGINX Reverse Proxy`,
                },
                'scope.md': {
                  name: 'scope.md',
                  type: 'file',
                  permissions: '-rw-r--r--',
                  owner: 'ghost',
                  size: 612,
                  modified: '2025-05-13 14:00',
                  content: `# Rules of Engagement\n- Type: Grey-Box Ethical Penetration Test\n- Permitted Windows: 08:00 - 20:00 UTC\n- Safe Havens: 192.168.1.200 (Medical SCADA - DO NOT TOUCH)\n- Local LLMs: DeepSeek-R1 (Tactical), Llama-3.3 (Shell/CLI), Mistral-Nemo (Safety)\n- Artifact Storage: Write all scan outputs to /out`,
                },
                'agent_config.yaml': {
                  name: 'agent_config.yaml',
                  type: 'file',
                  permissions: '-rw-r--r--',
                  owner: 'ghost',
                  size: 420,
                  modified: '2025-05-14 09:00',
                  content: `orchestration:\n  models:\n    - id: deepseek-r1-7b\n      role: reasoning\n    - id: llama-3.3-8b\n      role: translator\n    - id: mistral-nemo-12b\n      role: guardrail\n  fuzzy_logic:\n    algorithm: mamdani_centroid\n    auto_exec_min: 78.0\n    sandbox_min: 55.0\n  out_directory: /out\n  telemetry: full`,
                },
              },
            },
          },
        },
        // Dedicated requested /out folder that tracks artifacts & scans
        out: {
          name: 'out',
          type: 'directory',
          permissions: 'drwxrwxrwx',
          owner: 'ghost',
          modified: '2025-05-14 09:55',
          children: {
            reports: {
              name: 'reports',
              type: 'directory',
              permissions: 'drwxr-xr-x',
              owner: 'ghost',
              modified: '2025-05-14 09:55',
              children: {
                'pentest-audit-final.md': {
                  name: 'pentest-audit-final.md',
                  type: 'file',
                  category: 'reports',
                  permissions: '-rw-r--r--',
                  owner: 'ghost',
                  size: 4320,
                  modified: '2025-05-14 09:52',
                  description: 'Comprehensive grey-box vulnerability audit report for ACME Corp subnet 192.168.1.0/24.',
                  content: `# EXECUTIVE PENETRATION TESTING AUDIT REPORT
**Target Organization**: ACME Corp Cyber Infrastructure
**Lead Auditor**: Ghost (Agentic AI Security Station v4.9.2)
**Multi-LLM Consensus**: DeepSeek-R1 + Llama-3.3 + Mistral-Nemo (Fuzzy Score: 93.8%)
**Date**: May 14, 2025

---

## 1. Executive Summary
During the Grey-Box assessment, the automated agent discovered 3 critical vulnerabilities across internal hosts:
1. **CVE-2023-38606** on Edge Gateway (192.168.1.1) - Unauthenticated Remote Code Execution.
2. **PostgreSQL Weak Salt & Hash Reuse** on DB Vault (192.168.1.42).
3. **Misconfigured SUID Binaries** on Internal Jumpbox (192.168.1.15).

## 2. Exploitation Path & Agent Reach
- Host 192.168.1.1 was identified via SYN stealth sweep.
- Multi-LLM orchestrated non-destructive payload validation.
- Sandboxed execution confirmed read-access privilege boundary.

## 3. Remediation Road Map
- Patch Edge gateway to firmware v12.4.9 immediately.
- Enforce Argon2id password hashing on PostgreSQL 15.
- Restrict SUID bit on /usr/bin/find and /usr/bin/python3.`,
                },
                'executive-summary.json': {
                  name: 'executive-summary.json',
                  type: 'file',
                  category: 'reports',
                  permissions: '-rw-r--r--',
                  owner: 'ghost',
                  size: 1540,
                  modified: '2025-05-14 09:54',
                  description: 'Structured JSON findings format for SIEM/Jira vulnerability ticketing integration.',
                  content: JSON.stringify({
                    engagement: "ACME Corp Red-Team Audit",
                    riskScore: 8.8,
                    severityBreakdown: { critical: 2, high: 3, medium: 4, low: 2 },
                    auditedHosts: 6,
                    compromisedHosts: 2,
                    remediationTimeEstimateHours: 24,
                    orchestrationConsensus: "OPTIMAL_94_PCT"
                  }, null, 2),
                },
              },
            },
            scans: {
              name: 'scans',
              type: 'directory',
              permissions: 'drwxr-xr-x',
              owner: 'ghost',
              modified: '2025-05-14 09:40',
              children: {
                'nmap-192.168.1.0-syn.xml': {
                  name: 'nmap-192.168.1.0-syn.xml',
                  type: 'file',
                  category: 'scans',
                  permissions: '-rw-r--r--',
                  owner: 'ghost',
                  size: 5120,
                  modified: '2025-05-14 09:38',
                  description: 'XML output of full TCP port sweep across target subnet.',
                  content: `<?xml version="1.0" encoding="UTF-8"?>
<nmaprun scanner="nmap" args="nmap -sS -sV -O -p- 192.168.1.0/24 -oA /out/scans/nmap-192.168.1.0-syn" start="1747214400">
  <host starttime="1747214402" endtime="1747214435">
    <status state="up" reason="arp-response"/>
    <address addr="192.168.1.1" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh" product="OpenSSH 8.9p1"/></port>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http" product="nginx 1.18.0"/></port>
      <port protocol="tcp" portid="443"><state state="open"/><service name="ssl/http" product="nginx 1.18.0"/></port>
    </ports>
  </host>
  <host starttime="1747214436" endtime="1747214460">
    <status state="up" reason="arp-response"/>
    <address addr="192.168.1.42" addrtype="ipv4"/>
    <ports>
      <port protocol="tcp" portid="5432"><state state="open"/><service name="postgresql" product="PostgreSQL 14.5"/></port>
    </ports>
  </host>
</nmaprun>`,
                },
                'dirsearch-auth-srv.txt': {
                  name: 'dirsearch-auth-srv.txt',
                  type: 'file',
                  category: 'scans',
                  permissions: '-rw-r--r--',
                  owner: 'ghost',
                  size: 2130,
                  modified: '2025-05-14 09:39',
                  description: 'Web directory enumeration results for internal auth portal.',
                  content: `[09:39:10] 200 -    4KB - /admin
[09:39:11] 301 -  178B  - /login -> /login/
[09:39:12] 200 -   12KB - /swagger-ui.html
[09:39:14] 403 -  564B  - /api/v1/internal/config.env
[09:39:16] 200 -  890B  - /metrics`,
                },
              },
            },
            captures: {
              name: 'captures',
              type: 'directory',
              permissions: 'drwxr-xr-x',
              owner: 'ghost',
              modified: '2025-05-14 09:42',
              children: {
                'raw-traffic-eth0.pcap': {
                  name: 'raw-traffic-eth0.pcap',
                  type: 'file',
                  category: 'captures',
                  permissions: '-rw-r--r--',
                  owner: 'ghost',
                  size: 148200,
                  modified: '2025-05-14 09:42',
                  description: 'PCAP raw network packet capture on eth0 interface during MITM audit.',
                  content: `[PCAP BINARY STREAM: 1,482 packets recorded]
Frame 1: 74 bytes on wire, 74 bytes captured
  Ethernet II, Src: 00:0c:29:4f:8e:1a, Dst: 00:50:56:c0:00:08
  Internet Protocol Version 4, Src: 192.168.1.80, Dst: 192.168.1.1
  Transmission Control Protocol, Src Port: 54102, Dst Port: 443 [SYN] Seq=0
Frame 2: 74 bytes on wire
  Internet Protocol Version 4, Src: 192.168.1.1, Dst: 192.168.1.80
  Transmission Control Protocol, Src Port: 443, Dst Port: 54102 [SYN, ACK] Seq=0 Ack=1`,
                },
              },
            },
            creds: {
              name: 'creds',
              type: 'directory',
              permissions: 'drwxr-xr-x',
              owner: 'ghost',
              modified: '2025-05-14 09:46',
              children: {
                'cracked-hashes.txt': {
                  name: 'cracked-hashes.txt',
                  type: 'file',
                  category: 'creds',
                  permissions: '-rw-------',
                  owner: 'ghost',
                  size: 450,
                  modified: '2025-05-14 09:45',
                  description: 'Sanitized recovery output from local Hashcat NTLM dictionary test.',
                  content: `# HASHCAT CRACKED RECOVERY - SENSITIVE
# Hash: Plaintext
e832c39d8916e392:Summer2024! (User: svc_backup)
a4f9104b9012cd31:CorpAdmin123$ (User: helpdesk01)
6f78810e201bfa99:P@ssw0rd2025! (User: staging_test)`,
                },
              },
            },
            payloads: {
              name: 'payloads',
              type: 'directory',
              permissions: 'drwxr-xr-x',
              owner: 'ghost',
              modified: '2025-05-14 09:48',
              children: {
                'safe-audit-probe.py': {
                  name: 'safe-audit-probe.py',
                  type: 'file',
                  category: 'payloads',
                  permissions: '-rwxr-xr-x',
                  owner: 'ghost',
                  size: 1820,
                  modified: '2025-05-14 09:47',
                  description: 'Non-destructive Python socket probe generated by Llama-3.3 under Mistral safety guardrails.',
                  content: `#!/usr/bin/env python3
# Synthetic Non-Destructive Probe Generated by Spectre AI Orchestrator
import socket, sys

def probe(host, port):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(2.0)
        s.connect((host, port))
        s.sendall(b"HEAD / HTTP/1.1\\r\\nHost: " + host.encode() + b"\\r\\n\\r\\n")
        banner = s.recv(1024)
        print(f"[+] Active Banner on {host}:{port}: {banner.decode('utf-8', errors='ignore').splitlines()[0]}")
        s.close()
    except Exception as e:
        print(f"[-] Connection failed: {e}")

if __name__ == '__main__':
    probe("192.168.1.1", 80)
`,
                },
              },
            },
          },
        },
      },
    };
  }

  public getPwd(): string {
    return this.currentPath;
  }

  public setPwd(path: string): boolean {
    const node = this.resolveNode(path);
    if (node && node.type === 'directory') {
      this.currentPath = this.normalizePath(path);
      return true;
    }
    return false;
  }

  public normalizePath(path: string): string {
    if (path.startsWith('/')) {
      const parts = path.split('/').filter(Boolean);
      const stack: string[] = [];
      for (const p of parts) {
        if (p === '.') continue;
        if (p === '..') {
          stack.pop();
        } else {
          stack.push(p);
        }
      }
      return '/' + stack.join('/');
    } else {
      const full = this.currentPath + '/' + path;
      return this.normalizePath(full);
    }
  }

  public resolveNode(path: string): VFile | null {
    const normalized = this.normalizePath(path);
    if (normalized === '/' || normalized === '') return this.root;
    const parts = normalized.split('/').filter(Boolean);
    let curr = this.root;
    for (const part of parts) {
      if (!curr.children || !curr.children[part]) {
        return null;
      }
      curr = curr.children[part];
    }
    return curr;
  }

  public listDirectory(path: string = this.currentPath): { name: string; node: VFile }[] | null {
    const dir = this.resolveNode(path);
    if (!dir || dir.type !== 'directory' || !dir.children) return null;
    return Object.entries(dir.children).map(([name, node]) => ({ name, node }));
  }

  public readFile(path: string): string | null {
    const node = this.resolveNode(path);
    if (!node || node.type !== 'file') return null;
    return node.content || '';
  }

  public writeFile(path: string, content: string, category: OutFileArtifact['category'] = 'scans', description: string = ''): boolean {
    const normalized = this.normalizePath(path);
    const parts = normalized.split('/').filter(Boolean);
    if (parts.length === 0) return false;
    const fileName = parts.pop()!;
    const parentPath = '/' + parts.join('/');
    
    // Ensure parent directories exist
    this.ensureDirectory(parentPath);
    const parent = this.resolveNode(parentPath);
    if (!parent || !parent.children) return false;

    const now = new Date().toISOString().replace('T', ' ').substring(0, 16);
    parent.children[fileName] = {
      name: fileName,
      type: 'file',
      permissions: '-rw-r--r--',
      owner: 'ghost',
      size: content.length,
      modified: now,
      content,
      category,
      description: description || `Generated artifact by Agent-Reach execution at ${now}`,
    };

    return true;
  }

  public ensureDirectory(path: string): boolean {
    const parts = this.normalizePath(path).split('/').filter(Boolean);
    let curr = this.root;
    for (const part of parts) {
      if (!curr.children) curr.children = {};
      if (!curr.children[part]) {
        curr.children[part] = {
          name: part,
          type: 'directory',
          permissions: 'drwxr-xr-x',
          owner: 'ghost',
          modified: new Date().toISOString().replace('T', ' ').substring(0, 16),
          children: {},
        };
      }
      curr = curr.children[part];
    }
    return true;
  }

  public getAllOutArtifacts(): OutFileArtifact[] {
    const artifacts: OutFileArtifact[] = [];
    const traverse = (node: VFile, currPath: string) => {
      if (node.type === 'file' && currPath.startsWith('/out')) {
        artifacts.push({
          id: currPath,
          path: currPath,
          filename: node.name,
          category: node.category || 'logs',
          size: node.size || (node.content ? node.content.length : 0),
          createdAt: node.modified,
          content: node.content || '',
          description: node.description || `${node.name} stored in ${currPath}`,
          tags: [node.category || 'artifact', node.name.split('.').pop() || 'file'],
        });
      }
      if (node.children) {
        for (const childName in node.children) {
          const childPath = currPath === '/' ? `/${childName}` : `${currPath}/${childName}`;
          traverse(node.children[childName], childPath);
        }
      }
    };

    traverse(this.root, '/');
    return artifacts;
  }

  public deleteArtifact(path: string): boolean {
    const normalized = this.normalizePath(path);
    const parts = normalized.split('/').filter(Boolean);
    if (parts.length === 0) return false;
    const fileName = parts.pop()!;
    const parentPath = '/' + parts.join('/');
    const parent = this.resolveNode(parentPath);
    if (parent && parent.children && parent.children[fileName]) {
      delete parent.children[fileName];
      return true;
    }
    return false;
  }
}

export const vfs = new VirtualFileSystem();
