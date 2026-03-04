from __future__ import annotations

"""ftrack Action: Open User Tasks (Houdini).

This action appears on Task selection and launches the standalone
User Tasks widget for the current user, focused on the selected task.

It is designed to run inside the environment prepared by ftrack Connect,
so all FTRACK_* variables and mroya-specific configuration (MROOT, etc.)
are already available. The action itself passes the Task id explicitly
via CLI argument: --task-id=<id>.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import ftrack_api  # type: ignore


logger = logging.getLogger(__name__ + ".OpenUserTasksHoudiniAction")


class OpenUserTasksHoudiniAction(object):
    """Action that opens standalone User Tasks UI for a selected Task."""

    label = "Open User Tasks (Houdini)"
    identifier = "mroya.open_user_tasks_houdini"
    description = "Open Mroya User Tasks focused on this Task (Houdini workflow)."

    def __init__(self, session: ftrack_api.Session) -> None:  # type: ignore[name-defined]
        super().__init__()
        self.session = session
        self.logger = logger

    # ------------------------------------------------------------------ Registration

    def register(self) -> None:
        """Register discover and launch listeners for this action."""
        self.session.event_hub.subscribe(
            "topic=ftrack.action.discover and source.user.username={0}".format(
                self.session.api_user
            ),
            self.discover,
        )
        self.session.event_hub.subscribe(
            "topic=ftrack.action.launch and data.actionIdentifier={0} and "
            "source.user.username={1}".format(self.identifier, self.session.api_user),
            self.launch,
        )

    # ------------------------------------------------------------------ Helpers

    @staticmethod
    def _is_task_selection(selection: List[Dict[str, Any]]) -> bool:
        """Return True if selection contains exactly one Task."""
        if len(selection) != 1:
            return False
        entity = selection[0]
        entity_type = (entity.get("entityType") or "").lower()
        return entity_type == "task"


    # ------------------------------------------------------------------ Event handlers

    def discover(self, event: Dict[str, Any]) -> Dict[str, Any] | None:
        """Return action config if triggered on a single Task."""
        data = event.get("data", {}) or {}
        selection = data.get("selection") or []
        self.logger.debug("discover: selection=%r", selection)

        if not self._is_task_selection(selection):
            return None

        return {
            "items": [
                {
                    "label": self.label,
                    "description": self.description,
                    "actionIdentifier": self.identifier,
                }
            ]
        }

    def launch(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Launch standalone User Tasks focused on selected Task."""
        data = event.get("data", {}) or {}
        selection = data.get("selection") or []
        self.logger.info("launch: selection=%r", selection)

        if not self._is_task_selection(selection):
            return {
                "success": False,
                "message": "Please select exactly one Task to open User Tasks.",
            }

        task_entity = selection[0]
        task_id = task_entity.get("entityId")
        if not task_id:
            return {
                "success": False,
                "message": "Selected Task has no id; cannot open User Tasks.",
            }

        # Build command to run User Tasks via in-plugin launcher. Use current
        # Python executable so that environment from ftrack Connect is preserved.
        python_exe = sys.executable or "python"
        cmd = [
            python_exe,
            "-m",
            "ftrack_inout.browser.run_user_tasks_launcher",
            "--dcc",
            "houdini",
            "--task-id",
            str(task_id),
        ]

        self.logger.info("Launching User Tasks via command: %r", cmd)

        try:
            # Launch detached process, do not wait for completion.
            subprocess.Popen(cmd, env=os.environ.copy())
        except Exception as exc:
            self.logger.error("Failed to launch User Tasks: %s", exc, exc_info=True)
            return {
                "success": False,
                "message": f"Failed to launch User Tasks: {exc}",
            }

        return {
            "success": True,
            "message": "User Tasks (Houdini) launched in a separate window.",
        }


def register(session: Any, **kw: Any) -> None:
    """Register action plugin with ftrack."""
    if not isinstance(session, ftrack_api.Session):
        return

    action = OpenUserTasksHoudiniAction(session)
    action.register()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _session = ftrack_api.Session()
    register(_session)
    _session.event_hub.wait()

