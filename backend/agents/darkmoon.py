from .base import AgentAdapter, AgentManifest

ADAPTER = AgentAdapter(AgentManifest(
    "darkmoon", "DarkMoon", "", "unknown", ("darkmoon",),
    ("advisory",), notes="No uniquely verified repository is configured.",
))
