"""
Path resolution for components - DCC-agnostic core.

Primary Disk location = the one with highest precedence (lowest priority value).
Secondary Disk (e.g. burlin.backup) and S3 require transfer to primary before use.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Built-in ftrack locations we exclude from "primary Disk" selection
BUILTIN_LOCATION_NAMES = frozenset((
    "ftrack.origin",
    "ftrack.unmanaged",
    "ftrack.review",
    "ftrack.server",
    "ftrack.connect",
))


def get_primary_disk_location(session: Any) -> Optional[Any]:
    """
    Return the primary Disk location for the DCC (e.g. burlin.local).

    Primary = Disk location with highest precedence (lowest priority value).
    Excludes built-in ftrack locations.

    Returns:
        Location entity or None if no user Disk locations configured.
    """
    if not session:
        return None
    try:
        import ftrack_api
        locations = session.query("Location").all()
    except Exception as e:
        logger.warning("get_primary_disk_location: query failed: %s", e)
        return None

    disk_locations = []
    for loc in locations:
        name = loc.get("name") or ""
        if name in BUILTIN_LOCATION_NAMES:
            continue
        acc = getattr(loc, "accessor", None)
        if not acc:
            continue
        if hasattr(ftrack_api.accessor, "disk") and isinstance(
            acc, ftrack_api.accessor.disk.DiskAccessor
        ):
            disk_locations.append(loc)

    if not disk_locations:
        return None

    # Lower priority value = higher precedence (ftrack convention)
    disk_locations.sort(key=lambda l: l.get("priority", 999))
    return disk_locations[0]


def resolve_component_path(
    session: Any,
    component: Any,
    location: Optional[Any] = None,
) -> str:
    """
    Resolve filesystem path for a component.

    If location is explicitly passed:
        Return whatever path that location returns (caller knows what they want).

    If location is None (auto-detect):
        - Require configured locations; error if not
        - Use primary Disk location (e.g. burlin.local)
        - Component must have 100% availability in primary
        - If only in secondary Disk (burlin.backup) or S3: error "Transfer to primary first"

    Args:
        session: ftrack_api.Session
        component: Component entity (or dict with id for lookup)
        location: Explicit location, or None for auto primary

    Returns:
        Filesystem path string

    Raises:
        ValueError: With descriptive message when path cannot be resolved
    """
    if not session:
        raise ValueError("Session is required")

    comp_entity = component
    if hasattr(component, "get") and component.get("id"):
        pass
    elif isinstance(component, dict) and component.get("id"):
        try:
            comp_entity = session.get("Component", str(component["id"]))
        except Exception as e:
            raise ValueError("Failed to get Component: %s" % e) from e
    else:
        raise ValueError("Component must be entity or dict with id")

    # Explicit location: trust caller, return path
    if location is not None:
        try:
            path = location.get_filesystem_path(comp_entity)
            if path is not None and str(path).strip():
                return str(path).strip()
            raise ValueError("Location %s returned empty path" % (location.get("name", "?")))
        except ValueError:
            raise
        except Exception as e:
            raise ValueError("get_filesystem_path failed: %s" % e) from e

    # Auto: require primary Disk location
    primary = get_primary_disk_location(session)
    if not primary:
        raise ValueError(
            "Locations not configured or no primary Disk location. "
            "Configure disk_locations.yaml (e.g. burlin.local)."
        )

    primary_name = primary.get("name", "?")

    try:
        availability = primary.get_component_availability(comp_entity)
    except Exception as e:
        raise ValueError("Failed to get availability: %s" % e) from e

    if availability >= 100.0:
        try:
            path = primary.get_filesystem_path(comp_entity)
            if path and str(path).strip():
                return str(path).strip()
        except Exception as e:
            raise ValueError("get_filesystem_path failed for %s: %s" % (primary_name, e)) from e

    # Not in primary - check if available elsewhere (suggest transfer)
    try:
        locations = session.query("Location").all()
        for loc in locations:
            if loc.get("name") == primary_name:
                continue
            try:
                av = loc.get_component_availability(comp_entity)
                if av and float(av) >= 100.0:
                    other_name = loc.get("name", "?")
                    raise ValueError(
                        "Component not in primary location (%s). "
                        "Available in %s - transfer to primary first."
                        % (primary_name, other_name)
                    )
            except ValueError:
                raise
            except Exception:
                continue
    except ValueError:
        raise

    raise ValueError(
        "Component not available in primary location (%s). "
        "Ensure transfer completed or select different version."
        % primary_name
    )
