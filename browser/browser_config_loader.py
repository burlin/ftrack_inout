"""
Load browser_config.yaml from ftrack_inout root (plugin level, not per-DCC).
Used by browser widget and simple_api_client for sequence display and project filter.
Requires PyYAML (ftrack_inout/requirements.txt).
"""

from __future__ import annotations

import yaml
from pathlib import Path
from typing import Any, Dict, Iterable, Set

_CACHE: dict[str, Any] | None = None

# ftrack_inout root = parent of browser/
FTRACK_INOUT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = FTRACK_INOUT_ROOT / "browser_config.yaml"

DEFAULTS = {
    "show_sequence_frame_range": True,
    "project_filter": {
        "enabled": True,
        "statuses": ["Active"],
    },
    "component_filters": {},  # per-DCC component visibility masks
}


def get_browser_config() -> dict[str, Any]:
    """Load and cache browser_config.yaml; return merged with DEFAULTS."""
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    result = dict(DEFAULTS)
    if CONFIG_PATH.is_file():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                if "show_sequence_frame_range" in data:
                    result["show_sequence_frame_range"] = bool(data["show_sequence_frame_range"])
                if "project_filter" in data and isinstance(data["project_filter"], dict):
                    pf = data["project_filter"]
                    if "enabled" in pf:
                        result["project_filter"]["enabled"] = bool(pf["enabled"])
                    if "statuses" in pf and isinstance(pf["statuses"], list):
                        result["project_filter"]["statuses"] = [str(s) for s in pf["statuses"]]
                if "component_filters" in data and isinstance(data["component_filters"], dict):
                    # Store as-is; normalization is handled in helper functions.
                    result["component_filters"] = data["component_filters"]
        except Exception:
            pass
    _CACHE = result
    return result


def get_show_sequence_frame_range() -> bool:
    """True = show frame range (1001 - 1721) for sequences; False = only pattern and count."""
    return bool(get_browser_config().get("show_sequence_frame_range", True))


def get_project_filter_statuses() -> list[str] | None:
    """Return list of status names to allow, or None if filter disabled (show all)."""
    cfg = get_browser_config()
    pf = cfg.get("project_filter") or {}
    if not pf.get("enabled"):
        return None
    statuses = pf.get("statuses")
    if not statuses:
        return None
    return [str(s) for s in statuses]


def _normalize_file_type(ft: str) -> str:
    """Normalize file_type / extension for comparison (no dot, lowercase)."""
    return (ft or "").replace(".", "").strip().lower()


def _normalize_type_list(values: Iterable[Any]) -> Set[str]:
    """Normalize a list of file type values to a set of normalized strings."""
    normalized: Set[str] = set()
    for v in values or []:
        ft = _normalize_file_type(str(v))
        if ft:
            normalized.add(ft)
    return normalized


def get_component_filters_for_dcc(dcc: str) -> Dict[str, Set[str]]:
    """Return component visibility masks (hide/disable) for given DCC.

    The browser_config.yaml may define:

    component_filters:
      default:
        hide_file_types: [ma, mb]
        disabled_file_types: [abc]
      houdini:
        hide_file_types: [ma, mb]
        disabled_file_types: [abc]
      maya:
        hide_file_types: [hip]

    Resolution rules:
    - Start with empty sets.
    - Apply "default"/"all"/* group if present.
    - Overlay DCC-specific group (key is lowercased dcc string).
    """
    cfg = get_browser_config()
    filters_cfg = cfg.get("component_filters") or {}
    hide: Set[str] = set()
    disabled: Set[str] = set()

    if isinstance(filters_cfg, dict):
        # Global/default groups
        for key in ("default", "all", "*"):
            group = filters_cfg.get(key)
            if isinstance(group, dict):
                hide.update(_normalize_type_list(group.get("hide_file_types") or []))
                disabled.update(_normalize_type_list(group.get("disabled_file_types") or []))

        # DCC-specific overrides
        dcc_key = str(dcc or "").strip().lower()
        if dcc_key:
            group = filters_cfg.get(dcc_key)
            if isinstance(group, dict):
                hide.update(_normalize_type_list(group.get("hide_file_types") or []))
                disabled.update(_normalize_type_list(group.get("disabled_file_types") or []))

    return {
        "hide_file_types": hide,
        "disabled_file_types": disabled,
    }
