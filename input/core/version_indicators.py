"""
Compute version menu labels with (*) indicator for versions containing matching component.

Pure logic - extracted from Houdini _update_version_menu_indicators.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def _normalize_file_type(ft: str) -> str:
    return (ft or "").replace(".", "").strip().lower()


def compute_version_labels_with_indicators(
    cached_data: Dict[str, Any],
    selected_comp_id: str,
    current_version_id: str,
    selected_comp_name: Optional[str] = None,
    selected_comp_file_type: Optional[str] = None,
) -> List[str]:
    """
    Build version labels with (*) for versions that have component with same name+file_type.

    Same logic as Houdini _update_version_menu_indicators.

    Args:
        cached_data: From load_asset_version_component_data
        selected_comp_id: Currently selected component ID
        current_version_id: Version where selected component is from
        selected_comp_name: Override - component name (from components_names if not passed)
        selected_comp_file_type: Override - file type (from components_file_types if not passed)

    Returns:
        List of labels, e.g. ["v044 (*)", "v043 (*)", "v042", ...]
    """
    version_info = cached_data.get("version_info", [])
    components_map = cached_data.get("components_map", {})
    components_file_types = cached_data.get("components_file_types", {})
    components_names = cached_data.get("components_names", {})

    if not version_info:
        return []

    curr_ver_ft = components_file_types.get(current_version_id, {})
    curr_ver_names = components_names.get(current_version_id, {})
    if not curr_ver_ft and current_version_id:
        for vid in components_file_types:
            if str(vid).lower() == str(current_version_id).lower():
                curr_ver_ft = components_file_types[vid]
                curr_ver_names = components_names.get(vid, {})
                break
    # Prefer cache when selected_comp_id is in current version (ensures consistent matching)
    comp_ft = None
    comp_name = None
    if selected_comp_id and current_version_id:
        curr_comps = components_map.get(current_version_id, [])
        if selected_comp_id in curr_comps:
            comp_ft = curr_ver_ft.get(selected_comp_id, "")
            comp_name = curr_ver_names.get(selected_comp_id, "") or None
    if comp_ft is None:
        comp_ft = selected_comp_file_type
    if comp_name is None:
        comp_name = selected_comp_name
    if comp_ft is None:
        comp_ft = curr_ver_ft.get(selected_comp_id, "")
    if comp_name is None:
        comp_name = curr_ver_names.get(selected_comp_id, selected_comp_id)

    comp_ft_norm = _normalize_file_type(comp_ft or "")
    comp_name_lower = (comp_name or "").strip().lower()

    result: List[str] = []
    for ver in version_info:
        version_id = ver["id"]
        label = ver["name"]
        comps_in_ver = components_map.get(version_id, [])
        ver_ft = components_file_types.get(version_id, {})
        ver_names = components_names.get(version_id, {})

        if selected_comp_id in comps_in_ver:
            if _normalize_file_type(ver_ft.get(selected_comp_id, "")) == comp_ft_norm:
                label += " (*)"
        else:
            for cid in comps_in_ver:
                if (
                    (ver_names.get(cid, "") or "").strip().lower() == comp_name_lower
                    and _normalize_file_type(ver_ft.get(cid, "")) == comp_ft_norm
                ):
                    label += " (*)"
                    break
        result.append(label)
    return result
