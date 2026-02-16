"""
Standalone DCC adapter: bridge between FtrackApiClient and input core.

Gets session from api client, calls core functions. Used by FtrackInputWidget.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ftrack_inout.input.core import load_asset_version_component_data


def load_asset_version_data_for_standalone(
    api_client: Any,
    asset_id: str,
    force_refresh: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Load version/component cached data using core. Standalone uses api_client.get_session().

    Args:
        api_client: FtrackApiClient with get_session()
        asset_id: Ftrack asset ID
        force_refresh: If True, query fresh from server (bypass relationship cache)

    Returns:
        Cached data dict from load_asset_version_component_data, or None.
    """
    get_session = getattr(api_client, "get_session", None)
    session = get_session() if callable(get_session) else None
    if not session:
        return None
    return load_asset_version_component_data(session, str(asset_id), force_refresh=force_refresh)
