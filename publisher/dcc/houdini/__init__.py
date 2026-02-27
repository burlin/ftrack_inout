"""
Houdini DCC bridge for Universal Publisher.

This module provides:
- HoudiniParameterInterface: Reads/writes HDA parameters
- HoudiniBridge: DCC-specific functions (saveArchive, find_linked_components)
- Functions for HDA callbacks
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any, Dict, List, Optional, Tuple

_log = logging.getLogger(__name__)

# Houdini imports (only available in Houdini)
try:
    import hou
    HOUDINI_AVAILABLE = True
except ImportError:
    HOUDINI_AVAILABLE = False
    hou = None  # type: ignore

# Import core components
try:
    from ...core import (
        ComponentData,
        PublishJob,
        PublishResult,
        Publisher,
        JobBuilder,
    )
    CORE_AVAILABLE = True
except ImportError as e:
    CORE_AVAILABLE = False
    _log.warning(f"Core publisher not available: {e}")


class HoudiniParameterInterface:
    """Parameter interface for Houdini HDA nodes.
    
    Implements the ParameterInterface protocol for reading/writing HDA parameters.
    Supports target_asset parameter for forwarding to external nodes.
    """
    
    def __init__(self, node, target_node=None):
        """Initialize with HDA node.
        
        Args:
            node: Source HDA node (hou.Node)
            target_node: Target node for p_* parameters (optional, from target_asset)
        """
        self.node = node
        self.target_node = target_node or node
    
    def get_parameter(self, name: str) -> Any:
        """Get parameter value from node."""
        if not HOUDINI_AVAILABLE:
            return None
        
        # Determine which node to read from
        # p_* and task_* parameters go to target_node
        if name.startswith('p_') or name.startswith('task_'):
            read_node = self.target_node
        else:
            read_node = self.node
        
        try:
            parm = read_node.parm(name)
            if parm is None:
                return None
            
            # Get value based on parameter type
            parm_template = parm.parmTemplate()
            parm_type = parm_template.type()
            
            if parm_type == hou.parmTemplateType.String:
                return parm.eval()
            elif parm_type == hou.parmTemplateType.Int:
                return parm.eval()
            elif parm_type == hou.parmTemplateType.Toggle:
                return parm.eval()
            elif parm_type == hou.parmTemplateType.Float:
                return parm.eval()
            elif parm_type == hou.parmTemplateType.Menu:
                return parm.evalAsString()
            else:
                return parm.eval()
        except Exception as e:
            _log.warning(f"Failed to read parameter '{name}': {e}")
            return None
    
    def set_parameter(self, name: str, value: Any) -> None:
        """Set parameter value on node."""
        if not HOUDINI_AVAILABLE:
            return
        
        # Determine which node to write to
        if name.startswith('p_') or name.startswith('task_'):
            write_node = self.target_node
        else:
            write_node = self.node
        
        try:
            parm = write_node.parm(name)
            if parm is not None:
                parm.set(value)
                _log.debug(f"Set parameter '{name}' = '{value}' on {write_node.path()}")
        except Exception as e:
            _log.warning(f"Failed to set parameter '{name}': {e}")
    
    def show_message(self, message: str, severity: str = "info") -> None:
        """Show message using Houdini UI."""
        if not HOUDINI_AVAILABLE:
            print(f"[{severity}] {message}")
            return
        
        try:
            if severity == "error":
                hou.ui.displayMessage(message, severity=hou.severityType.Error)
            elif severity == "warning":
                hou.ui.displayMessage(message, severity=hou.severityType.Warning)
            else:
                hou.ui.displayMessage(message, severity=hou.severityType.Message)
        except Exception:
            print(f"[{severity}] {message}")


def get_target_node(node) -> 'hou.Node':
    """Get target node from target_asset parameter.
    
    If target_asset is set and points to a valid node, return that node.
    Otherwise return the source node.
    """
    if not HOUDINI_AVAILABLE:
        return node
    
    try:
        target_asset_parm = node.parm('target_asset')
        if target_asset_parm:
            path = target_asset_parm.eval().strip()
            if path:
                target = hou.node(path)
                if target is not None:
                    return target
    except Exception as e:
        _log.warning(f"Failed to get target node: {e}")
    
    return node


def save_scene_archive() -> str:
    """Save current scene as archive (snapshot).
    
    Saves a copy of the current .hip file to $HIP/tmp/ with timestamp.
    Returns the path to the saved archive.
    """
    if not HOUDINI_AVAILABLE:
        raise RuntimeError("Houdini is not available")
    
    import time
    import os
    
    original_file = hou.hipFile.path()
    
    # Build archive path: $HIP/tmp/P_YYYYMMDDHHMMSS_filename.hip
    hip_dir = hou.getenv("HIP") or os.path.dirname(original_file)
    tmp_dir = os.path.join(hip_dir, "tmp")
    
    # Create tmp directory if it doesn't exist
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir)
    
    timestamp = time.strftime("%Y%m%d%H%M%S")
    basename = hou.hipFile.basename()
    archive_name = f"P_{timestamp}_{basename}"
    archive_path = os.path.join(tmp_dir, archive_name)
    archive_path = str(archive_path)  # Ensure string
    
    _log.info(f"[HoudiniBridge] Saving scene archive to: {archive_path}")
    
    # Save archive without adding to recent files
    hou.hipFile.save(file_name=archive_path, save_to_recent_files=False)
    
    # Restore original filename in session
    hou.hipFile.setName(original_file)
    
    return archive_path


def find_linked_component_ids() -> List[str]:
    """Find all __ftrack_used_CompId values in the scene.
    
    Scans all nodes for the __ftrack_used_CompId attribute and returns
    a list of component IDs that are linked in this scene.
    """
    if not HOUDINI_AVAILABLE:
        return []
    
    linked_ids = []
    attrib_name = "__ftrack_used_CompId"
    
    try:
        # Search all nodes in scene
        for node in hou.node('/').allSubChildren():
            try:
                parm = node.parm(attrib_name)
                if parm:
                    value = parm.eval()
                    if value and str(value).strip():
                        linked_ids.append(str(value).strip())
            except Exception:
                continue
    except Exception as e:
        _log.warning(f"[HoudiniBridge] Error scanning for linked components: {e}")
    
    # Remove duplicates while preserving order
    seen = set()
    unique_ids = []
    for cid in linked_ids:
        if cid not in seen:
            seen.add(cid)
            unique_ids.append(cid)
    
    _log.debug(f"[HoudiniBridge] Found {len(unique_ids)} linked component IDs")
    return unique_ids


def build_job_from_hda(node) -> PublishJob:
    """Build PublishJob from HDA node.
    
    Reads parameters from publish HDA structure:
    - Selector: task_Id, asset_name, asset_id, type (working fields)
    - Task folder: p_task_id, task_project, task_parent, task_name (storage)
    - Asset folder: p_project, p_parent, p_asset_type, p_asset_name, p_asset_id (storage)
    - Components: use_snapshot, use_playblast, playblast, components multiparm
    - comment: version comment (needs to be added to HDA)
    
    Args:
        node: HDA node (hou.Node) or node path (str)
        
    Returns:
        PublishJob ready for execution
    """
    if not HOUDINI_AVAILABLE:
        raise RuntimeError("Houdini is not available")
    
    if not CORE_AVAILABLE:
        raise RuntimeError("Core publisher is not available")
    
    # Get node if path provided
    if isinstance(node, str):
        node = hou.node(node)
        if node is None:
            raise ValueError(f"Node not found: {node}")
    
    # Get target node (for p_* parameters if target_asset is set)
    target_node = get_target_node(node)
    
    _log.info(f"[HoudiniBridge] Building PublishJob from {node.path()}")
    if target_node != node:
        _log.info(f"[HoudiniBridge] Using target_node: {target_node.path()}")
    
    # Helper to read from correct node
    def get_parm(name: str):
        """Get parameter value, using target_node for p_* params."""
        # p_* and task_* parameters are on target_node
        if name.startswith('p_') or name.startswith('task_'):
            read_node = target_node
        else:
            read_node = node
        
        parm = read_node.parm(name)
        if parm is None:
            return None
        
        return parm.eval()
    
    components: List[ComponentData] = []
    
    # 1. Snapshot component
    use_snapshot = get_parm('use_snapshot')
    if use_snapshot:
        _log.debug("[HoudiniBridge] Adding snapshot component")
        
        # Save scene archive
        try:
            snapshot_path = save_scene_archive()
        except Exception as e:
            _log.error(f"[HoudiniBridge] Failed to save scene archive: {e}")
            snapshot_path = None
        
        # Collect linked component IDs for ilink metadata
        snapshot_metadata = {}
        try:
            linked_ids = find_linked_component_ids()
            if linked_ids:
                import json
                snapshot_metadata['ilink'] = json.dumps(linked_ids)
                _log.debug(f"[HoudiniBridge] Snapshot ilink: {len(linked_ids)} components")
        except Exception as e:
            _log.warning(f"[HoudiniBridge] Failed to collect ilink: {e}")
        
        components.append(ComponentData(
            name='snapshot',
            file_path=snapshot_path,
            component_type='snapshot',
            export_enabled=True,
            metadata=snapshot_metadata  # No 'dcc' tag for snapshot, but has ilink
        ))
    
    # 2. Playblast component
    use_playblast = get_parm('use_playblast')
    if use_playblast:
        playblast_path = get_parm('playblast') or ''
        _log.debug(f"[HoudiniBridge] Adding playblast component: {playblast_path}")
        
        # Check if playblast is a sequence
        playblast_seq = _detect_sequence_on_disk(playblast_path)
        if playblast_seq:
            playblast_path = playblast_seq['pattern']
        
        components.append(ComponentData(
            name='playblast',
            file_path=playblast_path,
            component_type='playblast',
            export_enabled=True,
            metadata={'dcc': 'houdini'}
        ))
    
    # 3. File components (always read, use_custom only controls UI visibility)
    # Get component count from multiparm
    # In HDA, 'components' is a TabbedMultiparmBlock folder
    components_parm = node.parm('components')
    component_count = components_parm.eval() if components_parm else 0
    _log.debug(f"[HoudiniBridge] Processing {component_count} file components")
    
    if component_count > 0:
        
        for i in range(1, component_count + 1):
            comp_name = get_parm(f'comp_name{i}') or f'component_{i}'
            # Get evaluated path (expressions/variables like $F4 expanded)
            file_path = get_parm(f'file_path{i}') or ''
            # Raw path (unexpanded) - for sequence fallback when $F4→0001 but files start at 1128
            file_path_raw = None
            try:
                fp_parm = node.parm(f'file_path{i}')
                if fp_parm and hasattr(fp_parm, 'rawValue'):
                    file_path_raw = fp_parm.rawValue() or ''
            except Exception:
                pass
            
            export_val = get_parm(f'export{i}')
            export_enabled = (export_val == 1 or export_val is True) if export_val is not None else True
            
            # Skip placeholder paths (e.g., "*.abc", "*.hip") - these are templates, not real files
            if file_path.startswith('*') or not file_path.strip():
                _log.debug(f"[HoudiniBridge] Skipping placeholder/empty path for component {i}: '{file_path}'")
                continue
            
            # Collect metadata from nested multiparm
            metadata = {'dcc': 'houdini'}
            meta_count_parm = node.parm(f'meta_count{i}')
            meta_count = meta_count_parm.eval() if meta_count_parm else 0
            for m in range(1, meta_count + 1):
                key = get_parm(f'key{i}_{m}') or ''
                value = get_parm(f'value{i}_{m}') or ''
                if key:
                    metadata[key] = value
            
            # Determine component type - use fileseq to detect sequences on disk
            component_type = 'file'
            sequence_pattern = None
            frame_range = None
            
            if file_path:
                seq_result = _detect_sequence_on_disk(file_path, raw_path=file_path_raw)
                if seq_result:
                    component_type = 'sequence'
                    sequence_pattern = seq_result['pattern']
                    frame_range = seq_result.get('frame_range')
                    file_path = seq_result['pattern']  # Use pattern as file_path
                    _log.debug(f"[HoudiniBridge] Detected sequence: {sequence_pattern}, range: {frame_range}")
            
            _log.debug(
                f"[HoudiniBridge] Component {i}: "
                f"name='{comp_name}', type='{component_type}', enabled={export_enabled}, "
                f"path='{file_path}'"
            )
            
            components.append(ComponentData(
                name=comp_name,
                file_path=file_path,
                component_type=component_type,
                export_enabled=export_enabled,
                metadata=metadata,
                sequence_pattern=sequence_pattern,
                frame_range=frame_range,
            ))
    
    # Get scene path
    source_scene = None
    try:
        source_scene = hou.hipFile.path()
    except Exception:
        pass
    
    # Read from storage parameters (p_* on target_node)
    # These are the "confirmed" values, not the working fields
    task_id = get_parm('p_task_id') or ''
    asset_id = get_parm('p_asset_id') or None
    asset_name = get_parm('p_asset_name') or None
    asset_type = get_parm('p_asset_type') or None
    
    # Comment parameter (may not exist in old HDA versions)
    comment = get_parm('comment') or ''
    
    # Thumbnail (optional - for versions without playblast)
    thumbnail_path = get_parm('thumbnail_path') or None
    if thumbnail_path:
        thumbnail_path = str(thumbnail_path).strip() or None
    
    # Build job
    job = PublishJob(
        task_id=task_id,
        asset_id=asset_id,
        asset_name=asset_name,
        asset_type=asset_type,
        comment=comment,
        components=components,
        thumbnail_path=thumbnail_path,
        source_dcc='houdini',
        source_scene=source_scene,
    )
    
    _log.info(
        f"[HoudiniBridge] Built PublishJob: task={job.task_id}, "
        f"asset={job.asset_id or job.asset_name}, "
        f"components={len(components)}"
    )
    
    return job


def _is_sequence_pattern(path: str) -> bool:
    """Check if path contains sequence pattern."""
    if not path:
        return False
    
    indicators = ['%d', '%0', '$F', '@', '#']
    for indicator in indicators:
        if indicator in path:
            if indicator == '#':
                import re
                if re.search(r'[._]#+[._]', path) or path.endswith('#'):
                    return True
            else:
                return True
    return False


def _detect_sequence_on_disk(
    file_path: str,
    raw_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Detect sequence on disk from a single file path.
    
    Uses fileseq to find the full sequence from a single file.
    When path contains Houdini $F4 (expanded to current frame), the evaluated
    file may not exist (e.g. frame 1 when sequence starts at 1128). In that case,
    tries findSequencesOnDisk with a wildcard pattern derived from the path.
    
    Args:
        file_path: Path to a single file (evaluated, may be part of a sequence)
        raw_path: Raw/unexpanded path (e.g. with $F4) - used for fallback when
            evaluated path points to non-existent file
        
    Returns:
        Dict with 'pattern', 'frame_range' if sequence found, else None
    """
    if not file_path:
        return None
    
    import os
    import re
    
    # Extensions that are typically sequences
    seq_extensions = ['.vdb', '.exr', '.jpg', '.jpeg', '.bgeo', '.tiff', '.tif', 
                      '.png', '.bgeo.sc', '.geo', '.geo.sc', '.sc', '.abc', '.ass']
    
    # Check if file has a sequence-like extension
    file_lower = file_path.lower()
    is_seq_ext = any(file_lower.endswith(ext) for ext in seq_extensions)
    
    if not is_seq_ext:
        return None
    
    def _seq_to_result(seq) -> Dict[str, Any]:
        """Convert fileseq result to our format."""
        seq_length = len(seq)
        start_frame = seq.start()
        end_frame = seq.end()
        dirname = seq.dirname()
        basename = seq.basename()
        padding = seq.padding()
        ext = seq.extension()
        
        if padding:
            pad_len = len(padding.replace('@', '').replace('#', ''))
            if pad_len == 0:
                pad_len = len(str(end_frame))
            pad_str = f'%0{pad_len}d'
        else:
            pad_str = '%04d'
        
        pattern = os.path.join(dirname, f"{basename}{pad_str}{ext}")
        pattern = pattern.replace('\\', '/')
        frame_range_str = f'{start_frame}-{end_frame}'
        full_path = f"{pattern} [{frame_range_str}]"
        
        _log.debug(
            f"[HoudiniBridge] Sequence detected: {seq_length} frames, "
            f"range {start_frame}-{end_frame}, pattern: {pattern}"
        )
        return {
            'pattern': full_path,
            'frame_range': (start_frame, end_frame),
            'length': seq_length,
        }
    
    try:
        import fileseq as fs
        
        # 1. Try findSequenceOnDisk with evaluated path (works when file exists)
        seq = fs.findSequenceOnDisk(file_path)
        
        if seq is not None and len(seq) > 1:
            return _seq_to_result(seq)
        
        # 2. Fallback: evaluated path points to non-existent file (e.g. $F4→0001
        #    when current frame is 1 but sequence on disk is 1128-1135). Build
        #    wildcard pattern and scan directory.
        dirname = os.path.dirname(file_path)
        basename = os.path.basename(file_path)
        
        # Prefer raw_path if it contains $F - convert $F4 etc to fileseq @
        pattern_path = None
        if raw_path and '$F' in raw_path:
            # Convert X:/path/maya_part.$F4.sc → X:/path/maya_part.@.sc
            pattern_path = re.sub(r'\$F\d*', '@', raw_path)
            pattern_path = pattern_path.replace('\\', '/')
        else:
            # From evaluated path maya_part.0001.sc → maya_part.@.sc
            match = re.match(r'^(.+?)\.(\d+)\.([^.]+)$', basename)
            if match:
                prefix, _frame, ext = match.groups()
                pattern_path = os.path.join(dirname, f"{prefix}.@{ext}")
                pattern_path = pattern_path.replace('\\', '/')
        
        if pattern_path and os.path.isdir(dirname):
            seqs = fs.findSequencesOnDisk(pattern_path)
            if seqs:
                # Pick first (or longest) sequence
                seq = max(seqs, key=len)
                if len(seq) > 1:
                    return _seq_to_result(seq)
        
        return None
        
    except ImportError:
        _log.warning("[HoudiniBridge] fileseq not available, sequence detection disabled")
        return None
    except Exception as e:
        _log.debug(f"[HoudiniBridge] Not a sequence or error: {e}")
        return None


# ============================================================================
# HDA Callback Functions
# ============================================================================

def publish_callback():
    """Main publish callback for HDA button.
    
    If HDA parm 'publish_in_background' is true, runs publish in a separate thread
    so Houdini stays responsive; result is shown and node updated on main thread.
    
    Call this from HDA 'Render' button callback:
        from ftrack_inout.publisher.dcc.houdini import publish_callback
        publish_callback()
    """
    if not HOUDINI_AVAILABLE:
        print("[HoudiniBridge] Houdini is not available")
        return
    
    node = hou.pwd()
    
    # Read "Publish in background" checkbox (HDA parm: publish_in_background)
    publish_in_background = False
    parm = node.parm("publish_in_background")
    if parm is not None:
        try:
            publish_in_background = bool(parm.eval())
        except Exception:
            pass
    
    try:
        # Build job (on main thread; job is plain data)
        job = build_job_from_hda(node)
        
        # Validate
        is_valid, errors = job.validate()
        if not is_valid:
            error_msg = "Validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            hou.ui.displayMessage(error_msg, severity=hou.severityType.Error)
            return
        
        # Get Ftrack session (needed for both paths)
        session = _get_ftrack_session()
        if not session:
            hou.ui.displayMessage(
                "Ftrack session not available.\n"
                "Make sure Ftrack is connected.",
                severity=hou.severityType.Error
            )
            return
        
        if publish_in_background:
            _run_publish_in_background(job, node)
            hou.ui.displayMessage(
                "Publish started in background.\nYou can keep working; a message will show when done.",
                severity=hou.severityType.Message
            )
            return
        
        # Execute publish on main thread (blocking)
        publisher = Publisher(session=session, dry_run=False)
        result = publisher.execute(job)
        _show_publish_result_and_update_node(node, result)
            
    except Exception as e:
        import traceback
        _log.error(f"[HoudiniBridge] Publish error: {e}", exc_info=True)
        hou.ui.displayMessage(
            f"Publish error:\n{e}\n\n{traceback.format_exc()}",
            severity=hou.severityType.Error
        )


def _run_publish_in_background(job: "PublishJob", node: "hou.Node"):
    """Run publish in a worker thread; on completion run UI update on main thread."""
    node_path = node.path()
    
    def worker():
        result = None
        try:
            # Use a new session in the thread (ftrack session is not thread-safe to share)
            import ftrack_api
            session = ftrack_api.Session(auto_connect_event_hub=False)
            publisher = Publisher(session=session, dry_run=False)
            result = publisher.execute(job)
        except Exception as e:
            import traceback
            _log.error(f"[HoudiniBridge] Background publish error: {e}", exc_info=True)
            result = PublishResult(success=False, error_message=f"{e}\n{traceback.format_exc()}")
        
        if result is not None and HOUDINI_AVAILABLE:
            hou.executeInMainThreadWithResult(
                lambda: _show_publish_result_and_update_node(hou.node(node_path), result)
            )
    
    thread = threading.Thread(target=worker, name="FtPublishBackground", daemon=True)
    thread.start()


def _show_publish_result_and_update_node(node: "hou.Node", result: "PublishResult"):
    """Show result message and update node params; must run on main thread."""
    if result.success:
        msg = (
            f"Published successfully!\n\n"
            f"Asset Version: #{result.asset_version_number}\n"
            f"Components: {len(result.component_ids)}\n\n"
            f"Component IDs:\n" +
            "\n".join(f"  - {cid}" for cid in result.component_ids)
        )
        hou.ui.displayMessage(msg, severity=hou.severityType.Message)
        _update_node_after_publish(node, result)
    else:
        hou.ui.displayMessage(
            f"Publish failed:\n{result.error_message}",
            severity=hou.severityType.Error
        )


def publish_dry_run_callback():
    """Dry-run publish callback for testing.
    
    Call this from HDA button callback:
        from ftrack_inout.publisher.dcc.houdini import publish_dry_run_callback
        publish_dry_run_callback()
    """
    if not HOUDINI_AVAILABLE:
        print("[HoudiniBridge] Houdini is not available")
        return
    
    node = hou.pwd()
    
    try:
        # Build job
        job = build_job_from_hda(node)
        
        # Validate
        is_valid, errors = job.validate()
        if not is_valid:
            error_msg = "Validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            hou.ui.displayMessage(error_msg, severity=hou.severityType.Warning)
            # Continue to show dry-run anyway
        
        # Execute dry-run (no session needed)
        publisher = Publisher(session=None, dry_run=True)
        result = publisher.execute(job)
        
        # Result is printed to console by Publisher
        hou.ui.displayMessage(
            f"DRY RUN completed.\n\n"
            f"Check Houdini console for details.\n\n"
            f"Would create {len(result.component_ids)} components.",
            severity=hou.severityType.Message
        )
        
    except Exception as e:
        import traceback
        _log.error(f"[HoudiniBridge] Dry-run error: {e}", exc_info=True)
        hou.ui.displayMessage(
            f"Dry-run error:\n{e}",
            severity=hou.severityType.Error
        )


def _get_ftrack_session():
    """Get Ftrack session using shared session factory."""
    try:
        # Try to use shared session factory (with optimized caching)
        from ...common.session_factory import get_shared_session
        session = get_shared_session()
        if session:
            # Cache in hou.session for backward compatibility
            if HOUDINI_AVAILABLE and hou:
                try:
                    hou.session.ftrack_session = session
                except Exception:
                    pass
            return session
    except ImportError:
        _log.debug("[HoudiniBridge] Common session factory not available, falling back to local session")
    except Exception as e:
        _log.debug(f"[HoudiniBridge] Failed to get shared session: {e}")
    
    # Fallback: Try to get session from hou.session
    if HOUDINI_AVAILABLE and hou:
        try:
            if hasattr(hou.session, 'ftrack_session'):
                return hou.session.ftrack_session
        except Exception:
            pass
        
        # Fallback: Create new session
        try:
            import ftrack_api
            session = ftrack_api.Session(auto_connect_event_hub=False)
            hou.session.ftrack_session = session
            return session
        except Exception as e:
            _log.warning(f"[HoudiniBridge] Failed to create Ftrack session: {e}")
            return None
    
    return None


def _update_node_after_publish(node, result: PublishResult):
    """Update node parameters after successful publish.
    
    Updates target_node with asset/version info.
    Also mirrors to source HDA if target is self.
    """
    try:
        target_node = get_target_node(node)
        
        _log.info(f"[HoudiniBridge] Updating node parameters after publish")
        
        # Update asset info on target node
        if target_node.parm('p_asset_id') and result.asset_id:
            _log.debug(f"[HoudiniBridge] SET p_asset_id = {result.asset_id}")
            target_node.parm('p_asset_id').set(result.asset_id)
        
        if target_node.parm('p_asset_name') and result.asset_name:
            _log.debug(f"[HoudiniBridge] SET p_asset_name = {result.asset_name}")
            target_node.parm('p_asset_name').set(result.asset_name)
        
        # Update version info
        if target_node.parm('p_version_id') and result.asset_version_id:
            _log.debug(f"[HoudiniBridge] SET p_version_id = {result.asset_version_id}")
            target_node.parm('p_version_id').set(result.asset_version_id)
        
        if target_node.parm('p_version_number') and result.asset_version_number:
            _log.debug(f"[HoudiniBridge] SET p_version_number = {result.asset_version_number}")
            target_node.parm('p_version_number').set(result.asset_version_number)
        
        # If target is the HDA itself, also mirror to legacy selector parameters
        if target_node == node:
            _log.debug("[HoudiniBridge] Target is self - mirroring to legacy params")
            
            if node.parm('asset_id') and result.asset_id:
                node.parm('asset_id').set(result.asset_id)
            
            if node.parm('asset_name') and result.asset_name:
                node.parm('asset_name').set(result.asset_name)
        
        # Log to node if log parameter exists
        if node.parm('log'):
            import time
            timestamp = time.strftime("%H:%M:%S")
            log_msg = (
                f"[{timestamp}] Published v{result.asset_version_number}: "
                f"{len(result.component_ids)} components"
            )
            node.parm('log').set(log_msg)
        
        _log.info(f"[HoudiniBridge] Node parameters updated successfully")
            
    except Exception as e:
        _log.warning(f"[HoudiniBridge] Failed to update node after publish: {e}")
