"""Reader for Claude account info from .claude.json."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Friendly labels keyed by substrings found in seatTier / userRateLimitTier.
_SEAT_TIER_LABELS = {
    "enterprise": "Enterprise",
    "max_20": "Claude Code Max 20x",
    "max20": "Claude Code Max 20x",
    "max_5": "Claude Code Max 5x",
    "max5": "Claude Code Max 5x",
    "pro": "Claude Code Pro",
}

# organizationRateLimitTier values are very explicit (e.g. "default_claude_max_5x").
_ORG_RATE_LIMIT_LABELS = {
    "max_20x": "Claude Code Max 20x",
    "max_5x": "Claude Code Max 5x",
    "enterprise": "Enterprise",
    "claude_ai": "Claude Code Pro",  # "default_claude_ai"
}

# organizationType as a last resort.
_ORG_TYPE_LABELS = {
    "claude_enterprise": "Enterprise",
    "claude_max": "Claude Code Max",
    "claude_pro": "Claude Code Pro",
}


def _match(raw: Optional[str], mapping: Dict[str, str]) -> str:
    if not raw:
        return ""
    t = raw.lower().replace("-", "_")
    for key, label in mapping.items():
        if key in t:
            return label
    return ""


def get_account_info(data_path: Optional[str] = None) -> Dict[str, Any]:
    """Read oauthAccount fields from the .claude.json for the active instance.

    Args:
        data_path: Path to the Claude projects directory (e.g. ~/.claude-work/projects).
                   The .claude.json file is expected one level up (e.g. ~/.claude-work/).

    Returns:
        Dict with display_name, email, org_name, seat_tier, plan_label.
        plan_label is derived from account fields in priority order:
        seatTier → userRateLimitTier → organizationRateLimitTier → organizationType.
    """
    result = {
        "display_name": "",
        "email": "",
        "org_name": "",
        "seat_tier": "",
        "plan_label": "",
    }

    base = Path(data_path).expanduser() if data_path else Path.home()

    # For --instance work/personal the .claude.json sits one level above /projects.
    # Standard default install uses ~/.claude.json.
    candidates = [
        base.parent / ".claude.json",
        base.parent.parent / ".claude.json",
        Path.home() / ".claude.json",
    ]
    claude_json = next((p for p in candidates if p.exists()), None)
    if claude_json is None:
        return result

    try:
        with open(claude_json, encoding="utf-8") as f:
            data = json.load(f)
        acct = data.get("oauthAccount") or {}
        result["display_name"] = acct.get("displayName", "")
        result["email"] = acct.get("emailAddress", "")
        result["org_name"] = acct.get("organizationName", "")
        result["seat_tier"] = acct.get("seatTier") or ""

        plan_label = (
            _match(acct.get("seatTier"), _SEAT_TIER_LABELS)
            or _match(acct.get("userRateLimitTier"), _SEAT_TIER_LABELS)
            or _match(acct.get("organizationRateLimitTier"), _ORG_RATE_LIMIT_LABELS)
            or _match(acct.get("organizationType"), _ORG_TYPE_LABELS)
        )
        result["plan_label"] = plan_label
    except Exception as e:
        logger.debug("Could not read account info from %s: %s", claude_json, e)

    return result
