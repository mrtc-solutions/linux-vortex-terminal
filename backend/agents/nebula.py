from .base import AgentAdapter, AgentManifest

ADAPTER = AgentAdapter(AgentManifest(
    "nebula", "Nebula", "https://github.com/BerylliumSec/nebula", "BSD-2-Clause", ("nebula",),
    ("advisory-pentest", "cli-assistant"),
))
