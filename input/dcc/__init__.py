"""
DCC adapters for Ftrack Input core.

- standalone: Qt widget context, uses FtrackApiClient / session
- houdini: HDA bridge, same core, Houdini node/parm access
- maya: Maya adapter, load_asset_version_data_for_maya, resolve_component_path_maya
"""

# Standalone adapter - available when running outside DCC
from .standalone import load_asset_version_data_for_standalone

# Houdini adapter - for Houdini finput HDA
from .houdini import load_asset_version_data_for_houdini

# Maya adapter
from .maya import (
    load_asset_version_data_for_maya,
    resolve_component_path_maya,
    get_session_for_maya,
)

__all__ = [
    "load_asset_version_data_for_standalone",
    "load_asset_version_data_for_houdini",
    "load_asset_version_data_for_maya",
    "resolve_component_path_maya",
    "get_session_for_maya",
]
