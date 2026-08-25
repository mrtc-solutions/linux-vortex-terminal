"""Bounded, evidence-only parsers for Vortex artifacts and tool output.

Parsers return observations and provenance. They never infer vulnerabilities or
turn a missing/invalid file into a finding. Raw bytes are read transiently and
are not included in returned records.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import re
import stat
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

MAX_ARTIFACT_BYTES = 10 * 1024 * 1024
PARSER_VERSION = "1"
ANSI_RE = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|[@-_])")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
BIDI_RE = re.compile(r"[\u202a-\u202e\u2066-\u2069]")
SECRET_RE = re.compile(r"(?i)(bearer\s+|password\s*[=:]\s*|token\s*[=:]\s*|api[_-]?key\s*[=:]\s*|secret\s*[=:]\s*)([^\s,;]+)")


class ArtifactError(ValueError):
    pass


def sanitize(text: str) -> str:
    text = ANSI_RE.sub("", text)
    text = CONTROL_RE.sub("", text)
    return BIDI_RE.sub("[BIDI]", text).replace("\r", "")


def redact(text: str) -> str:
    text = sanitize(text)
    return SECRET_RE.sub(lambda match: match.group(1) + "[REDACTED]", text)


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _base(source: dict[str, Any], data: bytes, kind: str, parser_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_id": hashlib.sha256((source.get("identity", "") + sha256(data)).encode()).hexdigest()[:32],
        "kind": kind,
        "source": source,
        "size_bytes": len(data),
        "sha256": sha256(data),
        "parser": {"id": parser_id, "version": PARSER_VERSION},
    }


def _read_path(raw_path: str) -> tuple[Path, bytes]:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ArtifactError("artifact path is required")
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    try:
        # Reject a symlink at the user boundary. O_NOFOLLOW closes the small
        # race between validation and reading the file.
        if candidate.is_symlink():
            raise ArtifactError("symlink artifacts are not accepted")
        resolved = candidate.resolve(strict=True)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(str(resolved), flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ArtifactError("artifact must be a regular file")
            if info.st_size > MAX_ARTIFACT_BYTES:
                raise ArtifactError(f"artifact exceeds {MAX_ARTIFACT_BYTES} byte limit")
            chunks: list[bytes] = []
            remaining = MAX_ARTIFACT_BYTES + 1
            while remaining > 0:
                chunk = os.read(fd, min(1024 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            if len(data) > MAX_ARTIFACT_BYTES:
                raise ArtifactError(f"artifact exceeds {MAX_ARTIFACT_BYTES} byte limit")
            return resolved, data
        finally:
            os.close(fd)
    except ArtifactError:
        raise
    except FileNotFoundError as exc:
        raise ArtifactError("artifact does not exist") from exc
    except OSError as exc:
        raise ArtifactError(f"artifact could not be read: {exc}") from exc


def parse_nmap_xml(data: bytes, source: dict[str, Any]) -> dict[str, Any]:
    base = _base(source, data, "nmap-xml", "nmap.xml")
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        base.update({"state": "tool_error", "error": "DOCTYPE/entity declarations are not accepted"})
        return base
    try:
        root = ET.fromstring(data)
    except (ET.ParseError, ValueError) as exc:
        base.update({"state": "tool_error", "error": f"invalid XML: {exc}"})
        return base
    if root.tag.rsplit("}", 1)[-1] != "nmaprun":
        base.update({"state": "tool_error", "error": "XML root is not nmaprun"})
        return base
    hosts: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    elements = lambda name: [item for item in root.iter() if item.tag.rsplit("}", 1)[-1] == name]
    for host in elements("host")[:512]:
        status = next(iter([item for item in host if item.tag.rsplit("}", 1)[-1] == "status"]), None)
        addresses = [item.attrib.get("addr", "") for item in host if item.tag.rsplit("}", 1)[-1] == "address" and item.attrib.get("addr")]
        names = [item.attrib.get("name", "") for item in elements("hostname") if item.attrib.get("name") and host in list(item.iterancestors())] if hasattr(host, "iterancestors") else [item.attrib.get("name", "") for item in host.iter() if item.tag.rsplit("}", 1)[-1] == "hostname" and item.attrib.get("name")]
        valid_addresses = []
        for address in addresses:
            try: ipaddress.ip_address(address); valid_addresses.append(address)
            except ValueError: parse_errors.append("invalid host address observed")
        host_item: dict[str, Any] = {"addresses": valid_addresses[:8], "hostnames": [redact(name) for name in names[:8]], "status": status.attrib.get("state") if status is not None else "unknown", "ports": []}
        for port in [item for item in host.iter() if item.tag.rsplit("}", 1)[-1] == "port"]:
            state = next(iter([item for item in port if item.tag.rsplit("}", 1)[-1] == "state"]), None)
            service = next(iter([item for item in port if item.tag.rsplit("}", 1)[-1] == "service"]), None)
            protocol, port_id = port.attrib.get("protocol"), port.attrib.get("portid")
            try:
                if protocol not in {"tcp", "udp", "sctp"} or not port_id or not (1 <= int(port_id) <= 65535): raise ValueError
            except ValueError:
                parse_errors.append("invalid port observation")
                continue
            port_item = {"protocol": protocol, "port": port_id, "state": state.attrib.get("state") if state is not None else "unknown"}
            if service is not None:
                port_item["service"] = redact(service.attrib.get("name", ""))
                for key in ("product", "version", "extrainfo"):
                    if service.attrib.get(key): port_item[key] = redact(service.attrib[key])
            host_item["ports"].append(port_item)
            if port_item["state"] == "open":
                observations.append({"type": "open_port", "host": valid_addresses[0] if valid_addresses else (names[0] if names else "unknown"), "protocol": protocol, "port": port_id, "service": port_item.get("service"), "evidence_ref": "nmaprun.host.ports.port.state"})
        hosts.append(host_item)
    hosts = hosts[:512]
    observations = observations[:2048]
    base.update({
        "state": "tool_error" if parse_errors and not hosts else "observed" if hosts else "inconclusive",
        "scanner": redact(root.attrib.get("scanner", "nmap")),
        "scanner_arguments": redact(root.attrib.get("args", "")),
        "hosts": hosts,
        "observations": observations,
        "parse_errors": parse_errors[:20],
        "summary": f"Observed {len(hosts)} host record(s) and {len(observations)} open-port observation(s).",
        "limitations": ["This parser reports tool observations only; it does not confirm vulnerabilities or host security."],
    })
    return base


def parse_http_headers(text: str, source: dict[str, Any]) -> dict[str, Any]:
    data = text.encode("utf-8", "replace")
    base = _base(source, data, "http-headers", "curl.headers")
    safe = redact(text)
    blocks = re.split(r"(?=^HTTP/\d(?:\.\d)?\s+\d{3}\b)", safe, flags=re.MULTILINE)
    blocks = [block for block in blocks if block.strip()]
    if not blocks:
        base.update({"state": "tool_error", "error": "no HTTP response status line observed"})
        return base
    block = blocks[-1]
    lines = block.splitlines()
    match = re.match(r"^HTTP/\d(?:\.\d)?\s+(\d{3})(?:\s+(.*))?$", lines[0].strip())
    if not match:
        base.update({"state": "tool_error", "error": "invalid HTTP status line"})
        return base
    headers: list[dict[str, str]] = []
    for line in lines[1:]:
        if not line.strip():
            break
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        if name.strip(): headers.append({"name": name.strip().lower(), "value": value.strip()[:2048]})
    redirects = [header["value"] for header in headers if header["name"] == "location"]
    base.update({
        "state": "observed",
        "status_code": int(match.group(1)),
        "reason": match.group(2) or "",
        "headers": headers[:200],
        "redirects": redirects[:10],
        "redirect_requires_new_scope_check": bool(redirects),
        "observations": [{"type": "http_header", **header, "evidence_ref": "curl.response.headers"} for header in headers[:200]],
        "summary": f"Observed HTTP status {match.group(1)} with {len(headers)} response header(s).",
        "limitations": ["Headers are observations, not proof of a vulnerability or secure configuration.", "Redirect destinations are reported but never followed automatically; a new scope check is required."],
    })
    return base


def parse_text(data: bytes, source: dict[str, Any]) -> dict[str, Any]:
    base = _base(source, data, "text", "text.metadata")
    text = sanitize(data.decode("utf-8", "replace"))
    base.update({
        "state": "inconclusive",
        "line_count": len(text.splitlines()),
        "summary": "Artifact was hashed and bounded, but no reviewed parser was selected.",
        "observations": [],
        "limitations": ["No finding is inferred from unparsed text."],
    })
    return base


def analyze_bytes(data: bytes, *, kind: str = "auto", source: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(kind, str):
        raise ArtifactError("artifact kind must be a string")
    if not isinstance(data, bytes):
        raise ArtifactError("artifact data must be bytes")
    if len(data) > MAX_ARTIFACT_BYTES:
        raise ArtifactError(f"artifact exceeds {MAX_ARTIFACT_BYTES} byte limit")
    source = source or {"kind": "memory", "identity": "memory"}
    kind = kind.lower()
    if kind in ("nmap", "nmap-xml", "xml") or (kind == "auto" and data.lstrip().startswith(b"<nmaprun")):
        return parse_nmap_xml(data, source)
    if kind in ("http", "http-headers", "headers") or (kind == "auto" and re.search(rb"^HTTP/\d(?:\.\d)?\s+\d{3}", data, re.MULTILINE)):
        return parse_http_headers(data.decode("utf-8", "replace"), source)
    return parse_text(data, source)


def analyze_path(raw_path: str, kind: str = "auto") -> dict[str, Any]:
    if not isinstance(kind, str):
        raise ArtifactError("artifact kind must be a string")
    path, data = _read_path(raw_path)
    source = {"kind": "file", "path": str(path), "identity": str(path)}
    if kind == "auto":
        if path.suffix.lower() in (".xml", ".nmap"):
            kind = "nmap-xml"
    return analyze_bytes(data, kind=kind, source=source)


def analyze_operation_http(text: str, operation_id: str) -> dict[str, Any]:
    return parse_http_headers(text, {"kind": "operation_output", "operation_id": operation_id, "identity": operation_id})
