"""
Load Ftrack credentials from standard Ftrack Connect storage or .env fallback.

Standard path (same as ftrack Connect):
- Windows: %LOCALAPPDATA%\\ftrack\\ftrack-connect\\
- Files: credentials.json (preferred) or config.json (legacy)

Structure: {"accounts": [{"server_url": "...", "api_user": "...", "api_key": "..."}]}
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Credential keys we set in os.environ
FTRACK_CRED_KEYS = ("FTRACK_SERVER", "FTRACK_API_USER", "FTRACK_API_KEY")


def _get_ftrack_connect_dir() -> Optional[Path]:
    """Return standard Ftrack Connect config directory, or None if not found."""
    try:
        import platformdirs
        base = Path(platformdirs.user_data_dir("ftrack-connect", "ftrack"))
        if base.is_dir():
            return base
        # Dir might not exist yet; parent should exist
        if base.parent.is_dir():
            return base
    except ImportError:
        pass
    # Fallback: Windows LOCALAPPDATA
    local_app = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app:
        base = Path(local_app) / "ftrack" / "ftrack-connect"
        return base
    return None


def _load_from_ftrack_connect_json(path: Path) -> Optional[dict[str, str]]:
    """Read credentials from config.json/credentials.json. Returns dict or None."""
    if not path.is_file():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.debug("Failed to read %s: %s", path, e)
        return None
    accounts = data.get("accounts")
    if not accounts or not isinstance(accounts, list):
        return None
    acc = accounts[0]
    if not isinstance(acc, dict):
        return None
    server = (acc.get("server_url") or "").strip()
    if not server:
        return None
    # Normalize server URL (ftrack API expects trailing slash)
    if not server.endswith("/"):
        server = server + "/"
    user = (acc.get("api_user") or "").strip()
    key = (acc.get("api_key") or "").strip()
    return {
        "FTRACK_SERVER": server,
        "FTRACK_API_USER": user,
        "FTRACK_API_KEY": key,
    }


def load_ftrack_credentials_from_connect() -> Optional[dict[str, str]]:
    """
    Load FTRACK_SERVER, FTRACK_API_USER, FTRACK_API_KEY from standard Ftrack Connect storage.

    Returns dict with keys FTRACK_SERVER, FTRACK_API_USER, FTRACK_API_KEY, or None if not found.
    """
    base = _get_ftrack_connect_dir()
    if not base:
        return None
    for name in ("credentials.json", "config.json"):
        creds = _load_from_ftrack_connect_json(base / name)
        if creds:
            logger.debug("Loaded Ftrack credentials from %s", base / name)
            return creds
    return None


def load_ftrack_credentials_into_env(
    *,
    prefer_connect: bool = True,
    dotenv_paths: Optional[list[Path]] = None,
) -> bool:
    """
    Load Ftrack credentials into os.environ. Does not override existing values.

    Order:
    1. If prefer_connect: try Ftrack Connect config.json/credentials.json
    2. If dotenv_paths: try each .env file
    3. Return True if any credentials were loaded
    """
    loaded = False

    if prefer_connect:
        creds = load_ftrack_credentials_from_connect()
        if creds:
            for key in FTRACK_CRED_KEYS:
                val = creds.get(key)
                if val and key not in os.environ:
                    os.environ[key] = val
                    loaded = True
            if loaded:
                return True

    if dotenv_paths:
        try:
            import dotenv
        except ImportError:
            dotenv = None
        if dotenv:
            for p in dotenv_paths:
                if p.is_file():
                    try:
                        # dotenv loads into os.environ, doesn't override by default
                        result = dotenv.load_dotenv(dotenv_path=p)
                        if result:
                            loaded = True
                        logger.debug("Loaded .env from %s", p)
                        break  # First valid .env wins
                    except Exception as e:
                        logger.debug("Failed to load %s: %s", p, e)

    return loaded
