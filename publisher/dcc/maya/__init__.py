"""
Maya DCC bridge and node implementation for Universal Publisher.

This module provides:
- Maya node creation with static attributes
- Button to open Qt UI for dynamic Task Definition
- DCC bridge for reading/writing Maya node attributes
- build_job_from_maya_node() - build PublishJob from Maya node
- publish_callback() / publish_dry_run_callback() - publish callbacks
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

_log = logging.getLogger(__name__)

# Maya imports (only available in Maya)
try:
    import maya.cmds as cmds
    import maya.OpenMayaUI as omui
    MAYA_AVAILABLE = True
except ImportError:
    MAYA_AVAILABLE = False
    cmds = None  # type: ignore
    omui = None  # type: ignore

try:
    from PySide6 import QtWidgets, QtCore
    from shiboken6 import wrapInstance
    PYSIDE_AVAILABLE = True
except ImportError:
    try:
        from PySide2 import QtWidgets, QtCore
        from shiboken2 import wrapInstance
        PYSIDE_AVAILABLE = True
    except ImportError:
        PYSIDE_AVAILABLE = False
        QtWidgets = None  # type: ignore
        QtCore = None  # type: ignore
        wrapInstance = None  # type: ignore

# Import core components
try:
    from ...core import (
        ComponentData,
        PublishJob,
        PublishResult,
        Publisher,
    )
    CORE_AVAILABLE = True
except ImportError as e:
    CORE_AVAILABLE = False
    _log.warning(f"Core publisher not available: {e}")


# Global reference to publisher UI window
_publisher_ui_window = None  # type: ignore[var-annotated]


def get_maya_main_window():
    """Get QWidget of Maya main window."""
    if not PYSIDE6_AVAILABLE or not MAYA_AVAILABLE:
        return None
    try:
        ptr = omui.MQtUtil.mainWindow()
        if ptr is None:
            return None
        return wrapInstance(int(ptr), QtWidgets.QWidget)
    except Exception as e:
        _log.warning(f"Failed to get Maya main window: {e}")
        return None


def create_publisher_node(node_name: Optional[str] = None) -> str:
    """Create Maya node for publisher with static attributes.
    
    Creates a locator node (visible in Outliner and viewport) with attributes for:
    - Static parameters (task_id, asset_id, asset_name, type, use_snapshot, etc.)
    - Buttons available via floating toolbar when selected
    
    Returns:
        Name of created node
    """
    if not MAYA_AVAILABLE:
        raise RuntimeError("Maya is not available")
    
    if node_name is None:
        # Find unique name
        base_name = "mroya_publisher"
        node_name = base_name + "1"
        counter = 1
        while cmds.objExists(node_name):
            counter += 1
            node_name = f"{base_name}{counter}"
    
    # Create locator - visible in Outliner and viewport
    if not cmds.objExists(node_name):
        # Create locator and rename
        loc = cmds.spaceLocator(name=node_name)[0]
        node = loc
        
        # Mark as publisher node
        cmds.addAttr(node, longName="isMroyaPublisher", attributeType="bool", defaultValue=True)
        
        # Set locator scale for visibility
        cmds.setAttr(f"{node}.localScaleX", 0.5)
        cmds.setAttr(f"{node}.localScaleY", 0.5)
        cmds.setAttr(f"{node}.localScaleZ", 0.5)
        
        # Lock transforms (this is a data node, not meant to be moved)
        for attr in ['tx', 'ty', 'tz', 'rx', 'ry', 'rz', 'sx', 'sy', 'sz']:
            cmds.setAttr(f"{node}.{attr}", lock=True)
    else:
        node = node_name
    
    # Add static attributes
    _add_publisher_attributes(node)
    
    _log.info(f"Created publisher node: {node}")
    return node




def _add_publisher_attributes(node: str):
    """Add static publisher attributes to Maya node."""
    
    def add_string_attr(name: str):
        if not cmds.attributeQuery(name, node=node, exists=True):
            cmds.addAttr(node, longName=name, dataType="string")
    
    def add_bool_attr(name: str, default: bool = False):
        if not cmds.attributeQuery(name, node=node, exists=True):
            cmds.addAttr(node, longName=name, attributeType="bool", defaultValue=default)
    
    def add_int_attr(name: str, default: int = 0):
        if not cmds.attributeQuery(name, node=node, exists=True):
            cmds.addAttr(node, longName=name, attributeType="long", defaultValue=default)
    
    # Task parameters (storage - filled after selection)
    add_string_attr("p_task_id")
    add_string_attr("p_project")
    add_string_attr("p_parent")
    
    # Asset parameters (storage - filled after selection)
    add_string_attr("p_asset_id")
    add_string_attr("p_asset_name")
    add_string_attr("p_asset_type")
    
    # Version info (filled after publish)
    add_string_attr("p_version_id")
    add_int_attr("p_version_number")
    
    # Comment
    add_string_attr("comment")
    
    # Snapshot/Playblast toggles
    add_bool_attr("use_snapshot", False)
    add_bool_attr("use_playblast", False)
    add_string_attr("playblast")  # playblast file path
    
    # Components count
    add_int_attr("components", 0)
    
    # Log output
    add_string_attr("log")
    
    # Component attributes are added dynamically via add_component_attributes()
    # Format: comp_name{i}, file_path{i}, export{i}, meta_count{i}


def add_component_attributes(node: str, index: int):
    """Add attributes for a specific component index.
    
    Args:
        node: Maya node name
        index: Component index (1-based)
    """
    if not MAYA_AVAILABLE:
        return
    
    def add_string_attr(name: str):
        if not cmds.attributeQuery(name, node=node, exists=True):
            cmds.addAttr(node, longName=name, dataType="string")
    
    def add_bool_attr(name: str, default: bool = True):
        if not cmds.attributeQuery(name, node=node, exists=True):
            cmds.addAttr(node, longName=name, attributeType="bool", defaultValue=default)
    
    def add_int_attr(name: str, default: int = 0):
        if not cmds.attributeQuery(name, node=node, exists=True):
            cmds.addAttr(node, longName=name, attributeType="long", defaultValue=default)
    
    # Component name and path
    add_string_attr(f"comp_name{index}")
    add_string_attr(f"file_path{index}")
    
    # Export toggle
    add_bool_attr(f"export{index}", True)
    
    # Metadata count
    add_int_attr(f"meta_count{index}", 0)


def _add_ui_button_attribute(node: str):
    """Add button attribute that opens Qt UI for Task Definition."""
    if not cmds.attributeQuery("openTaskDefinition", node=node, exists=True):
        # Create enum attribute as pseudo-button
        cmds.addAttr(
            node,
            longName="openTaskDefinition",
            attributeType="enum",
            enumName=":Open Task Definition",
            keyable=False
        )


def open_task_definition_ui(node_name: Optional[str] = None):
    """Open Qt UI window for Task Definition (dynamic part).
    
    This UI shows only the Task Definition section from PublisherWidget,
    allowing user to select task and asset. Static parameters remain on node.
    """
    global _publisher_ui_window
    
    if not PYSIDE_AVAILABLE:
        _log.error("PySide6/PySide2 is not available in Maya")
        return
    
    if not MAYA_AVAILABLE:
        _log.error("Maya is not available")
        return
    
    # Get node name from selection if not provided
    if node_name is None:
        selection = cmds.ls(selection=True)
        if not selection:
            _log.warning("No node selected. Please select a publisher node first.")
            return
        node_name = selection[0]
    
    # Check if node is a publisher node
    if not cmds.attributeQuery("isMroyaPublisher", node=node_name, exists=True):
        _log.warning(f"Node '{node_name}' is not a publisher node")
        return
    
    # Bootstrap paths
    import sys
    import os
    from pathlib import Path
    
    # Find project root
    project_root = _find_project_root()
    plugins_root = project_root / "ftrack_plugins"
    
    for path in (project_root, plugins_root):
        path_str = str(path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
    
    # Import publisher widget
    try:
        from ftrack_inout.publisher.ui.publisher_widget import PublisherWidget
    except ImportError as e:
        _log.error(f"Failed to import PublisherWidget: {e}")
        return
    
    # Create or reuse window
    main_window = get_maya_main_window()
    
    if _publisher_ui_window is None or not _publisher_ui_window.isVisible():
        # Create dialog with only Task Definition section
        window = QtWidgets.QDialog(main_window)
        window.setWindowTitle(f"Task Definition - {node_name}")
        window.setMinimumWidth(600)
        window.setMinimumHeight(400)
        
        layout = QtWidgets.QVBoxLayout(window)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Create publisher widget
        # TODO: Create a specialized widget that shows only Task Definition section
        # For now, use full widget but we can hide other sections
        publisher_widget = PublisherWidget()
        
        # TODO: Hide non-Task-Definition sections
        # publisher_widget.hide_sections_except_task_definition()
        
        layout.addWidget(publisher_widget)
        
        # Add sync button to copy data back to node
        sync_btn = QtWidgets.QPushButton("Apply to Node")
        sync_btn.clicked.connect(lambda: _sync_ui_to_node(publisher_widget, node_name))
        layout.addWidget(sync_btn)
        
        window.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        _publisher_ui_window = window
    
    _publisher_ui_window.show()
    _publisher_ui_window.raise_()
    _publisher_ui_window.activateWindow()


def _sync_ui_to_node(widget, node_name: str):
    """Sync data from Qt UI back to Maya node."""
    if not MAYA_AVAILABLE:
        return
    
    try:
        # Read values from widget
        task_id = widget.get_parameter('task_Id')
        asset_id = widget.get_parameter('asset_id')
        asset_name = widget.get_parameter('asset_name')
        asset_type = widget.get_parameter('type')
        
        # Write to node
        if task_id:
            cmds.setAttr(f"{node_name}.taskId", task_id, type="string")
        if asset_id:
            cmds.setAttr(f"{node_name}.assetId", asset_id, type="string")
        if asset_name:
            cmds.setAttr(f"{node_name}.assetName", asset_name, type="string")
        if asset_type:
            cmds.setAttr(f"{node_name}.assetType", asset_type, type="string")
        
        _log.info(f"Synced UI data to node: {node_name}")
    except Exception as e:
        _log.error(f"Failed to sync UI to node: {e}")


def _find_project_root():
    """Find Mroya project root."""
    import os
    from pathlib import Path
    
    env_root = os.environ.get("MROOT")
    if env_root:
        env_path = Path(env_root)
        if (env_path / "run_browser.py").is_file():
            return env_path
    
    # Try to find from current file location
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "run_browser.py").is_file():
            return parent
    
    # Fallback
    return here.parents[4]  # Adjust based on structure


# DCC Bridge for Maya
class MayaDCCBridge:
    """Maya DCC bridge for reading/writing node attributes."""
    
    def __init__(self, node_name: str):
        """Initialize with Maya node name."""
        self.node_name = node_name
    
    def get_dcc_name(self) -> str:
        """Return DCC name."""
        return "maya"
    
    def read_parameter(self, param_name: str) -> Any:
        """Read parameter value from Maya node."""
        if not MAYA_AVAILABLE:
            return None
        
        # Use attribute name directly (Maya uses same names now)
        attr_path = f"{self.node_name}.{param_name}"
        
        if not cmds.attributeQuery(param_name, node=self.node_name, exists=True):
            return None
        
        try:
            attr_type = cmds.getAttr(attr_path, type=True)
            if attr_type == "string":
                return cmds.getAttr(attr_path) or ""
            elif attr_type == "bool":
                return 1 if cmds.getAttr(attr_path) else 0
            elif attr_type in ("long", "short", "int"):
                return cmds.getAttr(attr_path)
            else:
                return cmds.getAttr(attr_path)
        except Exception as e:
            _log.warning(f"Failed to read {attr_path}: {e}")
            return None
    
    def set_parameter(self, param_name: str, value: Any) -> None:
        """Set parameter value on Maya node."""
        if not MAYA_AVAILABLE:
            return
        
        attr_path = f"{self.node_name}.{param_name}"
        
        if not cmds.attributeQuery(param_name, node=self.node_name, exists=True):
            _log.warning(f"Attribute {param_name} does not exist on {self.node_name}")
            return
        
        try:
            attr_type = cmds.getAttr(attr_path, type=True)
            if attr_type == "string":
                cmds.setAttr(attr_path, str(value), type="string")
            elif attr_type == "bool":
                cmds.setAttr(attr_path, bool(value))
            elif attr_type in ("long", "short", "int"):
                cmds.setAttr(attr_path, int(value))
            else:
                cmds.setAttr(attr_path, value)
        except Exception as e:
            _log.warning(f"Failed to set {attr_path} = {value}: {e}")


# ============================================================================
# Scene Archive (Snapshot)
# ============================================================================

def save_scene_archive() -> str:
    """Save current Maya scene as archive (snapshot).
    
    Saves a copy of the current scene to a temp folder with timestamp.
    Returns the path to the saved archive.
    """
    if not MAYA_AVAILABLE:
        raise RuntimeError("Maya is not available")
    
    import tempfile
    
    # Get current scene path
    current_scene = cmds.file(query=True, sceneName=True)
    if not current_scene:
        current_scene = "untitled"
    
    # Build archive path
    scene_dir = os.path.dirname(current_scene) if current_scene != "untitled" else tempfile.gettempdir()
    tmp_dir = os.path.join(scene_dir, "tmp")
    
    # Create tmp directory if needed
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir)
    
    # Get scene basename and extension
    basename = os.path.basename(current_scene) if current_scene != "untitled" else "untitled.ma"
    name, ext = os.path.splitext(basename)
    if not ext:
        ext = ".ma"  # Default to Maya ASCII
    
    # Build archive filename with timestamp
    timestamp = time.strftime("%Y%m%d%H%M%S")
    archive_name = f"P_{timestamp}_{name}{ext}"
    archive_path = os.path.join(tmp_dir, archive_name)
    
    _log.info(f"[MayaBridge] Saving scene archive to: {archive_path}")
    
    # Save archive
    cmds.file(rename=archive_path)
    cmds.file(save=True, type="mayaAscii" if ext == ".ma" else "mayaBinary")
    
    # Restore original scene name
    if current_scene and current_scene != "untitled":
        cmds.file(rename=current_scene)
    
    return archive_path


def find_linked_component_ids() -> List[str]:
    """Find all ftrack component IDs linked in the scene.
    
    Scans all nodes for __ftrack_used_CompId attribute.
    """
    if not MAYA_AVAILABLE:
        return []
    
    linked_ids = []
    attrib_name = "__ftrack_used_CompId"
    
    try:
        # Find all nodes with this attribute
        nodes_with_attr = cmds.ls(f"*.{attrib_name}", objectsOnly=True) or []
        
        for node in nodes_with_attr:
            try:
                value = cmds.getAttr(f"{node}.{attrib_name}")
                if value and str(value).strip():
                    linked_ids.append(str(value).strip())
            except Exception:
                continue
    except Exception as e:
        _log.warning(f"[MayaBridge] Error scanning for linked components: {e}")
    
    # Remove duplicates while preserving order
    seen = set()
    unique_ids = []
    for cid in linked_ids:
        if cid not in seen:
            seen.add(cid)
            unique_ids.append(cid)
    
    _log.debug(f"[MayaBridge] Found {len(unique_ids)} linked component IDs")
    return unique_ids


# ============================================================================
# Build PublishJob from Maya Node
# ============================================================================

def build_job_from_maya_node(node_name: str) -> 'PublishJob':
    """Build PublishJob from Maya publisher node.
    
    Reads all parameters from the node and constructs a PublishJob.
    Similar to Houdini's build_job_from_hda.
    
    Args:
        node_name: Name of Maya publisher node
        
    Returns:
        PublishJob ready for execution
    """
    if not MAYA_AVAILABLE:
        raise RuntimeError("Maya is not available")
    
    if not CORE_AVAILABLE:
        raise RuntimeError("Core publisher not available")
    
    if not cmds.objExists(node_name):
        raise ValueError(f"Node '{node_name}' does not exist")
    
    _log.info(f"[MayaBridge] Building PublishJob from node: {node_name}")
    
    # Helper to get attribute value
    def get_attr(name: str, default=None):
        attr_path = f"{node_name}.{name}"
        if not cmds.attributeQuery(name, node=node_name, exists=True):
            return default
        try:
            value = cmds.getAttr(attr_path)
            return value if value is not None else default
        except Exception:
            return default
    
    components: List[ComponentData] = []
    
    # 1. Snapshot component
    use_snapshot = get_attr('use_snapshot', False)
    if use_snapshot:
        _log.debug("[MayaBridge] Adding snapshot component")
        
        # Save scene archive
        try:
            snapshot_path = save_scene_archive()
        except Exception as e:
            _log.error(f"[MayaBridge] Failed to save scene archive: {e}")
            snapshot_path = None
        
        # Collect linked component IDs for ilink metadata
        snapshot_metadata = {}
        try:
            linked_ids = find_linked_component_ids()
            if linked_ids:
                import json
                snapshot_metadata['ilink'] = json.dumps(linked_ids)
        except Exception as e:
            _log.warning(f"[MayaBridge] Failed to collect ilink: {e}")
        
        components.append(ComponentData(
            name='snapshot',
            file_path=snapshot_path,
            component_type='snapshot',
            export_enabled=True,
            metadata=snapshot_metadata
        ))
    
    # 2. Playblast component
    use_playblast = get_attr('use_playblast', False)
    if use_playblast:
        playblast_path = get_attr('playblast', '') or ''
        if playblast_path and not playblast_path.startswith('*'):
            components.append(ComponentData(
                name='playblast',
                file_path=playblast_path,
                component_type='playblast',
                export_enabled=True,
                metadata={'dcc': 'maya'}
            ))
    
    # 3. File components
    component_count = get_attr('components', 0) or 0
    
    for i in range(1, component_count + 1):
        comp_name = get_attr(f'comp_name{i}', f'component_{i}')
        file_path = get_attr(f'file_path{i}', '') or ''
        export_val = get_attr(f'export{i}', True)
        export_enabled = bool(export_val)
        
        # Skip placeholder paths
        if file_path.startswith('*') or not file_path.strip():
            _log.debug(f"[MayaBridge] Skipping placeholder path for component {i}: '{file_path}'")
            continue
        
        # Collect metadata
        metadata = {'dcc': 'maya'}
        meta_count = get_attr(f'meta_count{i}', 0) or 0
        for m in range(1, meta_count + 1):
            key = get_attr(f'key{i}_{m}', '') or ''
            value = get_attr(f'value{i}_{m}', '') or ''
            if key:
                metadata[key] = value
        
        # Determine component type
        component_type = 'file'
        sequence_pattern = None
        frame_range = None
        
        # Try to detect sequence using fileseq
        if file_path:
            seq_result = _detect_sequence_on_disk(file_path)
            if seq_result:
                component_type = 'sequence'
                sequence_pattern = seq_result['pattern']
                frame_range = seq_result.get('frame_range')
                file_path = seq_result['pattern']
        
        components.append(ComponentData(
            name=comp_name,
            file_path=file_path,
            component_type=component_type,
            export_enabled=export_enabled,
            metadata=metadata,
            sequence_pattern=sequence_pattern,
            frame_range=frame_range,
        ))
    
    # Get other parameters
    task_id = get_attr('p_task_id', '') or ''
    asset_id = get_attr('p_asset_id', '') or None
    asset_name = get_attr('p_asset_name', '') or None
    asset_type = get_attr('p_asset_type', '') or None
    comment = get_attr('comment', '') or ''
    
    # Get scene path
    source_scene = None
    try:
        source_scene = cmds.file(query=True, sceneName=True)
    except Exception:
        pass
    
    # Build job
    job = PublishJob(
        task_id=task_id,
        asset_id=asset_id if asset_id else None,
        asset_name=asset_name,
        asset_type=asset_type,
        comment=comment,
        components=components,
        source_dcc='maya',
        source_scene=source_scene,
    )
    
    _log.info(
        f"[MayaBridge] Built PublishJob: task={job.task_id}, "
        f"asset={job.asset_id or job.asset_name}, "
        f"components={len(components)}"
    )
    
    return job


def _detect_sequence_on_disk(file_path: str) -> Optional[Dict[str, Any]]:
    """Detect sequence on disk from a single file path.
    
    Uses fileseq to find the full sequence from a single file.
    """
    if not file_path:
        return None
    
    seq_extensions = ['.vdb', '.exr', '.jpg', '.jpeg', '.tiff', '.tif',
                      '.png', '.bgeo.sc', '.geo', '.geo.sc', '.abc', '.ass']
    
    file_lower = file_path.lower()
    is_seq_ext = any(file_lower.endswith(ext) for ext in seq_extensions)
    
    if not is_seq_ext:
        return None
    
    try:
        import fileseq as fs
        
        seq = fs.findSequenceOnDisk(file_path)
        
        if seq is None or len(seq) <= 1:
            return None
        
        # Build pattern with frame range
        combine = seq.format('{dirname}{basename}')
        padding = '%04d'
        range_str = seq.format('{start}-{end}')
        ext = seq.extension()
        
        pattern = f"{combine.replace(os.sep, '/')}{padding}{ext} [{range_str}]"
        
        start_frame = int(seq.format('{start}'))
        end_frame = int(seq.format('{end}'))
        
        return {
            'pattern': pattern,
            'frame_range': (start_frame, end_frame)
        }
        
    except ImportError:
        _log.debug("[MayaBridge] fileseq not available")
        return None
    except Exception as e:
        _log.debug(f"[MayaBridge] Not a sequence or error: {e}")
        return None


# ============================================================================
# Publish Callbacks
# ============================================================================

def _get_ftrack_session():
    """Get or create Ftrack session using shared session factory."""
    try:
        # Try to use shared session factory (with optimized caching)
        from ...common.session_factory import get_shared_session
        session = get_shared_session()
        if session:
            return session
    except ImportError:
        _log.debug("[MayaBridge] Common session factory not available, falling back to local session")
    except Exception as e:
        _log.debug(f"[MayaBridge] Failed to get shared session: {e}")
    
    # Fallback: Try to get existing session from Maya
    try:
        import maya.cmds as cmds
        if hasattr(cmds, '_ftrack_session') and cmds._ftrack_session:
            return cmds._ftrack_session
    except Exception:
        pass
    
    # Fallback: Create new session
    try:
        import ftrack_api
        session = ftrack_api.Session(auto_connect_event_hub=False)
        # Store for reuse
        try:
            cmds._ftrack_session = session
        except Exception:
            pass
        return session
        
    except Exception as e:
        _log.warning(f"[MayaBridge] Failed to get Ftrack session: {e}")
        return None


def publish_callback(node_name: str = None):
    """Main publish callback for Maya.
    
    Call from shelf button or script:
        from ftrack_inout.publisher.dcc.maya import publish_callback
        publish_callback()  # Uses selected node
        publish_callback("mroya_publisher1")  # Explicit node
    """
    if not MAYA_AVAILABLE:
        _log.error("[MayaBridge] Maya is not available")
        return
    
    # Get node name from selection if not provided
    if node_name is None:
        selection = cmds.ls(selection=True)
        if selection:
            node_name = selection[0]
        else:
            _log.error("[MayaBridge] No node selected or specified")
            cmds.warning("Please select a publisher node or specify node name")
            return
    
    try:
        # Build job
        job = build_job_from_maya_node(node_name)
        
        # Validate
        is_valid, errors = job.validate()
        if not is_valid:
            error_msg = "Validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            cmds.warning(error_msg)
            _log.error(f"[MayaBridge] {error_msg}")
            return
        
        # Get Ftrack session
        session = _get_ftrack_session()
        if not session:
            cmds.warning("Ftrack session not available. Make sure Ftrack is connected.")
            return
        
        # Execute publish
        publisher = Publisher(session=session, dry_run=False)
        result = publisher.execute(job)
        
        if result.success:
            msg = (
                f"Published successfully!\n\n"
                f"Asset Version: #{result.asset_version_number}\n"
                f"Components: {len(result.component_ids)}"
            )
            cmds.confirmDialog(title="Publish Success", message=msg, button=["OK"])
            
            # Update node parameters
            _update_node_after_publish(node_name, result)
        else:
            cmds.warning(f"Publish failed: {result.error_message}")
            _log.error(f"[MayaBridge] Publish failed: {result.error_message}")
            
    except Exception as e:
        import traceback
        _log.error(f"[MayaBridge] Publish error: {e}", exc_info=True)
        cmds.warning(f"Publish error: {e}")


def publish_dry_run_callback(node_name: str = None):
    """Dry-run publish callback for testing.
    
    Call from shelf button or script:
        from ftrack_inout.publisher.dcc.maya import publish_dry_run_callback
        publish_dry_run_callback()
    """
    if not MAYA_AVAILABLE:
        _log.error("[MayaBridge] Maya is not available")
        return
    
    # Get node name from selection if not provided
    if node_name is None:
        selection = cmds.ls(selection=True)
        if selection:
            node_name = selection[0]
        else:
            _log.error("[MayaBridge] No node selected or specified")
            cmds.warning("Please select a publisher node or specify node name")
            return
    
    try:
        # Build job
        job = build_job_from_maya_node(node_name)
        
        # Execute dry run (no session needed)
        publisher = Publisher(session=None, dry_run=True)
        result = publisher.execute(job)
        
        cmds.confirmDialog(
            title="Dry Run Complete",
            message=f"Check Script Editor for details.\nWould create {len(result.component_ids)} components.",
            button=["OK"]
        )
        
    except Exception as e:
        import traceback
        _log.error(f"[MayaBridge] Dry-run error: {e}", exc_info=True)
        cmds.warning(f"Dry-run error: {e}")


def _update_node_after_publish(node_name: str, result: 'PublishResult'):
    """Update node parameters after successful publish."""
    if not MAYA_AVAILABLE:
        return
    
    try:
        def set_attr(name: str, value):
            attr_path = f"{node_name}.{name}"
            if cmds.attributeQuery(name, node=node_name, exists=True):
                try:
                    attr_type = cmds.getAttr(attr_path, type=True)
                    if attr_type == "string":
                        cmds.setAttr(attr_path, str(value), type="string")
                    else:
                        cmds.setAttr(attr_path, value)
                except Exception:
                    pass
        
        # Update version info
        if result.asset_version_id:
            set_attr('p_version_id', result.asset_version_id)
        if result.asset_version_number:
            set_attr('p_version_number', result.asset_version_number)
        if result.asset_id:
            set_attr('p_asset_id', result.asset_id)
        if result.asset_name:
            set_attr('p_asset_name', result.asset_name)
        
        # Update log
        timestamp = time.strftime("%H:%M:%S")
        log_msg = f"[{timestamp}] Published v{result.asset_version_number}: {len(result.component_ids)} components"
        set_attr('log', log_msg)
        
        _log.info(f"[MayaBridge] Node parameters updated: {node_name}")
        
    except Exception as e:
        _log.warning(f"[MayaBridge] Failed to update node after publish: {e}")
