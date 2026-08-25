from .base import AgentAdapter, AgentManifest

ADAPTER = AgentAdapter(AgentManifest(
    "hackerai", "HackerAI", "https://hackerai.co", "proprietary/unknown", ("hackerai",),
    ("advisory-pentest",), notes="No public local CLI was verified. Health check looks only for a local binary.",
))
