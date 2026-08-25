from .base import AgentAdapter, AgentManifest

ADAPTER = AgentAdapter(AgentManifest(
    "hexstrike", "HexStrike", "https://github.com/0x4m4/hexstrike-ai", "MIT", ("hexstrike", "hexstrike-ai"),
    ("mcp-tools",),
))
