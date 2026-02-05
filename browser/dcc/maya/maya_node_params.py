"""Functions for setting ftrack params on Maya nodes.

This module handles creating ftrack reference nodes in Maya
when triggered from the browser's "Set Full Params" button.
"""
from __future__ import annotations

import logging
import re
from typing import Mapping, Sequence

try:
    import maya.cmds as cmds
    MAYA_AVAILABLE: bool = True
except Exception:
    cmds = None  # type: ignore
    MAYA_AVAILABLE = False

# Import ftrack helpers (separated for easier removal)
try:
    from .ftrack_utils import get_component_path_by_id
except ImportError:
    get_component_path_by_id = None  # type: ignore

_log = logging.getLogger(__name__)


def _sanitize_node_name(name: str) -> str:
    """Sanitize a string to be a valid Maya node name.

    Maya node names can only contain alphanumeric characters and underscores.
    """
    if not name:
        return "unknown"
    # Replace any non-alphanumeric characters with underscores
    sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', name)
    # Ensure it doesn't start with a number
    if sanitized[0].isdigit():
        sanitized = '_' + sanitized
    return sanitized


def create_ftrack_reference_node(
    asset_version_id: str | None,
    component_name: str | None,
    component_id: str | None,
    asset_id: str | None,
    asset_name: str | None,
    asset_type: str | None,
    component_path: str | None,
) -> str | None:
    """Create a ftrack reference node with custom attributes.

    Creates a 'network' node (invisible in viewport) named
    'ftrack_reference_[component_name]' with ftrack metadata attributes.

    Args:
        asset_version_id: The ftrack AssetVersion ID.
        component_name: The component name (e.g., "main", "preview").
        component_id: The ftrack Component ID.
        asset_id: The ftrack Asset ID.
        asset_name: The asset name.
        asset_type: The asset type (e.g., "Geometry", "Rig").
        component_path: The file path of the component.

    Returns:
        The created node name, or None if creation failed.
    """
    if not MAYA_AVAILABLE:
        _log.warning("Maya not available, cannot create node")
        return None

    # Build node name
    safe_component_name = _sanitize_node_name(component_name or "unknown")
    node_name = f"ftrack_reference_{safe_component_name}"

    try:
        # Create a 'network' node - this is a dependency node with no viewport representation
        node = cmds.createNode('network', name=node_name)
        _log.info("Created ftrack reference node: %s", node)

        # Add custom string attributes
        attrs = {
            'ftrack_asset_version_id': asset_version_id or '',
            'ftrack_component_name': component_name or '',
            'ftrack_component_id': component_id or '',
            'ftrack_asset_id': asset_id or '',
            'ftrack_asset_name': asset_name or '',
            'ftrack_asset_type': asset_type or '',
            'ftrack_component_path': component_path or '',
        }

        for attr_name, attr_value in attrs.items():
            cmds.addAttr(node, longName=attr_name, dataType='string')
            cmds.setAttr(f'{node}.{attr_name}', attr_value, type='string')
            _log.debug("Set %s.%s = %s", node, attr_name, attr_value)

        return node

    except Exception as exc:
        _log.error("Failed to create ftrack reference node: %s", exc)
        return None


def set_hda_params_on_selected_nodes(
    asset_version_id: str | None,
    component_name: str | None,
    component_id: str | None,
    asset_id: str | None,
    asset_name: str | None,
    asset_type: str | None,
    hda_param_config: Mapping[str, Sequence[str]],
) -> tuple[int, int]:
    """Create a ftrack reference node with the given parameters.

    This function creates a new 'network' node (not visible/selectable in viewport)
    named 'ftrack_reference_[component_name]' with custom ftrack attributes.

    The component_path is automatically fetched from ftrack using the component_id.

    Args:
        asset_version_id: The ftrack AssetVersion ID.
        component_name: The component name (e.g., "main", "preview").
        component_id: The ftrack Component ID.
        asset_id: The ftrack Asset ID.
        asset_name: The asset name.
        asset_type: The asset type (e.g., "Geometry", "Rig").
        hda_param_config: Mapping of node types to parameter names (unused in Maya).

    Returns:
        Tuple of (success_count, failure_count).
        success_count is 1 if node was created, 0 otherwise.
    """
    if not MAYA_AVAILABLE:
        _log.warning("Maya not available, cannot create ftrack reference node")
        return 0, 1

    # Fetch component path from ftrack using component_id
    component_path = None
    if component_id and get_component_path_by_id is not None:
        component_path = get_component_path_by_id(component_id)
        if component_path:
            _log.info("Fetched component path: %s", component_path)
        else:
            _log.warning("Could not fetch path for component_id: %s", component_id)

    node = create_ftrack_reference_node(
        asset_version_id=asset_version_id,
        component_name=component_name,
        component_id=component_id,
        asset_id=asset_id,
        asset_name=asset_name,
        asset_type=asset_type,
        component_path=component_path,
    )

    if node:
        return 1, 0
    else:
        return 0, 1
