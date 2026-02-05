"""
Maya-specific helpers for ftrack_inout.browser.

Here we concentrate all `maya.cmds` imports and Maya API work so
main browser code remains DCC-agnostic.

Implemented:
- safe maya.cmds import (MAYA_AVAILABLE = False outside Maya);
- set_global_task_vars: set FTRACK_CONTEXTID / FTRACK_TASK;
- apply_scene_setup: basic FPS + frame range from shot data;
- MayaUserTasksHandlers: UserTasksWidget button handlers
  (Create Task Scene / Open Scene) with behavior similar to Houdini;
- open_ftrack_input_window: Ftrack Input (finput-like) window for Maya;
- create_input_node: create mroya_input locator with component attributes (from maya_input_window).
"""

from __future__ import annotations

from typing import Mapping, Any, Dict, Sequence
import logging
import os
import os.path

try:  # pragma: no cover - depends on DCC environment
    import maya.cmds as cmds  # type: ignore
    MAYA_AVAILABLE: bool = True
except Exception:  # pragma: no cover - non-Maya environment
    cmds = None  # type: ignore
    MAYA_AVAILABLE = False

__all__ = [
    "cmds",
    "MAYA_AVAILABLE",
    "set_global_task_vars",
    "apply_scene_setup",
    "MayaUserTasksHandlers",
    "open_ftrack_input_window",
    "create_input_node",
    "set_hda_params_on_selected_nodes",
    "set_full_params_on_publish_nodes",
]

try:
    from .maya_input_window import open_ftrack_input_window, create_input_node
except ImportError:
    open_ftrack_input_window = None  # type: ignore[misc, assignment]
    create_input_node = None  # type: ignore[misc, assignment]

_log = logging.getLogger(__name__)


def set_hda_params_on_selected_nodes(
    asset_version_id: str | None,
    component_name: str | None,
    component_id: str | None,
    asset_id: str | None,
    asset_name: str | None,
    asset_type: str | None,
    hda_param_config: Mapping[str, Sequence[str]],
) -> tuple[int, int]:
    """Maya stub: set params on selected nodes from browser selection.

    Receives selected element params (e.g. component_id when component selected,
    asset_version_id / asset_id / asset_name / asset_type when version or asset selected).
    Returns (success_count, nodes_without_parms). Stub returns (0, 0) and logs params.
    """
    _log.info(
        "[Maya Set Full Params] stub called with: asset_version_id=%s, component_name=%s, "
        "component_id=%s, asset_id=%s, asset_name=%s, asset_type=%s",
        asset_version_id,
        component_name,
        component_id,
        asset_id,
        asset_name,
        asset_type,
    )
    return 0, 0


def set_full_params_on_publish_nodes(
    session: Any,
    asset_id: str,
    asset_name: str,
    asset_type: str,
) -> tuple[int, int]:
    """Maya stub: no-op (publish-node logic is Houdini-specific). Returns (0, 0)."""
    _log.debug(
        "[Maya set_full_params_on_publish_nodes] stub: asset_id=%s, asset_name=%s, asset_type=%s",
        asset_id,
        asset_name,
        asset_type,
    )
    return 0, 0


def set_global_task_vars(task_id: str, task_label: str) -> None:
    """Set global variables/scene settings for current Ftrack task.

    - Always sets os.environ["FTRACK_CONTEXTID"] / ["FTRACK_TASK"].
    - In Maya additionally writes these values to optionVar.
    """
    try:
        os.environ["FTRACK_CONTEXTID"] = str(task_id)
        os.environ["FTRACK_TASK"] = str(task_label)
    except Exception as exc:  # pragma: no cover
        _log.warning("Maya DCC: failed to set env vars for task %s: %s", task_id, exc)

    if not MAYA_AVAILABLE:
        return

    try:
        cmds.optionVar(sv=("FTRACK_CONTEXTID", str(task_id)))  # type: ignore[arg-type]
        cmds.optionVar(sv=("FTRACK_TASK", str(task_label)))  # type: ignore[arg-type]
        _log.info(
            "Maya DCC: set FTRACK_CONTEXTID=%s, FTRACK_TASK=%s in optionVar",
            task_id,
            task_label,
        )
    except Exception as exc:  # pragma: no cover
        _log.warning("Maya DCC: failed to set optionVars for task %s: %s", task_id, exc)


def _fps_to_unit(fps: float) -> str:
    """Convert FPS to Maya time-unit."""
    rounded = int(round(fps))
    if rounded == 24:
        return "film"
    if rounded == 25:
        return "pal"
    if rounded == 30:
        return "ntsc"
    return f"{rounded}fps"


def apply_scene_setup(scene_setup: Mapping[str, object]) -> None:
    """Apply FPS and frame range in Maya.

    scene_setup:
      - "fps": float | str | None
      - "frame_range": {"start": int/float/str, "end": int/float/str} | None
    """
    if not MAYA_AVAILABLE:
        return

    # FPS
    try:
        fps_val = scene_setup.get("fps")  # type: ignore[assignment]
        if fps_val not in (None, "", [], {}):
            try:
                fps_f = float(fps_val)  # type: ignore[arg-type]
                if fps_f > 0:
                    unit = _fps_to_unit(fps_f)
                    cmds.currentUnit(time=unit)  # type: ignore[arg-type]
                    _log.info("Maya DCC: set FPS to %s (unit=%s)", fps_f, unit)
            except Exception as exc:
                _log.warning("Maya DCC: failed to parse/set FPS %r: %s", fps_val, exc)
    except Exception as exc:  # pragma: no cover
        _log.warning("Maya DCC: unexpected error while configuring FPS: %s", exc)

    # Frame range
    try:
        frame_range = scene_setup.get("frame_range") or {}  # type: ignore[assignment]
        start = getattr(frame_range, "get", lambda *_: None)("start")
        end = getattr(frame_range, "get", lambda *_: None)("end")

        if start not in (None, "", [], {}) and end not in (None, "", [], {}):
            start_i = int(round(float(start)))  # type: ignore[arg-type]
            end_i = int(round(float(end)))  # type: ignore[arg-type]
            try:
                cmds.playbackOptions(
                    min=start_i,
                    max=end_i,
                    animationStartTime=start_i,
                    animationEndTime=end_i,
                )
                _log.info("Maya DCC: set frame range to %s-%s", start_i, end_i)
            except Exception as exc:
                _log.warning("Maya DCC: failed to set frame range: %s", exc)
    except Exception as exc:  # pragma: no cover
        _log.warning("Maya DCC: unexpected error while configuring frame range: %s", exc)


class MayaUserTasksHandlers:
    """DCC handlers for UserTasksWidget in Maya.

    Behavior similar to Houdini:
    - Create Task Scene: sets up context, FPS/frame and saves scene to scene_path,
      then closes window;
    - Open Scene: opens file and closes window.
    """

    def create_task_scene(
        self,
        widget: Any,
        task_data: Dict[str, Any],
        dir_path,
        scene_path,
    ) -> None:
        if not MAYA_AVAILABLE:
            return

        task_id = str(task_data.get("id") or "")
        if not task_id:
            return

        task_name = task_data.get("name") or ""
        project_name = task_data.get("project_name") or ""
        parent_full = task_data.get("parent_full_name") or ""
        parent_name = parent_full.split(".")[-1] if parent_full else ""

        # 1) Task context
        try:
            task_label = (
                f"project: {project_name}   parent: {parent_name}   task: {task_name}"
            )
            set_global_task_vars(task_id, task_label)
            _log.info(
                "MayaUserTasksHandlers: set global task vars for %s (%s)",
                task_id,
                task_label,
            )
        except Exception as exc:
            _log.warning(
                "MayaUserTasksHandlers: failed to set global task vars: %s", exc
            )

        # 2) Scene Setup as in Houdini handler
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
                            "MayaUserTasksHandlers: failed to fetch shot info for %s: %s",
                            shot_id,
                            exc,
                        )

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
                if fstart not in (None, "", [], {}) and fend not in (
                    None,
                    "",
                    [],
                    {},
                ):
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
                    "MayaUserTasksHandlers: failed to calculate frame range from shot info: %s",
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
            "suggested_scene_name": os.path.basename(str(scene_path)),
            "suggested_scene_path": str(scene_path),
        }

        try:
            apply_scene_setup(scene_setup)
        except Exception as exc:
            _log.warning("MayaUserTasksHandlers: apply_scene_setup failed: %s", exc)

        # 3) Save Maya scene
        try:
            scene_path_str = str(scene_path)
            ext = os.path.splitext(scene_path_str)[1].lower()
            cmds.file(rename=scene_path_str)  # type: ignore[arg-type]
            if ext == ".ma":
                cmds.file(save=True, type="mayaAscii")  # type: ignore[arg-type]
            else:
                cmds.file(save=True, type="mayaBinary")  # type: ignore[arg-type]
            _log.info("MayaUserTasksHandlers: saved scene to %s", scene_path_str)
        except Exception as exc:
            _log.error(
                "MayaUserTasksHandlers: failed to save scene to %s: %s",
                scene_path,
                exc,
            )
            return

        # 4) Close UserTasksWidget window
        try:
            win = widget.window()
            if win is not None:
                win.close()
        except Exception as exc:
            _log.warning(
                "MayaUserTasksHandlers: failed to close widget window after create_task_scene: %s",
                exc,
            )

    def open_scene(
        self,
        widget: Any,
        path: str,
        task_data: Dict[str, Any],
    ) -> None:
        """Open Maya scene and close widget window (similar to Houdini open_scene)."""
        if not MAYA_AVAILABLE:
            return
        if not path:
            return

        try:
            _log.info("MayaUserTasksHandlers: loading scene %s", path)
            cmds.file(path, open=True, force=True)  # type: ignore[arg-type]
        except Exception as exc:
            _log.error(
                "MayaUserTasksHandlers: failed to load scene %s: %s",
                path,
                exc,
            )
            return

        try:
            win = widget.window()
            if win is not None:
                win.close()
        except Exception as exc:
            _log.warning(
                "MayaUserTasksHandlers: failed to close widget window after open_scene: %s",
                exc,
            )