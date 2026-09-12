"""One copy-paste install block for every missing AI component.

Aggregates the verified upstream commands for each layer that is actually
missing on this host (Ollama runtime, GGUF engine, GGUF model files, and the
individual AI assistants). VORTEX never executes any of it: the operator
copies the block into their main Linux terminal, pastes it, and returns to
click REFRESH ALL. Sections that are already present are omitted, so the
block always reflects live state. Assistants without a uniquely verified
repository contribute comment lines only — a pasteable block must never
turn into an unverified download.
"""
from __future__ import annotations

import re
from typing import Any

# Lines that may execute verbatim in the combined block. Anything else is
# comment-safe only: the upstream install guides mix prose with commands, and
# a pasted block must never turn a sentence (or a backtick) into a shell
# command.
_SHELL_COMMAND = re.compile(
    r"^(?:sudo\s+)?(?:"
    r"(?:curl|wget|mkdir|chmod|ln|cd|git|go|pip|pip3|pipx|python[0-9.]*|"
    r"cmake|make|docker|ollama|apt|apt-get|brew|npm|npx|pnpm|tar|unzip|source)\b"
    r"|\.\s"
    r")"
)
_SHELL_DANGEROUS = re.compile(r"[`;$\\]|>\s*\S")


def _import(name: str):
    try:
        import importlib
        return importlib.import_module(name)
    except ImportError:
        import importlib
        return importlib.import_module("backend." + name)


def _section_commands_ollama(runtime: dict[str, Any]) -> list[str]:
    return [
        "curl -fsSL https://ollama.com/install.sh | sh",
        "ollama pull llama3.2:3b        # fast/primary advisory model",
        "ollama pull qwen2.5:3b         # planner/specialist model",
    ]


def _section_commands_gguf_engine() -> list[str]:
    return [
        "python3 -m pip install --user llama-cpp-python   # in-process engine (recommended)",
        "# alternative: build llama.cpp for llama-cli:",
        "# git clone https://github.com/ggml-org/llama.cpp.git && cd llama.cpp && cmake -B build && cmake --build build --config Release -j",
    ]


def _section_commands_gguf_models() -> list[str]:
    return [
        "mkdir -p ~/linux-vortex-terminal/models",
        "# put Llama-3.2-3B-Instruct-Q4_K_M.gguf and Qwen2.5-3B-Instruct-Q4_K_M.gguf in that folder",
        "# exact download links: VORTEX -> AI OPS window -> Step 1 box (or docs/LOCAL_GGUF.md)",
    ]


def assemble(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    """Honest, live assembly of the missing-AI-stack install block."""
    settings = settings or {}
    sections: list[dict[str, Any]] = []

    try:
        runtime = _import("models.manager").runtime_status()
        if not runtime.get("installed"):
            sections.append({
                "id": "ollama",
                "title": "Ollama loopback runtime (secondary local-LLM layer)",
                "commands": _section_commands_ollama(runtime),
                "note": "Binds to loopback only. In-app alternative: MODELS view -> Local model runtime -> INSTALL OLLAMA (verifies release size + SHA-256).",
            })
    except Exception:
        pass

    try:
        gguf = _import("models.gguf").status(settings)
        files = gguf.get("files") or []
        valid = sum(1 for item in files if item.get("valid"))
        engine = (gguf.get("engine") or {}).get("state")
        if engine != "ready":
            sections.append({
                "id": "gguf-engine",
                "title": "On-device GGUF engine (primary local-LLM layer)",
                "commands": _section_commands_gguf_engine(),
                "note": "Lets VORTEX run your own .gguf files directly, without Ollama.",
            })
        if not valid:
            sections.append({
                "id": "gguf-models",
                "title": "On-device GGUF model files",
                "commands": _section_commands_gguf_models(),
                "note": "Your own on-device models; VORTEX validates each file before it can be used.",
            })
    except Exception:
        pass

    try:
        council = _import("agents.council").discover()
        upstream = _import("agents.upstream")
        for agent in council:
            if (agent.get("health") or {}).get("healthy"):
                continue
            agent_id = str(agent.get("id") or "")
            sections.append({
                "id": f"agent:{agent_id}",
                "title": f"AI assistant: {agent.get('name') or agent_id}",
                "commands": upstream.install_guide(agent_id),
                "note": agent.get("notes") or "",
            })
    except Exception:
        pass

    return {
        "install_commands": {
            "sections": sections,
            "combined": render_combined(sections),
            "nothing_missing": not sections,
        }
    }


def _paste_safe_line(line: str) -> str:
    """Return the line ready for a pasted block: commands execute, everything
    else becomes a comment. Backticks, substitutions, and redirects can never
    survive into an executable line."""
    stripped = str(line).strip()
    if not stripped:
        return ""
    if stripped.startswith("#"):
        return stripped
    if _SHELL_COMMAND.match(stripped) and not _SHELL_DANGEROUS.search(stripped):
        return stripped
    return "# " + stripped


def render_combined(sections: list[dict[str, Any]]) -> str:
    if not sections:
        return ("# VORTEX AI stack: nothing is missing on this host.\n"
                "# Every layer (GGUF, Ollama, assistants) that VORTEX probes is present.")
    lines = [
        "# ============================================================",
        "# VORTEX AI stack - paste into your MAIN Linux terminal",
        "# Only what is actually missing on this host is listed below.",
        "# VORTEX does not run any of this itself; no silent installs.",
        "# ============================================================",
        "",
    ]
    for section in sections:
        lines.append(f"# --- {section['title']} ---")
        for line in section.get("commands") or []:
            safe = _paste_safe_line(line)
            if safe:
                lines.append(safe)
        if section.get("note"):
            lines.append(f"# {section['note']}")
        lines.append("")
    lines.append("# Done? Click REFRESH ALL in VORTEX so the rescan sees the result.")
    return "\n".join(lines)
