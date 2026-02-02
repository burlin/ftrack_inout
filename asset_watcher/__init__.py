"""
Asset Watcher helpers for DCC integration.

Use these functions to add/remove asset watches from Houdini, Maya, etc.
"""

from __future__ import annotations

import logging
import socket
from typing import Optional

_log = logging.getLogger(__name__)


class UpdateAction:
    """Actions to take when update is detected."""
    NOTIFY_ONLY = 'notify_only'           # Just show notification
    WAIT_LOCATION = 'wait_location'       # Wait for component on accessible location
    AUTO_TRANSFER = 'auto_transfer'       # Automatically trigger transfer
    AUTO_UPDATE_DCC = 'auto_update_dcc'   # Auto-transfer + update in DCC


def watch_asset(
    session,
    asset_id: str,
    asset_name: str,
    component_name: Optional[str] = None,
    component_id: Optional[str] = None,
    target_location_id: Optional[str] = None,
    current_version_id: Optional[str] = None,
    source_dcc: str = "unknown",
    scene_path: Optional[str] = None,
    update_action: str = UpdateAction.WAIT_LOCATION,
    notify_dcc: bool = True,
):
    """
    Add asset to watchlist.
    
    Args:
        session: ftrack_api.Session with event_hub connected
        asset_id: Asset UUID
        asset_name: Asset name for display
        component_name: Specific component to watch (None = all)
        component_id: Current component ID
        target_location_id: Location to transfer to
        current_version_id: Currently used version ID
        source_dcc: DCC name (houdini, maya, etc.)
        scene_path: Path to scene file using this asset
        update_action: What to do when update detected:
            - UpdateAction.NOTIFY_ONLY: Just notify
            - UpdateAction.WAIT_LOCATION: Wait for accessible location (default)
            - UpdateAction.AUTO_TRANSFER: Auto-transfer to target
            - UpdateAction.AUTO_UPDATE_DCC: Auto-transfer + update DCC
        notify_dcc: Notify DCC when update available
    
    Example:
        import ftrack_api
        from ftrack_inout.asset_watcher import watch_asset, UpdateAction
        
        session = ftrack_api.Session(auto_connect_event_hub=True)
        
        # Watch with default action (wait for accessible location)
        watch_asset(
            session,
            asset_id="a96dc802-...",
            asset_name="BigMan",
            component_name="anim.fbx",
            target_location_id="burlin.local",
            source_dcc="houdini",
        )
        
        # Watch with auto-transfer
        watch_asset(
            session,
            asset_id="...",
            asset_name="Props",
            component_name="geo.abc",
            target_location_id="burlin.local",
            source_dcc="houdini",
            update_action=UpdateAction.AUTO_TRANSFER,
        )
    """
    import ftrack_api
    
    try:
        session.event_hub.connect()
    except Exception:
        pass
    
    hostname = socket.gethostname().lower()
    
    event = ftrack_api.event.base.Event(
        topic='mroya.asset.watch',
        data={
            'asset_id': asset_id,
            'asset_name': asset_name,
            'component_name': component_name,
            'component_id': component_id,
            'target_location_id': target_location_id,
            'current_version_id': current_version_id,
            'source_dcc': source_dcc,
            'scene_path': scene_path,
            'update_action': update_action,
            'notify_dcc': notify_dcc,
        },
        source={'hostname': hostname}
    )
    
    session.event_hub.publish(event, on_error='ignore')
    _log.info(f"Watch request sent for {asset_name}/{component_name} (action={update_action})")


def unwatch_asset(
    session,
    asset_id: str,
    component_name: Optional[str] = None,
):
    """
    Remove asset from watchlist.
    
    Args:
        session: ftrack_api.Session
        asset_id: Asset UUID
        component_name: Specific component (None = all components of this asset)
    """
    import ftrack_api
    
    try:
        session.event_hub.connect()
    except Exception:
        pass
    
    hostname = socket.gethostname().lower()
    
    event = ftrack_api.event.base.Event(
        topic='mroya.asset.unwatch',
        data={
            'asset_id': asset_id,
            'component_name': component_name,
        },
        source={'hostname': hostname}
    )
    
    session.event_hub.publish(event, on_error='ignore')
    _log.info(f"Unwatch request sent for {asset_id}/{component_name}")


def watch_component(
    session,
    component_id: str,
    target_location_id: Optional[str] = None,
    source_dcc: str = "unknown",
    scene_path: Optional[str] = None,
    auto_transfer: bool = True,
    notify_dcc: bool = True,
):
    """
    Add component to watchlist (auto-resolves asset info).
    
    Convenience function that queries ftrack for asset details.
    
    Args:
        session: ftrack_api.Session
        component_id: Component UUID
        target_location_id: Location to transfer to
        source_dcc: DCC name
        scene_path: Scene file path
        auto_transfer: Auto-transfer new versions
        notify_dcc: Notify on updates
    """
    # Query component details
    component = session.query(
        f'select id, name, version.id, version.version, version.asset_id, '
        f'version.asset.name, version.asset.parent.name '
        f'from Component where id is "{component_id}"'
    ).first()
    
    if not component:
        _log.warning(f"Component not found: {component_id}")
        return
    
    version = component['version']
    asset = version['asset']
    
    watch_asset(
        session=session,
        asset_id=asset['id'],
        asset_name=asset['name'],
        component_name=component['name'],
        component_id=component_id,
        target_location_id=target_location_id,
        current_version_id=version['id'],
        source_dcc=source_dcc,
        scene_path=scene_path,
        auto_transfer=auto_transfer,
        notify_dcc=notify_dcc,
    )
