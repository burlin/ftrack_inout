"""
DCC-agnostic selector logic for task and asset parameter management.

This module provides functions for managing task and asset selection logic
that work with any parameter interface (Houdini HDA, Maya node, Qt widget, etc.).

All functions accept a parameter interface object that provides:
- get_parameter(name: str) -> Any
- set_parameter(name: str, value: Any) -> None
- show_message(message: str, severity: str = "info") -> None (optional)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Protocol
else:
    Protocol = object

try:
    import ftrack_api
    FTRACK_AVAILABLE = True
except ImportError:
    FTRACK_AVAILABLE = False
    ftrack_api = None  # type: ignore

_log = logging.getLogger(__name__)


if TYPE_CHECKING:
    class ParameterInterface(Protocol):
        """Protocol for parameter getter/setter interface."""
        
        def get_parameter(self, name: str) -> Any:
            """Get parameter value by name."""
            ...
        
        def set_parameter(self, name: str, value: Any) -> None:
            """Set parameter value by name."""
            ...
        
        def show_message(self, message: str, severity: str = "info") -> None:
            """Show message to user (optional)."""
            ...
else:
    ParameterInterface = object


def check_task_id(
    params: Any,  # ParameterInterface
    session: Any,  # Optional[ftrack_api.Session]
    task_info_label: Optional[Any] = None
) -> bool:
    """
    Check and validate task_id (mimics fselector.checkTaskId).
    
    Args:
        params: Parameter interface
        session: Ftrack session
        task_info_label: Optional label widget to update (for Qt)
    
    Returns:
        True if task_id is valid, False otherwise
    """
    _log.info("[check_task_id] Starting task_id validation")
    
    if not session:
        _log.warning("[check_task_id] Ftrack session is not available")
        return False
    
    task_id = params.get_parameter('task_Id')
    _log.info(f"[check_task_id] Got task_id from params: {task_id}")
    
    if not task_id:
        _log.warning("[check_task_id] task_id is empty")
        if task_info_label is not None:
            task_info_label.setText("project: - parent: - taskname: -")
        return False
    
    try:
        _log.info(f"[check_task_id] Fetching Task entity: {task_id}")
        task = session.get('Task', task_id)
        task_name = task['name']
        _log.info(f"[check_task_id] Task name: {task_name}")
        
        parent = task['parent']
        parent_name = parent['name']
        parent_id = parent['id']
        _log.info(f"[check_task_id] Parent: {parent_name} (id: {parent_id})")
        
        project = parent['project']
        project_name = project['name']
        project_id = project['id']
        _log.info(f"[check_task_id] Project: {project_name} (id: {project_id})")
        
        info_text = f"project: {project_name}    parent: {parent_name}    taskname: {task_name}"
        if task_info_label is not None:
            task_info_label.setText(info_text)
            _log.info(f"[check_task_id] Updated task_info_label: {info_text}")
        _log.info("[check_task_id] Task validation successful")
        return True
    except Exception as e:
        _log.error(f"[check_task_id] Failed to validate task_id: {e}", exc_info=True)
        if task_info_label is not None:
            task_info_label.setText("")
        return False


def apply_task_id(
    params: Any,  # ParameterInterface
    session: Any,  # Optional[ftrack_api.Session]
    show_dialog: Optional[Any] = None
) -> bool:
    """
    Apply task_id to asset parameters (mimics fselector.applyTaskId).
    
    Args:
        params: Parameter interface
        session: Ftrack session
        show_dialog: Optional function to show dialogs (for Qt: QMessageBox)
    
    Returns:
        True if successful, False otherwise
    """
    _log.info("[apply_task_id] Starting apply_task_id")
    
    if not session:
        _log.warning("[apply_task_id] Ftrack session is not available")
        return False
    
    task_id = params.get_parameter('task_Id')
    _log.info(f"[apply_task_id] Got task_id from params: {task_id}")
    
    if not task_id:
        _log.warning("[apply_task_id] task_id is empty, setting test='undefined'")
        params.set_parameter('test', 'undefined')
        return False
    
    try:
        # Get new task and its parent
        _log.info(f"[apply_task_id] Fetching Task entity: {task_id}")
        new_task = session.get('Task', task_id)
        new_task_name = new_task['name']
        _log.info(f"[apply_task_id] New task name: {new_task_name}")
        
        new_parent = new_task['parent']
        new_parent_id = new_parent['id']
        new_parent_name = new_parent['name']
        _log.info(f"[apply_task_id] New parent: {new_parent_name} (id: {new_parent_id})")
        
        new_project = new_parent['project']
        new_project_id = new_project['id']
        new_project_name = new_project['name']
        _log.info(f"[apply_task_id] New project: {new_project_name} (id: {new_project_id})")
        
        # Helper function to set parameters
        def _set(parm_name: str, value: Any):
            try:
                _log.debug(f"[apply_task_id] Setting parameter '{parm_name}' = '{value}'")
                params.set_parameter(parm_name, value)
            except Exception as e:
                _log.warning(f"[apply_task_id] Failed to set '{parm_name}': {e}")
        
        # Check if asset is initialized (has p_asset_id)
        current_asset_id = params.get_parameter('p_asset_id')
        current_asset_id = str(current_asset_id).strip() if current_asset_id else None
        _log.info(f"[apply_task_id] Current asset_id: {current_asset_id}")
        
        # If asset is initialized, check if parent or project changed
        if current_asset_id:
            _log.info(f"[apply_task_id] Asset is initialized, checking parent/project changes")
            try:
                current_asset = session.get('Asset', current_asset_id)
                current_parent = current_asset['parent']
                current_parent_id = current_parent['id']
                current_parent_name = current_parent['name']
                _log.info(f"[apply_task_id] Current parent: {current_parent_name} (id: {current_parent_id})")
                
                current_project = current_parent['project']
                current_project_id = current_project['id']
                current_project_name = current_project['name']
                _log.info(f"[apply_task_id] Current project: {current_project_name} (id: {current_project_id})")
                
                # Check if parent or project changed
                parent_changed = (current_parent_id != new_parent_id) or (current_project_id != new_project_id)
                _log.info(f"[apply_task_id] Parent changed: {parent_changed} (parent: {current_parent_id != new_parent_id}, project: {current_project_id != new_project_id})")
                
                # If parent and project match, just apply task info
                if not parent_changed:
                    _log.info("[apply_task_id] Parent/project unchanged, applying task info only")
                    _set('p_task_id', task_id)
                    _set('task_project', new_project_name)
                    _set('task_parent', new_parent_name)
                    _set('task_name', new_task_name)
                    _log.info("[apply_task_id] Task info applied successfully")
                    return True
                
                # Parent or project changed - save p_asset_name and p_asset_type to asset_name and type,
                # then clear all p_* parameters
                current_asset_name = current_asset['name']
                current_asset_type = current_asset['type']['name']
                
                # Save p_asset_name and p_asset_type to asset_name and type before clearing
                _set('asset_name', current_asset_name)
                _set('type', current_asset_type)
                
                # Clear all p_* asset parameters
                _set('p_project', "")
                _set('p_parent', "")
                _set('p_asset_id', "")
                _set('p_asset_name', "")
                _set('p_asset_type', "")
                _set('asset_id', "")
                
                # Check if asset with same name exists in new parent
                existing_asset = session.query(
                    f'Asset where name is "{current_asset_name}" and parent.id is "{new_parent_id}"'
                ).first()
                
                # Determine dialog message and options
                if existing_asset:
                    existing_asset_type = existing_asset['type']['name']
                    if existing_asset_type == current_asset_type:
                        # Asset exists with same type
                        message = f"The asset '{current_asset_name}' already exists within this parent."
                        buttons = ("Use existing", "Create new", "Cancel")
                        if show_dialog:
                            result = show_dialog(message, buttons, "Asset Exists")
                            if result == 0:  # Use existing
                                _log.info("[apply_task_id] User chose 'Use existing'")
                                existing_asset_id = existing_asset['id']
                                existing_asset_entity = session.get('Asset', existing_asset_id)
                                existing_parent = existing_asset_entity['parent']
                                existing_project = existing_parent['project']
                                
                                _set('p_project', existing_project['name'])
                                _set('p_parent', existing_parent['name'])
                                _set('p_asset_type', existing_asset_type)
                                _set('p_asset_name', current_asset_name)
                                _set('p_asset_id', existing_asset_id)
                                _set('p_task_id', task_id)
                                _set('task_project', new_project_name)
                                _set('task_parent', new_parent_name)
                                _set('task_name', new_task_name)
                                _set('asset_id', existing_asset_id)
                                _set('asset_name', current_asset_name)
                                _set('type', existing_asset_type)
                                _log.info("[apply_task_id] Applied 'Use existing' parameters")
                                return True
                            elif result == 1:  # Create new
                                _log.info("[apply_task_id] User chose 'Create new'")
                                _set('p_asset_id', "")
                                _set('asset_id', "")
                                _set('p_project', new_project_name)
                                _set('p_parent', new_parent_name)
                                _set('p_asset_type', current_asset_type)
                                _set('p_asset_name', "")
                                _set('p_task_id', task_id)
                                _set('task_project', new_project_name)
                                _set('task_parent', new_parent_name)
                                _set('task_name', new_task_name)
                                _set('asset_name', "")
                                _set('type', current_asset_type)
                                _log.info("[apply_task_id] Applied 'Create new' parameters")
                                return True
                            else:  # Cancel
                                _log.info("[apply_task_id] User chose 'Cancel'")
                                return False
                        else:
                            _log.warning("[apply_task_id] show_dialog not available, cannot show dialog")
                    else:
                        # Asset exists but type is different
                        message = f"The asset '{current_asset_name}' already exists within this parent, but type is different (current: {current_asset_type}, existing: {existing_asset_type})."
                        buttons = ("Create new", "Cancel")
                        if show_dialog:
                            result = show_dialog(message, buttons, "Asset Type Mismatch")
                            if result == 0:  # Create new
                                _log.info("[apply_task_id] User chose 'Create new' (type mismatch)")
                                _set('p_asset_id', "")
                                _set('asset_id', "")
                                _set('p_project', new_project_name)
                                _set('p_parent', new_parent_name)
                                _set('p_asset_type', current_asset_type)
                                _set('p_asset_name', "")
                                _set('p_task_id', task_id)
                                _set('task_project', new_project_name)
                                _set('task_parent', new_parent_name)
                                _set('task_name', new_task_name)
                                _set('asset_name', "")
                                _set('type', current_asset_type)
                                _log.info("[apply_task_id] Applied 'Create new' parameters (type mismatch)")
                                return True
                            else:  # Cancel
                                _log.info("[apply_task_id] User chose 'Cancel' (type mismatch)")
                                return False
                        else:
                            _log.warning("[apply_task_id] show_dialog not available, cannot show dialog")
                else:
                    # Asset does not exist in new parent
                    message = f"The asset '{current_asset_name}' is not exists within this parent."
                    buttons = ("Copy current", "Create new", "Cancel")
                    if show_dialog:
                        result = show_dialog(message, buttons, "Asset Not Found")
                        if result == 0:  # Copy current
                            _log.info("[apply_task_id] User chose 'Copy current'")
                            _set('p_asset_id', "")
                            _set('asset_id', "")
                            _set('p_project', new_project_name)
                            _set('p_parent', new_parent_name)
                            _set('p_asset_type', current_asset_type)
                            _set('p_asset_name', current_asset_name)
                            _set('p_task_id', task_id)
                            _set('task_project', new_project_name)
                            _set('task_parent', new_parent_name)
                            _set('task_name', new_task_name)
                            _set('asset_name', current_asset_name)
                            _set('type', current_asset_type)
                            _log.info("[apply_task_id] Applied 'Copy current' parameters")
                            return True
                        elif result == 1:  # Create new
                            _log.info("[apply_task_id] User chose 'Create new' (not found)")
                            _set('p_asset_id', "")
                            _set('asset_id', "")
                            _set('p_project', new_project_name)
                            _set('p_parent', new_parent_name)
                            if current_asset_type:
                                _set('p_asset_type', current_asset_type)
                                _set('type', current_asset_type)
                            _set('p_asset_name', "")
                            _set('p_task_id', task_id)
                            _set('task_project', new_project_name)
                            _set('task_parent', new_parent_name)
                            _set('task_name', new_task_name)
                            _set('asset_name', "")
                            _log.info("[apply_task_id] Applied 'Create new' parameters (not found)")
                            return True
                        else:  # Cancel
                            _log.info("[apply_task_id] User chose 'Cancel' (not found)")
                            return False
                    else:
                        _log.warning("[apply_task_id] show_dialog not available, cannot show dialog")
                
                # If dialog was not shown or returned None, continue to apply task info
            except Exception as e:
                _log.warning(f"Failed to check asset parent in applyTaskId: {e}")
        else:
            # If asset is not initialized, check if p_parent or p_project changed
            _log.info("[apply_task_id] Asset is not initialized, checking p_parent/p_project changes")
            try:
                current_p_parent = params.get_parameter('p_parent')
                current_p_project = params.get_parameter('p_project')
                p_asset_name = params.get_parameter('p_asset_name')
                p_asset_type = params.get_parameter('p_asset_type')
                _log.info(f"[apply_task_id] Current p_parent: '{current_p_parent}', p_project: '{current_p_project}'")
                _log.info(f"[apply_task_id] Current p_asset_name: '{p_asset_name}', p_asset_type: '{p_asset_type}'")
                
                if (str(current_p_parent) != str(new_parent_name)) or (str(current_p_project) != str(new_project_name)):
                    _log.info("[apply_task_id] p_parent or p_project changed, saving and clearing p_* parameters")
                    # Save p_asset_name and p_asset_type to asset_name and type before clearing
                    if p_asset_name:
                        _set('asset_name', p_asset_name)
                    if p_asset_type:
                        _set('type', p_asset_type)
                    
                    # Clear all p_* asset parameters
                    _set('p_project', "")
                    _set('p_parent', "")
                    _set('p_asset_id', "")
                    _set('p_asset_name', "")
                    _set('p_asset_type', "")
                    _set('asset_id', "")
                    _log.info("[apply_task_id] Cleared all p_* parameters")
            except Exception as e:
                _log.warning(f"[apply_task_id] Exception while checking p_parent/p_project: {e}", exc_info=True)
        
        # Simple case: just apply task info
        _log.info("[apply_task_id] Applying task info parameters")
        _set('p_task_id', task_id)
        _set('task_project', new_project_name)
        _set('task_parent', new_parent_name)
        _set('task_name', new_task_name)
        _log.info("[apply_task_id] Task info applied successfully")
        return True
        
    except Exception as e:
        _log.error(f"[apply_task_id] Failed to apply task_id: {e}", exc_info=True)
        return False


def apply_asset_params(
    params: Any,  # ParameterInterface
    session: Any,  # Optional[ftrack_api.Session]
    task_info_label: Optional[Any] = None
) -> bool:
    """
    Apply asset parameters (mimics fselector.applyAssetParams).
    
    Args:
        params: Parameter interface
        session: Ftrack session
        task_info_label: Optional label widget to update (for Qt)
    
    Returns:
        True if successful, False otherwise
    """
    _log.info("[apply_asset_params] Starting apply_asset_params")
    
    if not session:
        _log.warning("[apply_asset_params] Ftrack session is not available")
        return False
    
    try:
        asset_id = params.get_parameter('asset_id')
        asset_name = params.get_parameter('asset_name')
        cur_type = params.get_parameter('type')
        task_id = params.get_parameter('task_Id')
        _log.info(f"[apply_asset_params] Read parameters: asset_id='{asset_id}', asset_name='{asset_name}', type='{cur_type}', task_id='{task_id}'")
    except Exception as e:
        _log.error(f"[apply_asset_params] Failed to read parameters: {e}", exc_info=True)
        return False
    
    def _set(parm_name: str, value: Any):
        try:
            _log.debug(f"[apply_asset_params] Setting parameter '{parm_name}' = '{value}'")
            params.set_parameter(parm_name, value)
        except Exception as e:
            _log.warning(f"[apply_asset_params] Failed to set '{parm_name}': {e}")
    
    if asset_id:
        _log.info(f"[apply_asset_params] Asset ID provided, querying Asset: {asset_id}")
        try:
            asset = session.query(f"Asset where id is '{asset_id}'").one()
            _log.info(f"[apply_asset_params] Found asset: {asset['name']}")
            
            parent = asset['parent']
            parent_name = parent['name']
            parent_id = parent['id']
            _log.info(f"[apply_asset_params] Asset parent: {parent_name} (id: {parent_id})")
            
            project = parent['project']
            project_name = project['name']
            project_id = project['id']
            _log.info(f"[apply_asset_params] Asset project: {project_name} (id: {project_id})")
            
            asset_type_name = cur_type if cur_type else asset['type']['name']
            asset_name_final = asset_name if asset_name else asset['name']
            _log.info(f"[apply_asset_params] Using asset_type='{asset_type_name}', asset_name='{asset_name_final}'")
            
            _set('p_project', project_name)
            _set('p_parent', parent_name)
            _set('p_asset_type', asset_type_name)
            _set('p_asset_name', asset_name_final)
            _set('p_asset_id', asset_id)
            _log.info("[apply_asset_params] Asset parameters applied successfully (from asset_id)")
            return True
        except Exception as e:
            _log.error(f"[apply_asset_params] Failed to resolve Asset '{asset_id}': {e}", exc_info=True)
            return False
    
    if not task_id:
        _log.warning("[apply_asset_params] No task_id provided")
        if task_info_label is not None:
            task_info_label.setText('undefined')
        return False
    
    _log.info(f"[apply_asset_params] No asset_id, using task_id to get parent/project: {task_id}")
    try:
        task = session.get('Task', task_id)
        parent = task['parent']
        parent_name = parent['name']
        parent_id = parent['id']
        _log.info(f"[apply_asset_params] Task parent: {parent_name} (id: {parent_id})")
        
        project = parent['project']
        project_name = project['name']
        project_id = project['id']
        _log.info(f"[apply_asset_params] Task project: {project_name} (id: {project_id})")
        
        _set('p_project', project_name)
        _set('p_parent', parent_name)
        _set('p_asset_type', cur_type)
        _set('p_asset_name', asset_name)
        _set('p_asset_id', "")
        _log.info("[apply_asset_params] Asset parameters applied successfully (from task_id)")
        return True
    except Exception as e:
        _log.error(f"[apply_asset_params] Failed to apply asset parameters: {e}", exc_info=True)
        return False


def get_assets_list(
    session: Any,  # Optional[ftrack_api.Session]
    task_id: str
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Get list of assets for a given task (mimics fselector.uniVerList).
    
    Args:
        session: Ftrack session
        task_id: Task ID
    
    Returns:
        Tuple of (unique_version dict {name: id}, unique_types dict {name: type})
    """
    _log.info(f"[get_assets_list] Starting get_assets_list for task_id: {task_id}")
    
    if not session:
        _log.warning("[get_assets_list] Ftrack session is not available")
        return {}, {}
    
    try:
        _log.info(f"[get_assets_list] Fetching Task entity: {task_id}")
        task = session.get('Task', task_id)
        parent_id = task['parent_id']
        _log.info(f"[get_assets_list] Task parent_id: {parent_id}")
        
        _log.info(f"[get_assets_list] Querying assets for parent.id='{parent_id}'")
        assets = session.query(f'Asset where parent.id is "{parent_id}"').all()
        _log.info(f"[get_assets_list] Found {len(assets)} assets")
        
        unique_version = {}
        unique_types = {}
        seen = set()
        sorted_assets = sorted(assets, key=lambda asset_entity: asset_entity['name'].lower()) if assets else []
        
        for asset in sorted_assets:
            try:
                asset_name = asset['name']
                asset_id = asset['id']
                asset_type = asset['type']['name']
                if asset_name not in seen:
                    unique_version[asset_name] = asset_id
                    unique_types[asset_name] = asset_type
                    seen.add(asset_name)
                    _log.debug(f"[get_assets_list] Added asset: {asset_name} (id: {asset_id}, type: {asset_type})")
            except Exception as e:
                _log.warning(f"[get_assets_list] Failed to process asset: {e}")
                continue
        
        _log.info(f"[get_assets_list] Returning {len(unique_version)} unique assets")
        return unique_version, unique_types
    except Exception as e:
        _log.error(f"[get_assets_list] Failed to get assets list: {e}", exc_info=True)
        return {}, {}


def apply_name(
    params: Any,  # ParameterInterface
    session: Any,  # Optional[ftrack_api.Session]
    assets_menu_ids: Optional[List[str]] = None,
    assets_menu_index: Optional[int] = None,
    show_message: Optional[Any] = None
) -> bool:
    """
    Apply asset from name/type or selected asset (mimics fselector.applyName).
    
    Args:
        params: Parameter interface
        session: Ftrack session
        assets_menu_ids: Optional list of asset IDs (for menu selection)
        assets_menu_index: Optional selected index in menu
        show_message: Optional function to show messages
    
    Returns:
        True if successful, False otherwise
    """
    _log.info("[apply_name] Starting apply_name")
    _log.info(f"[apply_name] assets_menu_ids: {assets_menu_ids}, assets_menu_index: {assets_menu_index}")
    
    if not session:
        _log.warning("[apply_name] Ftrack session is not available")
        return False
    
    # Check if assets menu is available (from get_ex)
    if assets_menu_ids and assets_menu_index is not None and assets_menu_index >= 0:
        _log.info(f"[apply_name] Using assets menu, index: {assets_menu_index}")
        if assets_menu_index < len(assets_menu_ids):
            asset_id = assets_menu_ids[assets_menu_index]
            _log.info(f"[apply_name] Selected asset_id from menu: {asset_id}")
            try:
                asset = session.get('Asset', asset_id)
                asset_name = asset['name']
                asset_type = asset['type']['name']
                _log.info(f"[apply_name] Found asset: {asset_name} (type: {asset_type})")
                
                if asset_name != 'new_asset':
                    params.set_parameter('asset_id', asset_id)
                    params.set_parameter('asset_name', asset_name)
                    params.set_parameter('type', asset_type)
                    _log.info("[apply_name] Asset parameters set successfully (from menu)")
                    return True
            except Exception as e:
                _log.error(f"[apply_name] Failed to load asset: {e}", exc_info=True)
                return False
    
    # Check if name field is available (from cr_new)
    name = params.get_parameter('name')
    if name:
        ass_type = params.get_parameter('ass_type')
        task_id = params.get_parameter('task_Id')
        
        if not task_id:
            if show_message:
                show_message("Task ID is empty. Set Task Id first.", "warning")
            return False
        
        # Check if asset with same name already exists
        exists = False
        try:
            task = session.get('Task', task_id)
            parent_id = task['parent_id']
            existing_asset = session.query(
                f'Asset where name is "{name}" and parent.id is "{parent_id}"'
            ).first()
            if existing_asset is not None:
                exists = True
            else:
                existing_build = session.query(
                    f'AssetBuild where name is "{name}" and parent.id is "{parent_id}"'
                ).first()
                if existing_build is not None:
                    exists = True
        except Exception as e:
            _log.warning(f"Failed to validate existing name '{name}': {e}")
        
        if exists:
            if show_message:
                show_message(f"Name '{name}' already exists. Try to select from existing assets.", "warning")
            return False
        
        # Clear asset_id and set name/type
        _log.info(f"[apply_name] Setting asset parameters: asset_id='', asset_name='{name}', type='{ass_type}'")
        params.set_parameter('asset_id', "")
        params.set_parameter('asset_name', name)
        params.set_parameter('type', ass_type)
        _log.info("[apply_name] Asset parameters set successfully (from name/type)")
        return True
    
    _log.warning("[apply_name] No name field and no assets menu selection")
    if show_message:
        show_message("No asset selected. Please use 'get_ex' or 'cr_new' first.", "info")
    return False
