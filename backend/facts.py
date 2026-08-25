"""Small deterministic parsers for apt and systemd command output.

These parsers consume observed command output only. They do not run commands,
make security claims, or infer facts when the tool failed.
"""
from __future__ import annotations

import re
from typing import Any

ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[@-_])")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean(text: str) -> str:
    return CONTROL_RE.sub("", ANSI_RE.sub("", text)).replace("\r", "")


def _items_after_heading(lines: list[str], heading: str) -> list[str]:
    values: list[str] = []
    active = False
    for line in lines:
        if heading.lower() in line.lower():
            active = True
            continue
        if active:
            if not line.strip():
                break
            if not line[:1].isspace():
                break
            values.extend(re.findall(r"[A-Za-z0-9][A-Za-z0-9+_.:-]*", line))
    return values[:500]


def parse_apt_preflight(text: str, exit_code: int | None = 0) -> dict[str, Any]:
    safe = clean(text)
    result: dict[str, Any] = {
        "state": "tool_error" if exit_code not in (None, 0) else "inconclusive",
        "exit_code": exit_code,
        "upgraded": 0,
        "newly_installed": 0,
        "removed": 0,
        "not_upgraded": 0,
        "packages_upgraded": [],
        "packages_new": [],
        "packages_removed": [],
        "held_or_kept_back": False,
        "requires_reboot": bool(re.search(r"reboot|restart required|needrestart", safe, re.I)),
        "errors": [],
    }
    result["packages_new"] = _items_after_heading(safe.splitlines(), "following NEW packages")
    result["packages_upgraded"] = _items_after_heading(safe.splitlines(), "following packages will be upgraded")
    result["packages_removed"] = _items_after_heading(safe.splitlines(), "following packages will be REMOVED")
    summary = re.search(r"(\d+) upgraded,\s*(\d+) newly installed,\s*(\d+) to remove and\s*(\d+) not upgraded", safe, re.I)
    if summary:
        result.update({"upgraded": int(summary.group(1)), "newly_installed": int(summary.group(2)), "removed": int(summary.group(3)), "not_upgraded": int(summary.group(4)), "state": "observed" if exit_code in (None, 0) else "tool_error"})
    result["held_or_kept_back"] = bool(re.search(r"kept back|held back|held packages?", safe, re.I))
    errors = [line.strip() for line in safe.splitlines() if re.match(r"(?:E:|Err:|Unable to acquire|Could not get lock)", line.strip(), re.I)]
    if errors:
        result["errors"] = errors[:20]
        result["state"] = "tool_error"
    if not summary and exit_code in (None, 0):
        result["errors"] = ["apt preflight summary was not observed"]
    return result


def parse_apt_policy(text: str, exit_code: int | None = 0) -> dict[str, Any]:
    safe = clean(text)
    result: dict[str, Any] = {"state": "observed" if exit_code in (None, 0) else "tool_error", "installed": None, "candidate": None, "sources": [], "raw_error": None}
    for key, pattern in (("installed", r"^\s*Installed:\s*(\S+)"), ("candidate", r"^\s*Candidate:\s*(\S+)")):
        match = re.search(pattern, safe, re.MULTILINE | re.I)
        if match: result[key] = match.group(1)
    for line in safe.splitlines():
        line = line.strip()
        if line.startswith("http://") or line.startswith("https://"):
            result["sources"].append(line.split()[0])
    if re.search(r"Candidate:\s*\(none\)", safe, re.I): result["state"] = "inconclusive"
    if exit_code not in (None, 0): result["raw_error"] = next((line.strip() for line in safe.splitlines() if line.strip()), "apt-cache policy failed")
    result["sources"] = list(dict.fromkeys(result["sources"]))[:20]
    return result


def parse_apt_show(text: str, exit_code: int | None = 0) -> dict[str, Any]:
    safe = clean(text)
    result: dict[str, Any] = {"state": "observed" if exit_code in (None, 0) else "tool_error", "package": None, "version": None, "architecture": None, "depends": [], "source": None}
    fields = {key: re.search(rf"^{key}:\s*(.+)$", safe, re.MULTILINE | re.I) for key in ("Package", "Version", "Architecture", "Depends", "Source")}
    if fields["Package"]: result["package"] = fields["Package"].group(1).strip()
    if fields["Version"]: result["version"] = fields["Version"].group(1).strip()
    if fields["Architecture"]: result["architecture"] = fields["Architecture"].group(1).strip()
    if fields["Source"]: result["source"] = fields["Source"].group(1).strip()
    if fields["Depends"]: result["depends"] = [part.strip().split()[0] for part in fields["Depends"].group(1).split(",")][:100]
    return result


def parse_dpkg_audit(text: str, exit_code: int | None = 0) -> dict[str, Any]:
    safe = clean(text)
    return {"state": "observed" if exit_code in (None, 0) else "tool_error", "incomplete": bool(safe.strip()) or exit_code not in (None, 0), "summary": safe.splitlines()[:20]}


def parse_systemd_show(text: str, exit_code: int | None = 0) -> dict[str, Any]:
    safe = clean(text)
    fields: dict[str, str] = {}
    for line in safe.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key] = value[:1000]
    state = "observed" if exit_code in (None, 0) and fields else "tool_error" if exit_code not in (None, 0) else "inconclusive"
    return {"state": state, "unit": fields.get("Id"), "description": fields.get("Description"), "load_state": fields.get("LoadState"), "active_state": fields.get("ActiveState"), "sub_state": fields.get("SubState"), "unit_file_state": fields.get("UnitFileState"), "fields": fields}


def parse_journal(text: str, exit_code: int | None = 0) -> dict[str, Any]:
    safe = clean(text)
    lines = [line for line in safe.splitlines() if line.strip()]
    failures = [line[:300] for line in lines if re.search(r"failed|failure|error|fatal|panic", line, re.I)]
    return {"state": "observed" if exit_code in (None, 0) else "tool_error", "line_count": len(lines), "failure_line_count": len(failures), "failure_lines": failures[:20]}


def parse_package_facts(results: list[dict[str, Any]]) -> dict[str, Any]:
    facts: dict[str, Any] = {"state": "observed", "dpkg": None, "held": [], "policy": None, "metadata": None, "preflight": None, "impact": {"upgraded": 0, "newly_installed": 0, "removed": 0, "not_upgraded": 0}}
    for item in results:
        argv = item.get("argv", [])
        output = item.get("stdout", "") + item.get("stderr", "")
        exit_code = item.get("exit_code")
        if item.get("status") != "succeeded": facts["state"] = "tool_error"
        if item.get("executable") == "dpkg" and "--audit" in argv: facts["dpkg"] = parse_dpkg_audit(output, exit_code)
        elif item.get("executable") == "apt-mark" and "showhold" in argv: facts["held"] = [line.strip() for line in output.splitlines() if line.strip()][:100]
        elif item.get("executable") == "apt-cache" and "policy" in argv: facts["policy"] = parse_apt_policy(output, exit_code)
        elif item.get("executable") == "apt-cache" and "show" in argv: facts["metadata"] = parse_apt_show(output, exit_code)
        elif item.get("executable") == "apt-get" and "-s" in argv:
            facts["preflight"] = parse_apt_preflight(output, exit_code)
            for key in facts["impact"]: facts["impact"][key] = facts["preflight"].get(key, 0)
    return facts


def parse_systemd_facts(results: list[dict[str, Any]]) -> dict[str, Any]:
    facts: dict[str, Any] = {"state": "observed", "unit": None, "journal": None}
    for item in results:
        if item.get("status") != "succeeded": facts["state"] = "tool_error"
        if item.get("executable") == "systemctl" and "show" in item.get("argv", []): facts["unit"] = parse_systemd_show(item.get("stdout", "") + item.get("stderr", ""), item.get("exit_code"))
        elif item.get("executable") == "journalctl": facts["journal"] = parse_journal(item.get("stdout", "") + item.get("stderr", ""), item.get("exit_code"))
    return facts


def parse_container_logs(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize bounded Docker/Podman logs without turning log text into findings."""
    if not results:
        return {"state": "not_run", "line_count": 0, "error": "no container log command was run"}
    item = results[-1]
    text = clean(item.get("stdout", "") + item.get("stderr", ""))
    lines = [line for line in text.splitlines() if line.strip()]
    levels = {level: sum(1 for line in lines if re.search(rf"\b{level}\b", line, re.I)) for level in ("trace", "debug", "info", "warn", "error", "fatal")}
    state = "observed" if item.get("status") == "succeeded" else "tool_error"
    return {"state": state, "line_count": len(lines), "levels": levels, "sample": lines[:20], "bounded": True, "limit_lines": 200, "limitations": ["Container logs are untrusted observations; level counts do not confirm an incident or vulnerability."]}


def parse_ssh_connection(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify real ssh connectivity output without retaining unredacted secrets."""
    if not results:
        return {"state": "not_run", "classification": "not_run"}
    item = results[-1]
    text = clean(item.get("stdout", "") + item.get("stderr", ""))
    lowered = text.lower()
    if item.get("status") == "succeeded" and item.get("exit_code") == 0:
        classification = "connected"
    elif "could not resolve hostname" in lowered or "name or service not known" in lowered:
        classification = "dns_failed"
    elif "host key verification failed" in lowered or "remote host identification has changed" in lowered:
        classification = "host_key_rejected"
    elif "permission denied" in lowered or "authentication failed" in lowered:
        classification = "auth_failed"
    elif "connection timed out" in lowered or "operation timed out" in lowered:
        classification = "timeout"
    elif "connection refused" in lowered:
        classification = "refused"
    elif item.get("status") != "succeeded":
        classification = "connection_failed"
    else:
        classification = "unknown"
    return {"state": "observed" if item.get("status") == "succeeded" else "tool_error", "classification": classification, "exit_code": item.get("exit_code"), "signal": item.get("signal"), "observed_lines": len([line for line in text.splitlines() if line.strip()]), "limitations": ["Connectivity/authentication status is not a security finding; passwords, keys, and full environment data are not retained."]}
