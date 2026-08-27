from .base import AgentAdapter, AgentManifest

ADAPTER = AgentAdapter(AgentManifest(
    "halo", "HALO", "", "unknown", ("halo", "halo-ai"),
    ("advisory",), notes="No uniquely verified repository is configured.",
))
