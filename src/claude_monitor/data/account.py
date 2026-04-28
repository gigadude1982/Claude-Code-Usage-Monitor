"""Reader for Claude account info from .claude.json."""

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def get_account_info(data_path: Optional[str] = None) -> Dict[str, Any]:
    """Read oauthAccount fields from .claude.json next to the data directory.

    Args:
        data_path: Path to the Claude projects directory (e.g. ~/.claude-work/projects).
                   The .claude.json file is expected one level up.

    Returns:
        Dict with display_name, email, org_name, seat_tier — empty strings if unavailable.
    """
    result = {"display_name": "", "email": "", "org_name": "", "seat_tier": ""}

    if not data_path:
        return result

    claude_json = Path(data_path).expanduser().parent / ".claude.json"
    if not claude_json.exists():
        return result

    try:
        with open(claude_json, encoding="utf-8") as f:
            data = json.load(f)
        acct = data.get("oauthAccount") or {}
        result["display_name"] = acct.get("displayName", "")
        result["email"] = acct.get("emailAddress", "")
        result["org_name"] = acct.get("organizationName", "")
        result["seat_tier"] = acct.get("seatTier", "")
    except Exception as e:
        logger.debug("Could not read account info from %s: %s", claude_json, e)

    return result
