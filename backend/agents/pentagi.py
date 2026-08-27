from .base import AgentAdapter, AgentManifest

ADAPTER = AgentAdapter(AgentManifest(
    "pentagi", "PentAGI", "https://github.com/vxcontrol/pentagi", "MIT", ("pentagi",),
    ("autonomous-pentest",),
))
