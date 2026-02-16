"""
Component menu data and selection resolution for a version.

Pure logic - extracted from Houdini applyVersionSelection.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def get_component_menu_data(
    cached_data: Dict[str, Any],
    version_id: str,
) -> Tuple[List[str], List[str]]:
    """
    Get component menu items (ids) and labels for a version.

    Same logic as Houdini applyVersionSelection menu building.

    Args:
        cached_data: From load_asset_version_component_data
        version_id: AssetVersion ID

    Returns:
        (items, labels) - items are component IDs, labels are e.g. ["maya_part (.sc)", ...]
    """
    components_map = cached_data.get("components_map", {}).get(version_id, [])
    components_file_types = cached_data.get("components_file_types", {}).get(version_id, {})
    components_names = cached_data.get("components_names", {}).get(version_id, {})

    items: List[str] = []
    labels: List[str] = []
    for comp_id in components_map:
        comp_name = components_names.get(comp_id, "")
        file_type = components_file_types.get(comp_id, "")
        if file_type:
            label = f"{comp_name} (.{file_type})"
        else:
            label = comp_name or comp_id
        items.append(comp_id)
        labels.append(label)
    return (items, labels)


def _normalize_file_type(ft: str) -> str:
    return (ft or "").replace(".", "").strip().lower()


def resolve_component_to_select(
    cached_data: Dict[str, Any],
    version_id: str,
    component_to_select_name: Optional[str] = None,
    previous_comp_id: Optional[str] = None,
    component_to_select_file_type: Optional[str] = None,
) -> Optional[str]:
    """
    Resolve which component_id to select in the menu.

    Priority: 1) by name+file_type (if file_type given), 2) by name only,
    3) previous comp_id, 4) first in list.

    When multiple components have the same name (e.g. File vs Sequence),
    prefer the one matching file_type to avoid switching File <-> Sequence.
    """
    components_map = cached_data.get("components_map", {}).get(version_id, [])
    components_names = cached_data.get("components_names", {}).get(version_id, {})
    components_file_types = cached_data.get("components_file_types", {}).get(version_id, {})

    if not components_map:
        return None

    if component_to_select_name:
        name_lower = component_to_select_name.strip().lower()
        ft_norm = _normalize_file_type(component_to_select_file_type or "")
        if ft_norm:
            for cid in components_map:
                if (components_names.get(cid, "") or "").strip().lower() == name_lower:
                    if _normalize_file_type(components_file_types.get(cid, "")) == ft_norm:
                        return cid
        for cid in components_map:
            if (components_names.get(cid, "") or "").strip().lower() == name_lower:
                return cid

    if previous_comp_id and previous_comp_id in components_map:
        return previous_comp_id

    return components_map[0]
