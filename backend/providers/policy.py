"""Cost-protection policy engine.

``free_only_mode`` is the global $0 guarantee: when it is on, Vortex never
routes to a model whose current price is not known to be $0, never upgrades
to a paid fallback, and never treats trial/promotional credit as free.
"""
from __future__ import annotations

import os
from typing import Any


def _env_flag(name: str) -> bool | None:
    raw = os.environ.get(name)
    if raw is None:
        return None
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def cost_policy(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or {}
    free_only = settings.get("free_only_mode", True) is True
    env_override = _env_flag("FREE_ONLY_MODE")
    if env_override is not None:
        # The environment can only make policy stricter or confirm it; an env
        # value of false still requires allow_paid_providers in settings.
        free_only = env_override or free_only
    allow_paid = settings.get("allow_paid_providers", False) is True
    if free_only:
        allow_paid = False
    return {
        "free_only": free_only,
        "allow_paid_providers": allow_paid,
        "allow_unknown_pricing": settings.get("allow_unknown_pricing", False) is True and not free_only,
    }


def provider_allowed(policy: dict[str, Any], definition: dict[str, Any], overrides: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Can this provider be considered at all under the current policy?"""
    overrides = overrides or {}
    free_status = str(definition.get("free_status") or "unknown")
    if not policy.get("free_only"):
        return True, "paid providers allowed by policy"
    if free_status == "free":
        return True, "provider is $0"
    if free_status == "conditional":
        return True, "provider has a $0 tier; per-model pricing still enforced"
    # unknown pricing
    if overrides.get("allow_in_free_mode") is True:
        return True, "operator verified this provider's free terms and enabled it for free-only mode"
    return False, "FREE STATUS: UNKNOWN — disabled under free-only mode until the operator verifies the provider's terms"


def model_allowed(policy: dict[str, Any], definition: dict[str, Any], model_entry: dict[str, Any] | None, overrides: dict[str, Any] | None = None) -> tuple[bool, str]:
    """Final gate before a request is sent to a specific model."""
    ok, reason = provider_allowed(policy, definition, overrides)
    if not ok:
        return False, reason
    if not policy.get("free_only"):
        return True, "policy allows paid models"
    if str(definition.get("mode")) == "local":
        return True, "local inference is $0"
    free = (model_entry or {}).get("free")
    if free is True:
        return True, "model verified $0"
    if free is False:
        return False, "model is currently priced above $0 — blocked by free-only mode"
    # Unknown model pricing on a conditional/free provider.
    if (overrides or {}).get("allow_in_free_mode") is True:
        return True, "operator override: provider terms verified by operator"
    if str(definition.get("free_status")) == "free":
        return True, "provider is $0 by construction"
    return False, "model pricing is unverified — blocked by free-only mode"
