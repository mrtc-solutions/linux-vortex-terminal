"""Reviewed argv builders for authorized assessment tools.

These functions never execute. They return typed argv or an honest reason
why no command can be created. Wordlists are only accepted when they already
exist as regular files on this host.
"""
from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

WORDLIST_CANDIDATES = (
    "/usr/share/wordlists/dirb/common.txt",
    "/usr/share/dirb/wordlists/common.txt",
    "/usr/share/seclists/Discovery/Web-Content/common.txt",
    "/usr/share/wordlists/dirbuster/directory-list-2.3-small.txt",
)
MAX_WORDLIST_BYTES = 20 * 1024 * 1024
WORDLIST_RE = re.compile(r"(?:wordlist|-w)\s+(\S+)", re.I)
BLOCKED_WORDLIST_NAMES = {"shadow", "passwd", "group", "vortex.db", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"}


def _data_root() -> Path:
    override = os.environ.get("VORTEX_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".local" / "share" / "vortex").resolve()


def _wordlist_permitted(resolved: Path) -> bool:
    if any(part in {".ssh", ".gnupg"} for part in resolved.parts):
        return False
    if resolved.name.lower() in BLOCKED_WORDLIST_NAMES:
        return False
    allowed = [Path("/usr/share").resolve(), _data_root()]
    for root in allowed:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _http_url(targets: list[str]) -> str | None:
    for target in targets:
        if target.lower().startswith(("http://", "https://")):
            return target
    return None


def _hostname(targets: list[str]) -> str | None:
    for target in targets:
        parsed = urlparse(target if "://" in target else f"//{target}")
        host = parsed.hostname
        if host and not host.replace(".", "").isdigit() and ":" not in host:
            return host
        if HOSTISH.match(target) and "/" not in target and ":" not in target:
            return target.lower()
    return None


HOSTISH = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$")


def _inspect_wordlist(raw: str) -> dict[str, Any] | None:
    path = Path(raw).expanduser()
    try:
        resolved = path.resolve(strict=True)
        st = resolved.stat()
    except OSError:
        return None
    if not resolved.is_file() or not stat.S_ISREG(st.st_mode):
        return None
    mode = stat.S_IMODE(st.st_mode)
    if mode & 0o022:
        return None
    if st.st_size <= 0 or st.st_size > MAX_WORDLIST_BYTES:
        return None
    if not _wordlist_permitted(resolved):
        return None
    return {"state": "observed", "path": str(resolved), "size": st.st_size}


def discover_wordlist(request: str = "") -> dict[str, Any]:
    match = WORDLIST_RE.search(request or "")
    if match:
        found = _inspect_wordlist(match.group(1))
        if found:
            return found
        return {
            "state": "absent",
            "path": None,
            "message": "The requested wordlist is missing, world-writable, too large, or outside /usr/share and the VORTEX data directory.",
        }
    for raw in WORDLIST_CANDIDATES:
        found = _inspect_wordlist(raw)
        if found:
            return found
    return {
        "state": "absent",
        "path": None,
        "message": "No reviewed wordlist was found. Provide an existing host path with `wordlist /absolute/path` under /usr/share or the VORTEX data directory.",
    }


def build_scan(tool: str, targets: list[str], request: str = "") -> dict[str, Any]:
    """Return a typed scan proposal or an honest unavailable reason."""
    tool = (tool or "").lower()
    if tool == "nuclei":
        url = _http_url(targets)
        if not url:
            return {"ok": False, "reason": "nuclei adapter requires an explicit HTTP(S) URL in engagement scope."}
        return {
            "ok": True,
            "adapter_id": "security.nuclei.templates",
            "argv": ["nuclei", "-u", url, "-timeout", "10", "-retries", "0", "-rate-limit", "5", "-c", "2", "-silent", "-nc", "-duc", "-ni"],
            "explanation": "Run installed nuclei against one scoped URL with update-check, interactsh, and color disabled.",
        }
    if tool == "nikto":
        url = _http_url(targets)
        if not url:
            return {"ok": False, "reason": "nikto adapter requires an explicit HTTP(S) URL in engagement scope."}
        return {
            "ok": True,
            "adapter_id": "security.nikto.web",
            "argv": ["nikto", "-h", url, "-nointeractive", "-nolookup", "-maxtime", "120s"],
            "explanation": "Run installed nikto against one scoped URL with interactive prompts and extra DNS lookups disabled.",
        }
    if tool == "amass":
        domain = _hostname(targets)
        if not domain:
            return {"ok": False, "reason": "amass adapter requires a hostname/domain (passive enum only)."}
        return {
            "ok": True,
            "adapter_id": "security.amass.passive",
            "argv": ["amass", "enum", "-passive", "-norecursive", "-timeout", "2", "-d", domain],
            "explanation": "Run installed amass in passive, non-recursive mode against one scoped domain.",
        }
    if tool in {"ffuf", "gobuster"}:
        url = _http_url(targets)
        if not url:
            return {"ok": False, "reason": f"{tool} adapter requires an explicit HTTP(S) URL in engagement scope."}
        wordlist = discover_wordlist(request)
        if wordlist["state"] != "observed":
            return {"ok": False, "reason": wordlist["message"], "missing": "wordlist"}
        if tool == "ffuf":
            fuzz_url = url if "FUZZ" in url else (url.rstrip("/") + "/FUZZ")
            return {
                "ok": True,
                "adapter_id": "security.ffuf.discovery",
                "argv": ["ffuf", "-u", fuzz_url, "-w", wordlist["path"], "-mc", "200,204,301,302,307,401,403", "-t", "10", "-timeout", "10", "-s", "-noninteractive"],
                "explanation": "Run installed ffuf with a host wordlist, bounded threads, and no interactive prompts.",
                "wordlist": wordlist["path"],
            }
        return {
            "ok": True,
            "adapter_id": "security.gobuster.discovery",
            "argv": ["gobuster", "dir", "-u", url, "-w", wordlist["path"], "-t", "10", "-q", "--no-error", "-to", "10s", "--no-color"],
            "explanation": "Run installed gobuster directory discovery with a host wordlist and bounded threads.",
            "wordlist": wordlist["path"],
        }
    return {"ok": False, "reason": f"ADAPTER NOT IMPLEMENTED: {tool}; no command was created."}
