"""
Ftrack Input (finput) - DCC-agnostic core and DCC adapters.

Structure:
- core/   - Pure logic: session + data, no UI. Reusable by Houdini, Maya, standalone.
- dcc/    - DCC adapters: standalone Qt, Houdini HDA bridge (later), Maya (later).

Usage:
  from ftrack_inout.input.core import load_asset_version_component_data
  data = load_asset_version_component_data(session, asset_id)
"""

from ftrack_inout.input.core.asset_version_component import (
    load_asset_version_component_data,
)

from ftrack_inout.input.core.version_indicators import (
    compute_version_labels_with_indicators,
)

from ftrack_inout.input.core.component_menu import (
    get_component_menu_data,
    resolve_component_to_select,
)

from ftrack_inout.input.core.path_resolution import (
    resolve_component_path,
    get_primary_disk_location,
)

__all__ = [
    "load_asset_version_component_data",
    "compute_version_labels_with_indicators",
    "get_component_menu_data",
    "resolve_component_to_select",
    "resolve_component_path",
    "get_primary_disk_location",
]
