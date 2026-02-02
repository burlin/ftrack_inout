"""
Blender-specific helpers for ftrack_inout.browser.

Similar to dcc.houdini layer: here we concentrate all `bpy` imports and
Blender API work so main browser code remains DCC-agnostic.

Currently this adapter:
- safely imports bpy (BLENDER_AVAILABLE = False if Blender unavailable);
- provides functions with interface consistent with Houdini layer where
  it makes sense (set_global_task_vars, apply_scene_setup, etc.);
- in standalone browser environment (without bpy) behaves as no-op.
"""

from __future__ import annotations

from typing import Mapping
import logging
import os

try:  # pragma: no cover - depends on Blender environment
    import bpy  # type: ignore

    BLENDER_AVAILABLE: bool = True
except Exception:  # ImportError, RuntimeError in non-Blender environment
    bpy = None  # type: ignore
    BLENDER_AVAILABLE = False

__all__ = [
    "bpy",
    "BLENDER_AVAILABLE",
    "set_global_task_vars",
    "apply_scene_setup",
]

_log = logging.getLogger(__name__)


def set_global_task_vars(task_id: str, task_label: str) -> None:
    """Set global variables/scene properties for current Ftrack task.

    Behavior:
    - in any environment sets os.environ["FTRACK_CONTEXTID"] / ["FTRACK_TASK"];
    - if Blender available, additionally saves these values on scene:
      scene["FTRACK_CONTEXTID"], scene["FTRACK_TASK"].
    In environment without Blender -- just changes environment variables.
    """
    # Always update process env variables.
    try:
        os.environ["FTRACK_CONTEXTID"] = str(task_id)
        os.environ["FTRACK_TASK"] = str(task_label)
    except Exception as exc:  # pragma: no cover
        _log.warning("Blender DCC: failed to set env vars for task %s: %s", task_id, exc)

    if not BLENDER_AVAILABLE:
        return

    try:
        scene = bpy.context.scene  # type: ignore[union-attr]
        if scene is None:
            return
        scene["FTRACK_CONTEXTID"] = str(task_id)
        scene["FTRACK_TASK"] = str(task_label)
        _log.info(
            "Blender DCC: set FTRACK_CONTEXTID=%s, FTRACK_TASK=%s on scene %s",
            task_id,
            task_label,
            getattr(scene, "name", "<unnamed>"),
        )
    except Exception as exc:  # pragma: no cover
        _log.warning("Blender DCC: failed to set scene properties for task %s: %s", task_id, exc)


def apply_scene_setup(scene_setup: Mapping[str, object]) -> None:
    """Apply basic scene settings (FPS and frame range) in Blender.

    Expects dictionary in same format as Houdini adapter:
      - scene_setup["fps"]: float | str | None
      - scene_setup["frame_range"]: {"start": int/float/str, "end": int/float/str} | None

    In environment without Blender -- no-op.
    """
    if not BLENDER_AVAILABLE:
        return

    try:
        scene = bpy.context.scene  # type: ignore[union-attr]
        if scene is None:
            return
    except Exception as exc:  # pragma: no cover
        _log.warning("Blender DCC: cannot access current scene: %s", exc)
        return

    # FPS
    try:
        fps_val = scene_setup.get("fps")  # type: ignore[assignment]
        if fps_val not in (None, "", [], {}):
            try:
                fps_f = float(fps_val)  # type: ignore[arg-type]
                if fps_f > 0:
                    scene.render.fps = int(round(fps_f))
                    _log.info("Blender DCC: set FPS to %s", fps_f)
            except Exception as exc:
                _log.warning(
                    "Blender DCC: failed to parse/set FPS %r: %s", fps_val, exc
                )
    except Exception as exc:  # pragma: no cover
        _log.warning("Blender DCC: unexpected error while configuring FPS: %s", exc)

    # Frame range
    try:
        frame_range = scene_setup.get("frame_range") or {}  # type: ignore[assignment]
        start = getattr(frame_range, "get", lambda *_: None)("start")
        end = getattr(frame_range, "get", lambda *_: None)("end")

        if start not in (None, "", [], {}) and end not in (None, "", [], {}):
            start_i = int(round(float(start)))  # type: ignore[arg-type]
            end_i = int(round(float(end)))  # type: ignore[arg-type]
            try:
                scene.frame_start = start_i
                scene.frame_end = end_i
                _log.info(
                    "Blender DCC: set frame range to %s-%s on scene %s",
                    start_i,
                    end_i,
                    getattr(scene, "name", "<unnamed>"),
                )
            except Exception as exc:
                _log.warning("Blender DCC: failed to set frame range: %s", exc)
    except Exception as exc:  # pragma: no cover
        _log.warning(
            "Blender DCC: unexpected error while configuring frame range: %s", exc
        )


