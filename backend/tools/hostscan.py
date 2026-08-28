"""Live Kali/Linux host-tool discovery.

VORTEX's builtin catalog is reviewed and finite. Operators on Kali (and other
Linux hosts) install additional tools after VORTEX starts. This module:

- walks only PATH directories that are safe for managed execution;
- classifies well-known Kali/Linux security tools;
- reports newly installed binaries since the last scan;
- never fabricates availability.

Planning a discovered tool still requires ``host_tool_access`` (an explicit
operator setting) and still goes through Guardian, typed argv, and the
engagement gate for outbound work. Interpreters and destructive binaries are
not planned from natural language.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import stat
import time
from pathlib import Path
from typing import Any

CONTROLLED_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Well-known Kali / Debian-security tools. Presence is probed; absence stays
# UNAVAILABLE. Licenses are attributed for operator awareness, not vendored.
KALI_CATALOG: dict[str, dict[str, Any]] = {
    "nmap": {"family": "authorized-reconnaissance", "role": "scoped service discovery", "network": "outbound-read", "risk": "high", "license": "NPSL"},
    "ncat": {"family": "network", "role": "ncat connectivity", "network": "outbound-read", "risk": "high", "license": "NPSL"},
    "nping": {"family": "network", "role": "packet generation", "network": "outbound-read", "risk": "high", "license": "NPSL"},
    "masscan": {"family": "authorized-reconnaissance", "role": "fast port scan", "network": "outbound-read", "risk": "high", "license": "AGPL-3.0"},
    "rustscan": {"family": "authorized-reconnaissance", "role": "port discovery", "network": "outbound-read", "risk": "high", "license": "GPL-3.0"},
    "netdiscover": {"family": "authorized-reconnaissance", "role": "ARP discovery", "network": "outbound-read", "risk": "high", "license": "GPL-3.0"},
    "arp-scan": {"family": "authorized-reconnaissance", "role": "ARP host discovery", "network": "outbound-read", "risk": "high", "license": "GPL-3.0"},
    "hping3": {"family": "network", "role": "crafted ICMP/TCP probes", "network": "outbound-read", "risk": "high", "license": "GPL-2.0"},
    "tcpdump": {"family": "network", "role": "packet capture", "network": "no-network", "risk": "medium", "license": "BSD-3-Clause"},
    "tshark": {"family": "network", "role": "packet analysis", "network": "no-network", "risk": "medium", "license": "GPL-2.0"},
    "wireshark": {"family": "network", "role": "packet analysis GUI", "network": "no-network", "risk": "medium", "license": "GPL-2.0"},
    "socat": {"family": "network", "role": "socket relay", "network": "outbound-read", "risk": "high", "license": "GPL-2.0"},
    "nc": {"family": "network", "role": "netcat", "network": "outbound-read", "risk": "high", "license": "BSD-3-Clause"},
    "nc.openbsd": {"family": "network", "role": "openbsd netcat", "network": "outbound-read", "risk": "high", "license": "BSD-3-Clause"},
    "nuclei": {"family": "authorized-assessment", "role": "template checks", "network": "outbound-read", "risk": "high", "license": "MIT"},
    "httpx": {"family": "authorized-http", "role": "HTTP probing", "network": "outbound-read", "risk": "high", "license": "MIT"},
    "katana": {"family": "authorized-http", "role": "web crawling", "network": "outbound-read", "risk": "high", "license": "MIT"},
    "ffuf": {"family": "authorized-content-discovery", "role": "content discovery", "network": "outbound-read", "risk": "high", "license": "MIT"},
    "gobuster": {"family": "authorized-content-discovery", "role": "directory discovery", "network": "outbound-read", "risk": "high", "license": "Apache-2.0"},
    "feroxbuster": {"family": "authorized-content-discovery", "role": "recursive content discovery", "network": "outbound-read", "risk": "high", "license": "MIT"},
    "dirb": {"family": "authorized-content-discovery", "role": "directory discovery", "network": "outbound-read", "risk": "high", "license": "GPL-2.0"},
    "dirbuster": {"family": "authorized-content-discovery", "role": "directory discovery", "network": "outbound-read", "risk": "high", "license": "Apache-2.0"},
    "wfuzz": {"family": "authorized-content-discovery", "role": "web fuzzer", "network": "outbound-read", "risk": "high", "license": "GPL-2.0"},
    "nikto": {"family": "authorized-assessment", "role": "web server assessment", "network": "outbound-read", "risk": "high", "license": "GPL-2.0"},
    "whatweb": {"family": "authorized-assessment", "role": "web fingerprinting", "network": "outbound-read", "risk": "high", "license": "GPL-2.0"},
    "wafw00f": {"family": "authorized-assessment", "role": "WAF detection", "network": "outbound-read", "risk": "high", "license": "GPL-2.0"},
    "wpscan": {"family": "authorized-assessment", "role": "WordPress assessment", "network": "outbound-read", "risk": "high", "license": "custom-free"},
    "sqlmap": {"family": "authorized-assessment", "role": "SQL injection testing", "network": "outbound-read", "risk": "high", "license": "GPL-2.0"},
    "amass": {"family": "passive-osint", "role": "attack-surface mapping", "network": "outbound-read", "risk": "high", "license": "Apache-2.0"},
    "subfinder": {"family": "passive-osint", "role": "subdomain discovery", "network": "outbound-read", "risk": "high", "license": "MIT"},
    "theharvester": {"family": "passive-osint", "role": "OSINT gathering", "network": "outbound-read", "risk": "high", "license": "GPL-2.0"},
    "recon-ng": {"family": "passive-osint", "role": "recon framework", "network": "outbound-read", "risk": "high", "license": "GPL-3.0"},
    "dnsenum": {"family": "passive-osint", "role": "DNS enumeration", "network": "outbound-read", "risk": "high", "license": "GPL-2.0"},
    "dnsrecon": {"family": "passive-osint", "role": "DNS reconnaissance", "network": "outbound-read", "risk": "high", "license": "GPL-2.0"},
    "fierce": {"family": "passive-osint", "role": "DNS reconnaissance", "network": "outbound-read", "risk": "high", "license": "GPL-3.0"},
    "whois": {"family": "network", "role": "registry lookup", "network": "outbound-read", "risk": "high", "license": "GPL-2.0"},
    "dig": {"family": "network", "role": "DNS lookup", "network": "outbound-read", "risk": "high", "license": "MPL-2.0"},
    "nslookup": {"family": "network", "role": "DNS lookup", "network": "outbound-read", "risk": "high", "license": "MPL-2.0"},
    "john": {"family": "analysis", "role": "hash analysis", "network": "no-network", "risk": "medium", "license": "GPL-2.0"},
    "hashcat": {"family": "analysis", "role": "hash analysis", "network": "no-network", "risk": "medium", "license": "MIT"},
    "hydra": {"family": "authorized-assessment", "role": "credential testing", "network": "outbound-read", "risk": "high", "license": "AGPL-3.0"},
    "medusa": {"family": "authorized-assessment", "role": "credential testing", "network": "outbound-read", "risk": "high", "license": "GPL-2.0"},
    "ncrack": {"family": "authorized-assessment", "role": "credential testing", "network": "outbound-read", "risk": "high", "license": "GPL-2.0"},
    "crunch": {"family": "analysis", "role": "wordlist generation", "network": "no-network", "risk": "low", "license": "GPL-2.0"},
    "cewl": {"family": "analysis", "role": "site-derived wordlist", "network": "outbound-read", "risk": "high", "license": "GPL-3.0"},
    "aircrack-ng": {"family": "wireless", "role": "wireless analysis", "network": "no-network", "risk": "high", "license": "GPL-2.0"},
    "airodump-ng": {"family": "wireless", "role": "wireless capture", "network": "no-network", "risk": "high", "license": "GPL-2.0"},
    "aireplay-ng": {"family": "wireless", "role": "wireless injection", "network": "no-network", "risk": "high", "license": "GPL-2.0"},
    "airmon-ng": {"family": "wireless", "role": "monitor-mode helper", "network": "no-network", "risk": "high", "license": "GPL-2.0"},
    "reaver": {"family": "wireless", "role": "WPS testing", "network": "no-network", "risk": "high", "license": "GPL-2.0"},
    "wifite": {"family": "wireless", "role": "wireless audit helper", "network": "no-network", "risk": "high", "license": "GPL-2.0"},
    "kismet": {"family": "wireless", "role": "wireless IDS", "network": "no-network", "risk": "high", "license": "GPL-2.0"},
    "msfconsole": {"family": "authorized-assessment", "role": "metasploit console", "network": "outbound-read", "risk": "high", "license": "BSD-3-Clause"},
    "msfvenom": {"family": "authorized-assessment", "role": "payload generation", "network": "no-network", "risk": "high", "license": "BSD-3-Clause"},
    "searchsploit": {"family": "analysis", "role": "exploit-db search", "network": "no-network", "risk": "low", "license": "GPL-2.0"},
    "binwalk": {"family": "forensics", "role": "firmware analysis", "network": "no-network", "risk": "low", "license": "MIT"},
    "foremost": {"family": "forensics", "role": "file carving", "network": "no-network", "risk": "low", "license": "public-domain"},
    "exiftool": {"family": "forensics", "role": "metadata inspection", "network": "no-network", "risk": "low", "license": "GPL-1.0-or-later"},
    "steghide": {"family": "forensics", "role": "steganography", "network": "no-network", "risk": "low", "license": "GPL-2.0"},
    "strings": {"family": "forensics", "role": "printable strings", "network": "no-network", "risk": "low", "license": "GPL-3.0"},
    "gdb": {"family": "reverse-engineering", "role": "debugger", "network": "no-network", "risk": "medium", "license": "GPL-3.0"},
    "radare2": {"family": "reverse-engineering", "role": "reverse engineering", "network": "no-network", "risk": "medium", "license": "LGPL-3.0"},
    "r2": {"family": "reverse-engineering", "role": "radare2 alias", "network": "no-network", "risk": "medium", "license": "LGPL-3.0"},
    "objdump": {"family": "reverse-engineering", "role": "object dump", "network": "no-network", "risk": "low", "license": "GPL-3.0"},
    "strace": {"family": "reverse-engineering", "role": "syscall trace", "network": "no-network", "risk": "medium", "license": "LGPL-2.1"},
    "ltrace": {"family": "reverse-engineering", "role": "library trace", "network": "no-network", "risk": "medium", "license": "GPL-2.0"},
    "apktool": {"family": "reverse-engineering", "role": "Android APK decode", "network": "no-network", "risk": "low", "license": "Apache-2.0"},
    "lynis": {"family": "hardening", "role": "host audit", "network": "no-network", "risk": "low", "license": "GPL-3.0"},
    "chkrootkit": {"family": "hardening", "role": "rootkit checks", "network": "no-network", "risk": "low", "license": "GPL-2.0"},
    "rkhunter": {"family": "hardening", "role": "rootkit hunter", "network": "no-network", "risk": "low", "license": "GPL-2.0"},
    "ssh-audit": {"family": "hardening", "role": "SSH configuration audit", "network": "outbound-read", "risk": "high", "license": "MIT"},
    "proxychains": {"family": "network", "role": "proxy wrapper", "network": "outbound-read", "risk": "high", "license": "GPL-2.0"},
    "proxychains4": {"family": "network", "role": "proxy wrapper", "network": "outbound-read", "risk": "high", "license": "GPL-2.0"},
    "enum4linux": {"family": "authorized-assessment", "role": "SMB enumeration", "network": "outbound-read", "risk": "high", "license": "GPL-2.0"},
    "enum4linux-ng": {"family": "authorized-assessment", "role": "SMB enumeration", "network": "outbound-read", "risk": "high", "license": "GPL-3.0"},
    "smbclient": {"family": "authorized-assessment", "role": "SMB client", "network": "outbound-read", "risk": "high", "license": "GPL-3.0"},
    "smbmap": {"family": "authorized-assessment", "role": "SMB share mapping", "network": "outbound-read", "risk": "high", "license": "GPL-3.0"},
    "responder": {"family": "authorized-assessment", "role": "name-service poisoning", "network": "outbound-read", "risk": "high", "license": "GPL-3.0"},
    "bettercap": {"family": "authorized-assessment", "role": "network attack framework", "network": "outbound-read", "risk": "high", "license": "GPL-3.0"},
    "ettercap": {"family": "authorized-assessment", "role": "MITM helper", "network": "outbound-read", "risk": "high", "license": "GPL-2.0"},
    "hash-identifier": {"family": "analysis", "role": "hash identification", "network": "no-network", "risk": "low", "license": "GPL-3.0"},
    "exif": {"family": "forensics", "role": "EXIF inspection", "network": "no-network", "risk": "low", "license": "MIT"},
    "stegsolve": {"family": "forensics", "role": "steg analysis", "network": "no-network", "risk": "low", "license": "custom-free"},
    "volatility": {"family": "forensics", "role": "memory forensics", "network": "no-network", "risk": "low", "license": "GPL-2.0"},
    "volatility3": {"family": "forensics", "role": "memory forensics", "network": "no-network", "risk": "low", "license": "GPL-2.0"},
    "trivy": {"family": "container-security", "role": "image/fs vulnerability scan", "network": "no-network", "risk": "medium", "license": "Apache-2.0"},
    "grype": {"family": "container-security", "role": "vulnerability scan", "network": "no-network", "risk": "medium", "license": "Apache-2.0"},
    "syft": {"family": "container-security", "role": "SBOM generation", "network": "no-network", "risk": "low", "license": "Apache-2.0"},
    "osv-scanner": {"family": "container-security", "role": "advisory scan", "network": "no-network", "risk": "low", "license": "Apache-2.0"},
}

# Never planned from natural language. Use the PTY for these.
DENYLIST = {
    "rm", "rmdir", "dd", "mkfs", "mkfs.ext4", "mkfs.xfs", "mkfs.btrfs", "wipefs",
    "shred", "reboot", "poweroff", "halt", "shutdown", "kexec", "chown", "chmod",
    "useradd", "userdel", "passwd", "su", "sudo", "doas", "pkexec",
    "iptables-restore", "ip6tables-restore", "nft",
}

INTERPRETERS = {
    "python", "python2", "python3", "pypy3", "bash", "sh", "dash", "zsh", "ksh",
    "fish", "perl", "ruby", "node", "nodejs", "lua", "php", "pwsh", "powershell",
    "busybox", "expect", "tclsh", "awk", "gawk", "mawk",
}

INTERPRETER_CODE_FLAGS = {"-c", "-e", "--eval", "-m", "--command"}

HELP_FLAGS = {"-h", "--help", "-V", "--version", "-v", "version", "help"}

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,80}$")
_CACHE: dict[str, Any] = {"at": 0.0, "result": None}
_CACHE_TTL = 8.0


def _is_user_writable_directory(path: Path, st: os.stat_result | None = None) -> bool:
    st = st or path.stat()
    mode = stat.S_IMODE(st.st_mode)
    return bool(mode & 0o022) or (os.getuid() != 0 and st.st_uid == os.getuid() and bool(mode & 0o200))


def safe_path_dirs(raw_path: str | None = None) -> list[str]:
    """Return PATH directories that are safe for managed execution."""
    raw = raw_path if raw_path is not None else (os.environ.get("PATH") or CONTROLLED_PATH)
    safe: list[str] = []
    for piece in raw.split(os.pathsep):
        directory = piece or "."
        try:
            resolved = Path(directory).expanduser().resolve(strict=True)
            st = resolved.stat()
            if not resolved.is_dir() or _is_user_writable_directory(resolved, st):
                continue
            safe.append(str(resolved))
        except OSError:
            continue
    return safe


def _snapshot_path() -> Path:
    try:
        from vortex_backend import data_root
    except ImportError:
        from backend.vortex_backend import data_root
    return data_root() / "host_tools_snapshot.json"


def load_snapshot() -> dict[str, Any]:
    path = _snapshot_path()
    if not path.is_file():
        return {"names": [], "at": None}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("names"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"names": [], "at": None}


def save_snapshot(names: list[str]) -> None:
    path = _snapshot_path()
    payload = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "names": sorted(set(names))}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    try:
        tmp.chmod(0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def _is_executable_file(entry: os.DirEntry[str]) -> bool:
    try:
        if not entry.is_file(follow_symlinks=True):
            return False
        st = entry.stat(follow_symlinks=True)
        return bool(st.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH))
    except OSError:
        return False


def list_path_executables(dirs: list[str] | None = None) -> dict[str, str]:
    """Map basename -> first safe PATH realpath. Does not hash contents."""
    found: dict[str, str] = {}
    for directory in dirs if dirs is not None else safe_path_dirs():
        try:
            with os.scandir(directory) as it:
                for entry in it:
                    name = entry.name
                    if name in found or not _NAME_RE.fullmatch(name):
                        continue
                    if not _is_executable_file(entry):
                        continue
                    try:
                        found[name] = str(Path(entry.path).resolve(strict=True))
                    except OSError:
                        found[name] = entry.path
        except OSError:
            continue
    return found


def classify(name: str) -> dict[str, Any]:
    meta = KALI_CATALOG.get(name)
    if meta:
        return {**meta, "source": "kali-catalog"}
    return {
        "family": "discovered",
        "role": "host PATH executable",
        "network": "unknown",
        "risk": "high",
        "license": "unknown",
        "source": "discovered",
    }


def scan_host_tools(*, persist: bool = True, use_cache: bool = True) -> dict[str, Any]:
    """Probe safe PATH directories and report catalog + newly installed tools."""
    now = time.monotonic()
    if use_cache and _CACHE["result"] is not None and (now - float(_CACHE["at"])) < _CACHE_TTL:
        return _CACHE["result"]
    try:
        from adapter_registry import TOOL_CATALOG
    except ImportError:
        from backend.adapter_registry import TOOL_CATALOG
    dirs = safe_path_dirs()
    found = list_path_executables(dirs)
    previous = set(str(x) for x in (load_snapshot().get("names") or []) if isinstance(x, str))
    tools: list[dict[str, Any]] = []
    new_names: list[str] = []
    for name, path in sorted(found.items()):
        info = classify(name)
        in_builtin = name in TOOL_CATALOG
        is_new = bool(previous) and name not in previous
        if is_new:
            new_names.append(name)
        tools.append({
            "name": name,
            "binary": path,
            "path": path,
            "state": "installed",
            "category": info.get("family"),
            "family": info.get("family"),
            "role": info.get("role"),
            "source": "builtin-catalog" if in_builtin else info.get("source"),
            "risk_level": info.get("risk"),
            "requires_network": info.get("network") not in (None, "no-network", "loopback-only"),
            "network_class": info.get("network"),
            "license": info.get("license"),
            "new_since_last_scan": is_new,
            "in_builtin_catalog": in_builtin,
            "kali_known": name in KALI_CATALOG,
        })
    kali_installed = [t for t in tools if t["kali_known"]]
    kali_absent = sorted(name for name in KALI_CATALOG if name not in found)
    discovered = [t for t in tools if not t["in_builtin_catalog"]]
    result = {
        "scanned_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "path_dirs": dirs,
        "tools": tools,
        "counts": {
            "path_executables": len(tools),
            "kali_known_installed": len(kali_installed),
            "kali_known_absent": len(kali_absent),
            "discovered": len(discovered),
            "new_since_last_scan": len(new_names),
            "builtin_catalog": len(TOOL_CATALOG),
        },
        "new_since_last_scan": new_names,
        "kali_absent": kali_absent,
        "host_tool_access_required_to_plan": True,
    }
    if persist:
        save_snapshot(list(found.keys()))
    _CACHE["at"] = now
    _CACHE["result"] = result
    return result


def invalidate_host_scan_cache() -> None:
    _CACHE["at"] = 0.0
    _CACHE["result"] = None


def _longest_tool_mention(text: str, names: set[str]) -> str | None:
    lower = text.lower()
    # Prefer longer names so "aircrack-ng" wins over a hypothetical "air".
    for name in sorted(names, key=len, reverse=True):
        if re.search(rf"(?<![A-Za-z0-9._+-]){re.escape(name.lower())}(?![A-Za-z0-9._+-])", lower):
            return name
    return None


def parse_host_argv(request: str, tool: str) -> list[str] | None:
    """Build typed argv from a natural-language request. None = cannot parse."""
    try:
        tokens = shlex.split(request)
    except ValueError:
        return None
    if not tokens:
        return None
    lowered = [t.lower() for t in tokens]
    if tool.lower() in lowered:
        start = lowered.index(tool.lower())
        argv = [tool, *tokens[start + 1:]]
    else:
        argv = [tool]
    if any("\x00" in arg for arg in argv):
        return None
    if any(token in arg for arg in argv for token in (";", "&&", "||", "|", ">", "<", "`", "$(")):
        return None
    if len(argv) > 24 or any(len(arg) > 400 for arg in argv):
        return None
    return argv


def match_request(request: str, installed: dict[str, str] | None = None) -> dict[str, Any] | None:
    """Return a host-tool plan proposal, or None if this request is not a host-tool ask.

    Callers must still honour ``host_tool_access``, Guardian, and engagement.
    """
    text = (request or "").strip()
    if not text or len(text) > 8000:
        return None
    found = installed if installed is not None else list_path_executables()
    names = set(found) | set(KALI_CATALOG)
    tool = _longest_tool_mention(text, names)
    if not tool:
        return None
    lower = text.lower()
    # Require an explicit run/use/invoke cue or the tool as the first token so
    # "check my nmap notes file" does not become an nmap scan. Bare tool names
    # ("wpscan", "lynis") are accepted.
    first = shlex.split(text)[0] if text else ""
    explicit = bool(re.search(rf"\b(?:run|use|launch|invoke|exec(?:ute)?)\s+{re.escape(tool)}\b", lower))
    if first.lower() != tool.lower() and not explicit and tool.lower() not in {t.lower() for t in KALI_CATALOG}:
        # Discovered (non-catalog) tools need an explicit run cue or exact name.
        if not re.search(rf"\b{re.escape(tool)}\b", lower):
            return None
        if not explicit and first.lower() != tool.lower():
            return None
    if tool in DENYLIST or Path(tool).name in DENYLIST:
        return {
            "name": tool,
            "status": "rejected",
            "reason": f"{tool} is not planned from natural language. Use a PTY session for operator-controlled destructive or privilege tools.",
        }
    if tool not in found:
        return {
            "name": tool,
            "status": "unavailable",
            "reason": f"TOOL MISSING: {tool} is not installed on a safe PATH directory.",
            "missing": tool,
        }
    argv = parse_host_argv(text, tool)
    if argv is None:
        return {
            "name": tool,
            "status": "clarified",
            "reason": "VORTEX could not parse a typed argv without shell metacharacters. Ask for a single tool with literal arguments, or use the PTY.",
        }
    info = classify(tool)
    extra = argv[1:]
    help_only = (not extra) or (len(extra) == 1 and extra[0] in HELP_FLAGS)
    if tool in INTERPRETERS and extra and any(flag in extra for flag in INTERPRETER_CODE_FLAGS):
        return {
            "name": tool,
            "status": "clarified",
            "reason": "VORTEX will not pass arbitrary code to interpreters from a natural-language plan. Use the PTY terminal for interactive interpreters.",
        }
    if tool in INTERPRETERS and extra and not help_only:
        return {
            "name": tool,
            "status": "clarified",
            "reason": "Interpreter binaries are limited to --help/--version through the planner. Use the PTY for an interactive session.",
        }
    network = "no-network" if help_only else info.get("network") or "unknown"
    if network == "unknown":
        network = "outbound-read"
    risk = "low" if help_only else (info.get("risk") or "high")
    adapter = "linux.host.help" if help_only else "linux.host.tool"
    return {
        "name": tool,
        "status": "ok",
        "argv": argv,
        "path": found[tool],
        "family": info.get("family"),
        "role": info.get("role"),
        "license": info.get("license"),
        "source": info.get("source"),
        "risk": risk,
        "network_class": network,
        "adapter_id": adapter,
        "needs_engagement": (not help_only) and network not in {"no-network", "loopback-only"},
        "help_only": help_only,
        "explanation": (
            f"Probe {tool} help/version only; no target is contacted."
            if help_only
            else f"Run the discovered host tool {tool} with typed argv. Guardian still authorizes execution."
        ),
    }
