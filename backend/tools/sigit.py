"""Reviewed SIGIT OSINT capability catalog.

SIGIT — "Simple Information Gathering Toolkit" — is a modular Python OSINT CLI
(MIT). VORTEX does not vendor, install, or auto-run SIGIT. Instead it reviews
the toolkit's service surface and treats it as engagement-gated OSINT
capability alongside the existing amass / subfinder / theharvester adapters:

- services that have a safe, reviewed equivalent are mapped onto the existing
  typed adapters (nmap, amass, dig/nslookup, whois, curl header discovery);
- services with no reviewed local equivalent (username / phone / email /
  breach / GitHub / tech / reverse-IP recon) are reported as reviewed
  capabilities that require an authorized engagement and the operator-installed
  ``sigit`` interactive TUI inside a PTY session. VORTEX never fabricates their
  output and never invents a subcommand argv for the TUI.

Reference: the canonical upstream repository (``termuxhackers-id/SIGIT``) was
unreachable at review time. The 14-service feature set below is cross-referenced
against the MIT rewrite ``UW4IS/SIGIT-0`` (UserRecon, PhoneInfo, MailFinder,
IPLocation, SubdomainScan, PortScanner, DNSRecon, WHOISLookup, SSLChecker,
HeaderAnalyzer, GitHubRecon, BreachChecker, TechDetector, ReverseIP).
"""
from __future__ import annotations

import re
from typing import Any

SIGIT_CLI_NAMES = ("sigit", "sigit.sh")

# SIGIT's service surface. ``safe_adapter`` is the reviewed, typed equivalent
# VORTEX can already plan; ``None`` means there is no safe local equivalent and
# the capability must run inside the operator-installed TUI. ``keywords`` are
# intentionally phrase-scoped so a generic word like "user" or "port" does not
# hijack an existing reviewed adapter. ``whois`` carries no keywords because the
# existing whois adapter handles those requests first.
SIGIT_SERVICES: dict[str, dict[str, Any]] = {
    "userrecon": {
        "name": "UserRecon", "number": "01", "title": "Username reconnaissance",
        "target_kind": "username",
        "keywords": ("userrecon", "user recon", "username recon", "username reconnaissance",
                     "username lookup", "check username", "username osint", "social media recon", "socmint"),
        "safe_adapter": None,
    },
    "phoneinfo": {
        "name": "PhoneInfo", "number": "02", "title": "Phone number information",
        "target_kind": "phone",
        "keywords": ("phoneinfo", "phone info", "phone information", "phone lookup",
                     "phone number lookup", "phone number info", "number information", "phone carrier"),
        "safe_adapter": None,
    },
    "mailfinder": {
        "name": "MailFinder", "number": "03", "title": "Find email with a name",
        "target_kind": "email",
        "keywords": ("mailfinder", "mail finder", "email finder", "find email", "find emails",
                     "email generation", "generate email", "generate emails", "email permutation"),
        "safe_adapter": None,
    },
    "iplocation": {
        "name": "IPLocation", "number": "04", "title": "IP to location lookup",
        "target_kind": "ip",
        "keywords": ("iplocation", "ip location", "ip to location", "locate ip",
                     "ip geolocation", "geoip", "ip geo"),
        "safe_adapter": None,
    },
    "subdomain": {
        "name": "SubdomainScan", "number": "05", "title": "Subdomain enumeration",
        "target_kind": "hostname",
        "keywords": ("subdomain scan", "subdomain enumeration", "subdomain discovery",
                     "enumerate subdomains", "find subdomains", "subdomain recon"),
        "safe_adapter": "security.amass.passive",
    },
    "portscan": {
        "name": "PortScanner", "number": "06", "title": "Network port scanner",
        "target_kind": "hostname/ip",
        "keywords": ("port scanner", "port scan", "scan ports", "port scanning", "tcp port scan"),
        "safe_adapter": "security.nmap.discovery",
    },
    "dnsrecon": {
        "name": "DNSRecon", "number": "07", "title": "DNS reconnaissance",
        "target_kind": "hostname",
        "keywords": ("dns recon", "dns reconnaissance", "dns enumeration", "dns lookup recon"),
        "safe_adapter": "linux.network.dns",
    },
    "whois": {
        "name": "WHOISLookup", "number": "08", "title": "Domain WHOIS information",
        "target_kind": "hostname/ip",
        "keywords": (),
        "safe_adapter": "linux.network.whois",
    },
    "sslcheck": {
        "name": "SSLChecker", "number": "09", "title": "SSL/TLS certificate check",
        "target_kind": "hostname",
        "keywords": ("ssl check", "ssl checker", "ssl certificate check", "check ssl",
                     "ssl expiry", "certificate check", "ssl issuer", "tls certificate check"),
        "safe_adapter": "security.http.headers",
    },
    "headers": {
        "name": "HeaderAnalyzer", "number": "10", "title": "Security header analysis",
        "target_kind": "url",
        "keywords": ("header analyzer", "security header analysis", "header analysis",
                     "security headers check", "header score", "analyze security headers"),
        "safe_adapter": "security.http.headers",
    },
    "github": {
        "name": "GitHubRecon", "number": "11", "title": "GitHub user reconnaissance",
        "target_kind": "github-user",
        "keywords": ("github recon", "github user", "github profile", "github osint",
                     "github account", "github enumeration", "github user lookup"),
        "safe_adapter": None,
    },
    "breach": {
        "name": "BreachChecker", "number": "12", "title": "Data breach lookup",
        "target_kind": "email",
        "keywords": ("breach checker", "breach check", "data breach", "check breach",
                     "pwned", "have i been pwned", "leaked password", "breach lookup", "email breach"),
        "safe_adapter": None,
    },
    "techdetect": {
        "name": "TechDetector", "number": "13", "title": "Website tech stack detection",
        "target_kind": "url",
        "keywords": ("tech detector", "tech detect", "tech stack", "detect cms",
                     "detect framework", "detect technology", "website tech",
                     "technology detection", "wappalyzer"),
        "safe_adapter": None,
    },
    "reverseip": {
        "name": "ReverseIP", "number": "14", "title": "Reverse IP lookup",
        "target_kind": "hostname/ip",
        "keywords": ("reverse ip", "reverse dns lookup", "reverse ip lookup",
                     "hosts on same ip", "reverse ip check", "same ip sites"),
        "safe_adapter": None,
    },
}

SERVICE_ORDER: tuple[str, ...] = (
    "userrecon", "phoneinfo", "mailfinder", "iplocation", "subdomain", "portscan",
    "dnsrecon", "whois", "sslcheck", "headers", "github", "breach", "techdetect", "reverseip",
)

# Bare toolkit mentions that do not name a specific service.
GENERIC_KEYWORDS: tuple[str, ...] = ("sigit", "osint", "information gathering")

# Reserved slug for a generic toolkit mention (not a specific service).
TOOLKIT = "_toolkit"

def _keyword_hit(lower: str, keywords: tuple[str, ...]) -> bool:
    for keyword in keywords:
        if " " in keyword:
            if keyword in lower:
                return True
        elif re.search(rf"(?<![A-Za-z0-9._+-]){re.escape(keyword)}(?![A-Za-z0-9._+-])", lower):
            return True
    return False


def classify_sigit_request(text: str | None) -> str | None:
    """Return the SIGIT service slug for a request, ``TOOLKIT`` for a generic
    toolkit mention, or ``None`` when the request is not SIGIT-related."""
    lower = (text or "").lower().strip()
    if not lower or len(lower) > 8000:
        return None
    for slug in SERVICE_ORDER:
        if _keyword_hit(lower, SIGIT_SERVICES[slug]["keywords"]):
            return slug
    if _keyword_hit(lower, GENERIC_KEYWORDS):
        return TOOLKIT
    return None


def mentions_sigit(text: str | None) -> bool:
    """True when the request explicitly names the ``sigit`` CLI."""
    lower = (text or "").lower()
    return bool(re.search(r"\bsigit(?:\.sh)?\b", lower))


def probe_sigit(installed: dict[str, str] | None = None) -> dict[str, Any]:
    """Probe for an operator-installed SIGIT CLI on a safe PATH.

    Presence-only: SIGIT's entry point is an interactive TUI that ignores
    arguments, so VORTEX never invokes it for a version string."""
    found = installed
    if found is None:
        try:
            from vortex_backend import probe_executable
        except ImportError:
            from backend.vortex_backend import probe_executable
        found = {}
        for name in SIGIT_CLI_NAMES:
            probe = probe_executable(name, include_version=False)
            if probe.get("state") == "installed" and probe.get("path"):
                found[name] = str(probe["path"])
    for name in SIGIT_CLI_NAMES:
        if name in found and found[name]:
            return {"state": "installed", "executable": name, "path": str(found[name])}
    return {"state": "absent", "executable": None, "path": None}


def service_listing() -> list[dict[str, Any]]:
    """Reviewed, read-only service manifest for the capabilities surface."""
    return [
        {
            "id": slug,
            "sigit_service": service["name"],
            "number": service["number"],
            "title": service["title"],
            "target_kind": service["target_kind"],
            "family": "passive-osint",
            "network": "outbound-read",
            "risk": "high",
            "license": "MIT",
            "safe_adapter": service["safe_adapter"],
            "auto_executed": False,
            "reviewed": True,
        }
        for slug, service in SIGIT_SERVICES.items()
    ]
