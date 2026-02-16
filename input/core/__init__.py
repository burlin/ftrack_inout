"""
Ftrack Input Core - pure logic, no DCC dependencies.

Functions work with ftrack_api.Session and return data structures.
UI/DCC layer is responsible for rendering.
"""

from .asset_version_component import load_asset_version_component_data
from .version_indicators import compute_version_labels_with_indicators
from .component_menu import get_component_menu_data, resolve_component_to_select
from .path_resolution import resolve_component_path, get_primary_disk_location

__all__ = [
    "load_asset_version_component_data",
    "compute_version_labels_with_indicators",
    "get_component_menu_data",
    "resolve_component_to_select",
    "resolve_component_path",
    "get_primary_disk_location",
]
