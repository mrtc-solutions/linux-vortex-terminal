"""Named execution policies. Guardian remains the evaluator."""
from __future__ import annotations

from .guardian import policy_defaults


def named(profile: str) -> dict:
    return policy_defaults(profile)
