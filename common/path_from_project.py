"""
Path from project root for display in UI (Transfer, Asset Watcher, Scene Resources).

Uses session cache; builds path from entity names: project/folder/.../asset_name
or project/.../asset_name/vNN/component_name.
"""

from __future__ import annotations

import logging
from typing import Optional

_log = logging.getLogger(__name__)


def get_asset_display_path(session, asset_id: str) -> Optional[str]:
    """Return path from project root to asset as string: project/folder/.../asset_name.
    Uses session cache. Returns None on error or if asset has no parent chain."""
    if not session or not asset_id:
        return None
    try:
        asset = session.get("Asset", asset_id)
        if not asset:
            return None
        name = (asset.get("name") or str(asset_id)) or "?"
        parent = asset.get("parent")
        if not parent:
            return name
        path_names = [name]
        current = parent
        while current:
            n = current.get("name") or getattr(current, "entity_type", "") or "?"
            path_names.append(str(n))
            etype = getattr(current, "entity_type", None) or getattr(current, "type", None)
            if etype and str(etype).lower() == "project":
                break
            parent = current.get("parent")
            if not parent:
                break
            current = parent
        path_names.reverse()
        return "/".join(path_names)
    except Exception as e:
        _log.warning("get_asset_display_path(%s): %s", asset_id[:8] if asset_id else "", e)
        return None


def get_component_display_path(session, component_id: str) -> Optional[str]:
    """Return path from project root to component: project/.../asset_name/vNN/component_name.
    Uses session cache. Returns None on error."""
    if not session or not component_id:
        return None
    try:
        comp = session.get("Component", component_id)
        if not comp:
            return None
        comp_name = comp.get("name") or "?"
        version = comp.get("version")
        if not version:
            return comp_name
        version_num = version.get("version") or "?"
        asset = version.get("asset")
        if not asset:
            return f"v{version_num}/{comp_name}"
        asset_path = get_asset_display_path(session, str(asset["id"]))
        if not asset_path:
            asset_path = asset.get("name") or "?"
        return f"{asset_path}/v{version_num}/{comp_name}"
    except Exception as e:
        _log.warning("get_component_display_path(%s): %s", component_id[:8] if component_id else "", e)
        return None


def get_asset_display_path_from_component(session, component_id: str) -> Optional[str]:
    """Return path from project root to the asset that owns this component: project/.../asset_name.
    Uses session cache. Returns None on error."""
    if not session or not component_id:
        return None
    try:
        comp = session.get("Component", component_id)
        if not comp:
            return None
        version = comp.get("version")
        if not version:
            return None
        asset = version.get("asset")
        if not asset:
            return None
        return get_asset_display_path(session, str(asset["id"]))
    except Exception as e:
        _log.warning("get_asset_display_path_from_component(%s): %s", component_id[:8] if component_id else "", e)
        return None
