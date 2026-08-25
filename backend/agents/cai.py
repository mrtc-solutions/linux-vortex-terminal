from .base import AgentAdapter, AgentManifest

ADAPTER = AgentAdapter(AgentManifest(
    "cai", "CAI", "https://github.com/aliasrobotics/cai", "MIT", ("cai",),
    ("advisory-pentest", "cli-assistant"),
))
