"""
Maya DCC adapter: uses input core for asset/component data and path resolution.

Provides:
- load_asset_version_data_for_maya: load cached version/component data
- resolve_component_path_maya: resolve path with optional Maya frame normalization

Usage from Maya:
    from ftrack_inout.input.dcc.maya import load_asset_version_data_for_maya
    cached = load_asset_version_data_for_maya(session, asset_id)

    from ftrack_inout.input.core import resolve_component_path
    path = resolve_component_path(session, component)
    # For sequences: normalize %04d -> <f> if needed (Maya frame syntax)
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger("ftrack_inout.input.dcc.maya")


def load_asset_version_data_for_maya(
    session: Any,
    asset_id: str,
    force_refresh: bool = False,
) -> Optional[Dict[str, Any]]:
    """
    Load version/component cached data using input core.

    Args:
        session: ftrack_api.Session
        asset_id: Ftrack asset ID
        force_refresh: If True, query fresh from server

    Returns:
        Cached data dict from load_asset_version_component_data, or None.
    """
    if not session:
        return None
    from ftrack_inout.input.core import load_asset_version_component_data
    return load_asset_version_component_data(session, str(asset_id), force_refresh=force_refresh)


def normalize_path_for_maya_frames(path: str) -> str:
    """
    Normalize frame placeholders in path for Maya.

    Ftrack/disk paths often use printf-style: frame.%04d.ext or frame.####.ext.
    Maya uses <f> or <frame> for frame substitution.

    This is optional - use when loading image sequences or cached sequences in Maya.

    Args:
        path: Raw path (e.g. /path/to/cache.####.bgeo)

    Returns:
        Path with Maya-style frame placeholder if detected.
    """
    if not path:
        return path
    # Common patterns: %04d, %d, ####
    path = re.sub(r'%0*(\d*)d', r'<f>', path)
    path = re.sub(r'#+', r'<f>', path)
    return path


def resolve_component_path_maya(
    session: Any,
    component: Any,
    location: Optional[Any] = None,
    normalize_frames: bool = False,
) -> str:
    """
    Resolve filesystem path for component, with optional Maya frame normalization.

    Args:
        session: ftrack_api.Session
        component: Component entity or dict with id
        location: Explicit location, or None for auto primary Disk
        normalize_frames: If True, convert %04d / #### to <f>

    Returns:
        Filesystem path string

    Raises:
        ValueError: When path cannot be resolved
    """
    from ftrack_inout.input.core import resolve_component_path

    path = resolve_component_path(session, component, location=location)
    if normalize_frames:
        path = normalize_path_for_maya_frames(path)
    return path


def get_session_for_maya() -> Optional[Any]:
    """
    Get Ftrack session. Uses common session factory if available.

    Returns:
        ftrack_api.Session or None
    """
    try:
        from ftrack_inout.common.session_factory import get_shared_session
        return get_shared_session()
    except ImportError:
        try:
            import ftrack_api
            return ftrack_api.Session()
        except Exception as e:
            logger.warning("Failed to get Ftrack session: %s", e)
            return None


# --- Example usage (run from Maya script editor) ---
# """
# Example: Load asset versions and resolve component path in Maya
#
# 1. Ensure ftrack_plugins is in sys.path
# 2. Run in Maya:
#
# import sys
# sys.path.insert(0, r"G:/mroya/ftrack_plugins")
#
# from ftrack_inout.input.dcc.maya import (
#     get_session_for_maya,
#     load_asset_version_data_for_maya,
#     resolve_component_path_maya,
# )
# from ftrack_inout.input.core import (
#     get_component_menu_data,
#     resolve_component_to_select,
#     compute_version_labels_with_indicators,
# )
#
# session = get_session_for_maya()
# if not session:
#     print("No Ftrack session")
# else:
#     asset_id = "YOUR_ASSET_ID"
#     cached = load_asset_version_data_for_maya(session, asset_id, force_refresh=True)
#     if cached:
#         version_info = cached["version_info"]
#         print("Versions:", [v["name"] for v in version_info])
#         version_id = version_info[0]["id"]
#         items, labels = get_component_menu_data(cached, version_id)
#         print("Components:", labels)
#         comp_id = resolve_component_to_select(cached, version_id)
#         if comp_id:
#             component = session.get("Component", comp_id)
#             path = resolve_component_path_maya(session, component)
#             print("Path:", path)
# """
