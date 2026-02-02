"""
Houdini-specific helpers for ftrack_inout.browser.

We collect all `hou` imports and Houdini API calls in one place so
main browser modules can, when possible, depend only on
dcc-layer abstractions.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence, Any, Dict
import logging
import os

try:  # pragma: no cover - depends on DCC environment
    import hou  # type: ignore
    HOUDINI_AVAILABLE: bool = True
except Exception:  # ImportError, RuntimeError in non-Houdini environment
    hou = None  # type: ignore
    HOUDINI_AVAILABLE = False


__all__ = [
    "hou",
    "HOUDINI_AVAILABLE",
    "set_global_task_vars",
    "set_task_id_on_selected_nodes",
    "set_hda_params_on_selected_nodes",
    "set_full_params_on_publish_nodes",
    "load_snapshot_hip",
    "apply_scene_setup",
    "HoudiniUserTasksHandlers",
]


_log = logging.getLogger(__name__)


def iter_parms(
    nodes: Iterable["hou.Node"],
    parm_names: Sequence[str],
) -> Iterable[tuple["hou.Node", "hou.Parm"]]:
    """Yield (node, parm) for every existing parm in parm_names on nodes."""
    if not HOUDINI_AVAILABLE:
        return []

    for node in nodes:
        for name in parm_names:
            parm = node.parm(name)
            if parm is not None:
                yield node, parm


def set_global_task_vars(task_id: str, task_label: str) -> None:
    """Set global scene variables FTRACK_CONTEXTID / FTRACK_TASK.

    Used by Set Task button in browser. In non-Houdini environment -- no-op.
    """
    if not HOUDINI_AVAILABLE:
        return

    try:
        def _hset(var: str, value: str) -> None:
            try:
                v = str(value).replace('"', '\\"')
                hou.hscript(f'set -g {var} = "{v}"')
            except Exception as exc:  # pragma: no cover - defensive log
                _log.warning("Failed to set scene var %s: %s", var, exc)

        _hset("FTRACK_CONTEXTID", str(task_id))
        _hset("FTRACK_TASK", task_label)
    except Exception as exc:  # pragma: no cover
        _log.warning("Failed to set global Ftrack task vars in Houdini: %s", exc)


def set_task_id_on_selected_nodes(
    task_id: str,
    task_param_names: Sequence[str],
) -> tuple[int, int]:
    """Set task_id on selected nodes.

    Returns (success_count, failed_count). In non-Houdini environment -- (0, 0).
    """
    if not HOUDINI_AVAILABLE:
        return 0, 0

    selected_nodes = hou.selectedNodes()
    if not selected_nodes:
        return 0, 0

    success_count = 0
    failed_count = 0

    for node in selected_nodes:
        param_found = False
        for param_name in task_param_names:
            parm = node.parm(param_name)
            if parm:
                parm.set(str(task_id))
                success_count += 1
                param_found = True
                _log.info("Set %s=%s on node %s", param_name, task_id, node.path())
                break

        if not param_found:
            failed_count += 1

    return success_count, failed_count


def set_hda_params_on_selected_nodes(
    asset_version_id: str | None,
    component_name: str | None,
    component_id: str | None,
    asset_id: str | None,
    asset_name: str | None,
    asset_type: str | None,
    hda_param_config: Mapping[str, Sequence[str]],
) -> tuple[int, int]:
    """Write HDA parameters on selected nodes according to config.

    Returns (success_count, nodes_without_parms).
    In non-Houdini environment -- (0, 0).
    """
    if not HOUDINI_AVAILABLE:
        return 0, 0

    selected_nodes = hou.selectedNodes()
    if not selected_nodes:
        _log.debug("[set_hda_params] No nodes selected")
        return 0, 0

    _log.debug(f"[set_hda_params] Selected nodes: {[n.path() for n in selected_nodes]}")
    _log.debug(f"[set_hda_params] Config: {dict(hda_param_config)}")
    version_param_names = list(hda_param_config.get("asset_version_id", []))
    component_param_names = list(hda_param_config.get("component_name", []))
    component_id_param_names = list(hda_param_config.get("component_id", []))
    asset_id_param_names = list(hda_param_config.get("asset_id", []))
    asset_name_param_names = list(hda_param_config.get("asset_name", []))
    asset_type_param_names = list(hda_param_config.get("asset_type", []))

    success_count = 0
    nodes_without_parms = 0

    for node in selected_nodes:
        node_updated = False

        if asset_version_id:
            for parm_name in version_param_names:
                parm = node.parm(parm_name)
                if parm:
                    parm.set(str(asset_version_id))
                    node_updated = True
                    break

        if component_name:
            for parm_name in component_param_names:
                parm = node.parm(parm_name)
                if parm:
                    try:
                        parm_template = parm.parmTemplate()
                        if parm_template.type() == hou.parmTemplateType.String:
                            parm.set(component_name)
                            node_updated = True
                            break
                        else:
                            _log.warning(
                                "Parameter %s on %s is not a string parameter, skipping",
                                parm_name,
                                node.path(),
                            )
                    except Exception as exc:
                        _log.warning(
                            "Could not set %s on %s: %s", parm_name, node.path(), exc
                        )

        if component_id:
            for parm_name in component_id_param_names:
                parm = node.parm(parm_name)
                if parm:
                    parm.set(str(component_id))
                    node_updated = True
                    break

        if asset_id:
            for parm_name in asset_id_param_names:
                parm = node.parm(parm_name)
                if parm:
                    try:
                        parm.set(str(asset_id))
                        node_updated = True
                        break
                    except Exception as exc:
                        _log.warning(
                            "Could not set %s on %s: %s", parm_name, node.path(), exc
                        )

        if asset_name:
            for parm_name in asset_name_param_names:
                parm = node.parm(parm_name)
                if parm:
                    try:
                        parm_template = parm.parmTemplate()
                        if parm_template.type() == hou.parmTemplateType.String:
                            parm.set(asset_name)
                            node_updated = True
                            break
                        else:
                            _log.warning(
                                "Parameter %s on %s is not a string parameter, skipping",
                                parm_name,
                                node.path(),
                            )
                    except Exception as exc:
                        _log.warning(
                            "Could not set %s on %s: %s", parm_name, node.path(), exc
                        )

        if asset_type:
            for parm_name in asset_type_param_names:
                parm = node.parm(parm_name)
                if parm:
                    try:
                        parm_template = parm.parmTemplate()
                        if parm_template.type() == hou.parmTemplateType.String:
                            parm.set(asset_type)
                            node_updated = True
                            break
                        else:
                            _log.warning(
                                "Parameter %s on %s is not a string parameter, skipping",
                                parm_name,
                                node.path(),
                            )
                    except Exception as exc:
                        _log.warning(
                            "Could not set %s on %s: %s", parm_name, node.path(), exc
                        )

        if node_updated:
            success_count += 1
            _log.info(
                "Set HDA params on node %s: AssetVersionId=%s, ComponentName=%s, "
                "ComponentId=%s, AssetId=%s, AssetName=%s, AssetType=%s",
                node.path(),
                asset_version_id or "N/A",
                component_name or "N/A",
                component_id or "N/A",
                asset_id or "N/A",
                asset_name or "N/A",
                asset_type or "N/A",
            )
        else:
            nodes_without_parms += 1

    return success_count, nodes_without_parms


def set_full_params_on_publish_nodes(
    session: Any,  # ftrack_api.Session
    asset_id: str,
    asset_name: str,
    asset_type: str,
) -> tuple[int, int]:
    """Set all p_* parameters (except task parameters) and components on publish nodes.
    
    Reads component list from asset.metadata (not from versions) to avoid heavy queries.
    Asset metadata contains index: {"component_name.ext": "component_id", ...}
    Gets project/parent from asset path (asset.parent.project and asset.parent).
    Clears all task-related parameters (p_task_id, task_project, task_parent, task_name).
    
    Args:
        session: Ftrack API session
        asset_id: Asset ID
        asset_name: Asset name
        asset_type: Asset type name
    
    Returns (success_count, nodes_without_parms).
    In non-Houdini environment -- (0, 0).
    """
    if not HOUDINI_AVAILABLE:
        return 0, 0
    
    if not asset_id or not asset_name:
        return 0, 0
    
    if not session:
        _log.warning("No session provided for set_full_params_on_publish_nodes")
        return 0, 0
    
    selected_nodes = hou.selectedNodes()
    if not selected_nodes:
        return 0, 0
    
    try:
        # Get asset entity and read metadata
        asset_entity = session.get('Asset', asset_id)
        if not asset_entity:
            _log.warning("Asset %s not found", asset_id)
            return 0, 0
        
        # Get project and parent from asset path (asset.parent.project and asset.parent)
        try:
            asset_parent = asset_entity.get('parent')
            if asset_parent:
                asset_parent_name = asset_parent.get('name', '') or ''
                asset_project = asset_parent.get('project')
                if asset_project:
                    asset_project_name = asset_project.get('name', '') or ''
                else:
                    asset_project_name = None
            else:
                asset_parent_name = None
                asset_project_name = None
        except Exception as exc:
            _log.warning("Failed to get project/parent from asset: %s", exc)
            asset_parent_name = None
            asset_project_name = None
        
        # Read component index from asset metadata
        asset_metadata = asset_entity.get('metadata') or {}
        if not isinstance(asset_metadata, dict):
            try:
                asset_metadata = dict(asset_metadata)
            except Exception:
                asset_metadata = {}
        
        # Parse metadata keys: format is "component_name.ext" -> component_id
        # Extract component names and extensions (excluding snapshot)
        comp_names = []
        file_paths = []
        for key, comp_id in asset_metadata.items():
            # Skip non-string keys or empty values
            if not isinstance(key, str) or not key:
                continue
            
            # Parse "component_name.ext" format
            if '.' in key:
                comp_name, ext = key.rsplit('.', 1)
                # Skip snapshot
                if comp_name.lower() == 'snapshot':
                    continue
                comp_names.append(comp_name)
                # Create file path mask like *.ext
                if ext:
                    file_paths.append(f"*.{ext}")
                else:
                    file_paths.append("*.*")
            else:
                # Key without extension - use as component name
                if key.lower() != 'snapshot':
                    comp_names.append(key)
                    file_paths.append("*.*")
        
        components_count = len(comp_names)
        
        success_count = 0
        nodes_without_parms = 0
        
        def _get_target_node_or_self(node):
            """Get target node from target_asset parameter, or return node itself."""
            try:
                p = node.parm("target_asset")
                if p is not None:
                    path = p.eval()
                    if isinstance(path, (tuple, list)):
                        path = path[0] if path else ""
                    path = str(path).strip() if path else ""
                    if path:
                        target_node = hou.node(path)
                        if target_node is not None:
                            return target_node
            except Exception:
                pass
            return node
        
        for node in selected_nodes:
            # Get target node (from target_asset parameter if available, otherwise use node itself)
            target_node = _get_target_node_or_self(node)
            node_updated = False
            
            # Set p_* parameters (except task parameters) and clear task parameters
            try:
                # p_project (from asset.parent.project) - set on target_node
                parm = target_node.parm('p_project')
                if parm:
                    if asset_project_name:
                        parm.set(asset_project_name)
                    else:
                        parm.set("")  # Clear if not available
                    node_updated = True
                
                # p_parent (from asset.parent) - set on target_node
                parm = target_node.parm('p_parent')
                if parm:
                    if asset_parent_name:
                        parm.set(asset_parent_name)
                    else:
                        parm.set("")  # Clear if not available
                    node_updated = True
                
                # p_asset_id - set on target_node
                parm = target_node.parm('p_asset_id')
                if parm:
                    parm.set(asset_id)
                    node_updated = True
                
                # p_asset_name - set on target_node
                parm = target_node.parm('p_asset_name')
                if parm:
                    parm.set(asset_name)
                    node_updated = True
                
                # p_asset_type - set on target_node
                parm = target_node.parm('p_asset_type')
                if parm:
                    if asset_type:
                        parm.set(asset_type)
                    else:
                        parm.set("")  # Clear if not available
                    node_updated = True
                
                # Clear all task-related parameters on target_node
                task_param_names = ['p_task_id', 'task_project', 'task_parent', 'task_name']
                for task_parm_name in task_param_names:
                    parm = target_node.parm(task_parm_name)
                    if parm:
                        try:
                            parm.set("")
                            node_updated = True
                        except Exception:
                            pass
                
                # components (count) - set on target_node
                parm = target_node.parm('components')
                if parm:
                    parm.set(components_count)
                    node_updated = True
                
                # comp_name and file_path (if components >= 1)
                # Publish HDA uses indexed parameters: comp_name1, comp_name2, ..., file_path1, file_path2, ...
                # Set on target_node
                if components_count >= 1:
                    for idx in range(components_count):
                        comp_idx = idx + 1  # Parameters are 1-indexed
                        
                        # comp_name{idx}
                        comp_name_parm = target_node.parm(f'comp_name{comp_idx}')
                        if comp_name_parm and idx < len(comp_names):
                            try:
                                comp_name_parm.set(comp_names[idx])
                                node_updated = True
                            except Exception as exc:
                                _log.warning("Could not set comp_name%d on %s: %s", comp_idx, target_node.path(), exc)
                        
                        # file_path{idx}
                        file_path_parm = target_node.parm(f'file_path{comp_idx}')
                        if file_path_parm and idx < len(file_paths):
                            try:
                                file_path_parm.set(file_paths[idx])
                                node_updated = True
                            except Exception as exc:
                                _log.warning("Could not set file_path%d on %s: %s", comp_idx, target_node.path(), exc)
                
            except Exception as exc:
                _log.warning("Error setting parameters on %s: %s", node.path(), exc)
            
            if node_updated:
                success_count += 1
                if target_node != node:
                    _log.info(
                        "Set full params on target node %s (from %s): p_asset_id=%s, p_asset_name=%s, components=%d",
                        target_node.path(),
                        node.path(),
                        asset_id,
                        asset_name,
                        components_count,
                    )
                else:
                    _log.info(
                        "Set full params on node %s: p_asset_id=%s, p_asset_name=%s, components=%d",
                        node.path(),
                        asset_id,
                        asset_name,
                        components_count,
                    )
            else:
                nodes_without_parms += 1
        
        return success_count, nodes_without_parms
        
    except Exception as exc:
        _log.error("Failed to set full params: %s", exc, exc_info=True)
        return 0, 0


def load_snapshot_hip(path: str) -> bool:
    """Load .hip snapshot in Houdini, preserving original scene file name.

    Returns True on success, False if loading is not possible.
    In non-Houdini environment -- always False.
    """
    if not HOUDINI_AVAILABLE:
        return False

    if not path:
        return False

    try:
        og_file_path = hou.hipFile.path()
        _log.info("Attempting to load snapshot: %s", path)
        hou.hipFile.load(path, suppress_save_prompt=True)
        hou.hipFile.setName(og_file_path)
        _log.info("Snapshot %s loaded.", path)
        return True
    except Exception as exc:  # pragma: no cover
        _log.error("Failed to load snapshot %s: %s", path, exc)
        return False


def apply_scene_setup(scene_setup: Mapping[str, object]) -> None:
    """Apply scene settings (FPS and frame range) from dictionary.

    Expects:
      - scene_setup["fps"]: float | None
      - scene_setup["frame_range"]: {"start": int, "end": int} | None
    In non-Houdini environment -- no-op.
    """
    if not HOUDINI_AVAILABLE:
        return

    try:
        fps_val = scene_setup.get("fps")  # type: ignore[assignment]
        if fps_val not in (None, "", [], {}):
            try:
                fps_f = float(fps_val)  # type: ignore[arg-type]
                if fps_f > 0:
                    hou.setFps(fps_f)
                    _log.info("Scene Setup: set FPS to %s", fps_f)
            except Exception as exc:
                _log.warning("Scene Setup: failed to parse/set FPS %r: %s", fps_val, exc)
    except Exception as exc:
        _log.warning("Scene Setup: unexpected error while configuring FPS: %s", exc)

    try:
        frame_range = scene_setup.get("frame_range") or {}  # type: ignore[assignment]
        start = getattr(frame_range, "get", lambda *_: None)("start")
        end = getattr(frame_range, "get", lambda *_: None)("end")

        if start not in (None, "", [], {}) and end not in (None, "", [], {}):
            start_i = int(round(float(start)))  # type: ignore[arg-type]
            end_i = int(round(float(end)))      # type: ignore[arg-type]
            try:
                hou.playbar.setFrameRange(start_i, end_i)
                hou.playbar.setPlaybackRange(start_i, end_i)
                _log.info("Scene Setup: set frame range to %s-%s", start_i, end_i)
            except Exception as exc:
                _log.warning("Scene Setup: failed to set frame range: %s", exc)
    except Exception as exc:
        _log.warning("Scene Setup: unexpected error while configuring frame range: %s", exc)


class HoudiniUserTasksHandlers:
    """DCC handlers for UserTasksWidget in Houdini.

    When creating scene from UserTasksWidget, executes same scenario as
    Scene Setup button in main browser:
    - sets task context (FTRACK_CONTEXTID / FTRACK_TASK);
    - if possible, configures FPS and frame range from shot data;
    - saves .hip file to provided scene_path;
    - closes widget window.
    """

    def create_task_scene(
        self,
        widget: Any,
        task_data: Dict[str, Any],
        dir_path,
        scene_path,
    ) -> None:
        if not HOUDINI_AVAILABLE:
            return

        task_id = str(task_data.get("id") or "")
        if not task_id:
            return

        task_name = task_data.get("name") or ""
        project_name = task_data.get("project_name") or ""
        parent_full = task_data.get("parent_full_name") or ""
        parent_name = parent_full.split(".")[-1] if parent_full else ""

        # 1) Set task context in Houdini (global scene variables).
        try:
            task_label = f"project: {project_name}   parent: {parent_name}   task: {task_name}"
            set_global_task_vars(task_id, task_label)
            _log.info(
                "HoudiniUserTasksHandlers: set global task vars for %s (%s)",
                task_id,
                task_label,
            )
        except Exception as exc:
            _log.warning("HoudiniUserTasksHandlers: failed to set global task vars: %s", exc)

        # 2) Try to repeat Scene Setup (FPS/frames) via SimpleFtrackApiClient.
        api = getattr(widget, "api", None)
        session = None
        if api is not None:
            session = getattr(api, "session", None)
            if session is None and hasattr(api, "get_session"):
                try:
                    session = api.get_session()
                except Exception:
                    session = None

        shot_info: Dict[str, Any] = {}
        frame_range = None
        fps_f = None
        shot_id = None

        if session is not None and api is not None:
            try:
                entity = session.get("Task", task_id)
            except Exception:
                entity = None
            if not entity:
                try:
                    entity = session.get("TypedContext", task_id)
                except Exception:
                    entity = None

            if entity:
                parent = entity.get("parent")
                if parent and parent.get("id"):
                    shot_id = parent.get("id")
                    parent_name = parent.get("name", "") or parent_name

                if shot_id:
                    try:
                        shot_info = api.get_shot_custom_attributes_on_demand(shot_id)
                    except Exception as exc:
                        _log.warning(
                            "HoudiniUserTasksHandlers: failed to fetch shot info for %s: %s",
                            shot_id,
                            exc,
                        )

        # Parse FPS and frame range same as in browser.
        if shot_info:
            try:
                fps_val = shot_info.get("fps")
                if fps_val not in (None, "", [], {}):
                    try:
                        fps_f = float(fps_val)
                        if fps_f <= 0:
                            fps_f = None
                    except Exception:
                        fps_f = None
            except Exception:
                fps_f = None

            try:
                fstart = shot_info.get("fstart")
                fend = shot_info.get("fend")
                if fstart not in (None, "", [], {}) and fend not in (None, "", [], {}):
                    fstart_i = int(round(float(fstart)))
                    fend_i = int(round(float(fend)))
                    handles = shot_info.get("handles", 0) or 0
                    preroll = shot_info.get("preroll", 0) or 0
                    try:
                        handles_i = int(round(float(handles)))
                    except Exception:
                        handles_i = 0
                    try:
                        preroll_i = int(round(float(preroll)))
                    except Exception:
                        preroll_i = 0

                    start = fstart_i - handles_i - preroll_i
                    end = fend_i + handles_i
                    frame_range = {"start": start, "end": end}
            except Exception as exc:
                _log.warning(
                    "HoudiniUserTasksHandlers: failed to calculate frame range from shot info: %s",
                    exc,
                )

        workdir = os.environ.get("FTRACK_WORKDIR", "")

        scene_setup = {
            "task_id": task_id,
            "task_name": task_name,
            "project_name": project_name,
            "parent_name": parent_name,
            "shot_id": shot_id,
            "shot_name": parent_name,
            "shot_info": shot_info,
            "fps": fps_f,
            "frame_range": frame_range,
            "workdir": workdir,
            # Use path already built by UserTasksWidget.
            "suggested_scene_name": os.path.basename(str(scene_path)),
            "suggested_scene_path": str(scene_path),
        }

        try:
            apply_scene_setup(scene_setup)
        except Exception as exc:
            _log.warning("HoudiniUserTasksHandlers: apply_scene_setup failed: %s", exc)

        # 3) Save .hip to specified path.
        try:
            hou.hipFile.save(str(scene_path))
            _log.info("HoudiniUserTasksHandlers: saved hip file to %s", scene_path)
        except Exception as exc:
            _log.error(
                "HoudiniUserTasksHandlers: failed to save hip file to %s: %s",
                scene_path,
                exc,
            )
            return

        # 4) Close widget window (usually QDialog containing it).
        try:
            win = widget.window()
            if win is not None:
                win.close()
        except Exception as exc:
            _log.warning("HoudiniUserTasksHandlers: failed to close widget window after create_task_scene: %s", exc)

    def open_scene(
        self,
        widget: Any,
        path: str,
        task_data: Dict[str, Any],
    ) -> None:
        """Open specified .hip in Houdini and close widget window.

        Intended for Open Scene button in UserTasksWidget when it's running
        inside Houdini.
        """
        if not HOUDINI_AVAILABLE:
            return

        if not path:
            return

        try:
            _log.info("HoudiniUserTasksHandlers: loading scene %s", path)
            hou.hipFile.load(path, suppress_save_prompt=True)
        except Exception as exc:
            _log.error("HoudiniUserTasksHandlers: failed to load scene %s: %s", path, exc)
            return

        # Close widget window after successful load.
        try:
            win = widget.window()
            if win is not None:
                win.close()
        except Exception as exc:
            _log.warning("HoudiniUserTasksHandlers: failed to close widget window after open_scene: %s", exc)
