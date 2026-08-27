from .base import AgentAdapter, AgentManifest

ADAPTER = AgentAdapter(AgentManifest(
    "strix", "Strix", "https://github.com/usestrix/strix", "Apache-2.0", ("strix",),
    ("advisory-pentest", "fix-suggestions"),
))
