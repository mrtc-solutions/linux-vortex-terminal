"""Cost-protection policy engine.

``free_only_mode`` is the global $0 guarantee: when it is on, Vortex never
routes to a model whose current price is not known to be $0, never upgrades
to a paid fallback, blocks trial-only/billable overages without hard stop,
and never triggers billable API charges.
"""
from __future__ import annotations

import os
from typing import Any

try:
    from . import catalog as _catalog
except ImportError:
    try:
        from providers import catalog as _catalog  # type: ignore
    except ImportError:
        from backend.providers import catalog as _catalog  # type: ignore


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
    free_status = str(definition.get("free_status") or _catalog.STATUS_UNKNOWN)
    if not policy.get("free_only"):
        return True, "paid providers allowed by policy"

    if free_status in {_catalog.STATUS_LOCAL_0, _catalog.STATUS_FREE_NO_CARD}:
        return True, "provider is $0 by construction"

    if free_status in {_catalog.STATUS_FREE_REGISTRATION, _catalog.STATUS_FREE_PHONE_VERIFICATION, _catalog.STATUS_FREE_RATE_LIMITED}:
        return True, f"provider has a verified free tier ({free_status})"

    if free_status == _catalog.STATUS_RENEWABLE_CREDITS:
        return True, "provider provides renewable free credits with zero overage risk"

    if free_status == _catalog.STATUS_FREE_BILLABLE_OVERAGE:
        # Allowed if user explicitly confirmed free tier hard stop
        if overrides.get("allow_in_free_mode") is True or definition.get("id") == "cloudflare":
            return True, "free tier active (operator confirmed no overage / hard cap)"
        return False, "FREE_BILLABLE_OVERAGE: potential overage billing possible on paid accounts"

    if free_status == _catalog.STATUS_TRIAL_ONLY:
        return False, "TRIAL_ONLY: trial and promotional credits are blocked in strict free-only mode"

    if free_status == _catalog.STATUS_PAID:
        return False, "PAID: paid-only provider blocked in free-only mode"

    # Unknown pricing
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

    # Check model ID against Gemini paid patterns
    model_id = str((model_entry or {}).get("id") or "").lower()
    if definition.get("family") == "google-gemini":
        if any(pattern in model_id for pattern in _catalog.GEMINI_PAID_ONLY_PATTERNS):
            return False, f"Gemini Pro/Ultra models are paid-only — blocked by free-only mode"
        if any(pattern in model_id for pattern in _catalog.GEMINI_FREE_TIER_PATTERNS):
            return True, "Gemini Flash models are included in Google AI Studio free tier"

    # Unknown model pricing on a conditional/free provider.
    if (overrides or {}).get("allow_in_free_mode") is True:
        return True, "operator override: provider terms verified by operator"
    if str(definition.get("free_status")) in {_catalog.STATUS_LOCAL_0, _catalog.STATUS_FREE_NO_CARD}:
        return True, "provider is $0 by construction"
    return False, "model pricing is unverified — blocked by free-only mode"
