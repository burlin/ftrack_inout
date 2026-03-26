from __future__ import annotations

"""Launcher for the User Tasks Qt widget as part of the ftrack_inout plugin.

This module contains the actual startup logic for the UserTasksWidget:
- shared ftrack session via common.session_factory.get_shared_session;
- SimpleFtrackApiClient with shared session;
- Qt application and top-level window.

It is designed to be used both:
- from ftrack Connect actions (Houdini, etc.), where environment is already prepared;
- from external wrappers (e.g. tools/run_user_tasks.py) that only handle
  environment bootstrap and then call this module.

UI features (implemented in ``UserTasksWidget``) include shot-level linked tasks
(same as ftrack web Links via ``Task.incoming_links`` / ``outgoing_links`` per
Developer Hub), ``use_this_list`` per linked task, and transfer-to-local for
selected components.
"""

import sys
from typing import Optional, Sequence, Tuple


def _parse_cli_args(argv: Sequence[str]) -> Tuple[Optional[str], Optional[str]]:
    """Parse minimal CLI arguments for User Tasks launcher.

    Supported options:
    --task-id=<id> or --task-id <id>  : initial Task id to focus on.
    --dcc=<name> or --dcc <name>      : optional DCC identifier (e.g. houdini, maya).

    Returns (task_id, dcc).
    """
    task_id: Optional[str] = None
    dcc: Optional[str] = None

    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg.startswith("--task-id="):
            value = arg.split("=", 1)[1].strip()
            if value:
                task_id = value
            i += 1
            continue
        if arg == "--task-id" and i + 1 < len(argv):
            value = argv[i + 1].strip()
            if value:
                task_id = value
            i += 2
            continue
        if arg.startswith("--dcc="):
            value = arg.split("=", 1)[1].strip()
            if value:
                dcc = value
            i += 1
            continue
        if arg == "--dcc" and i + 1 < len(argv):
            value = argv[i + 1].strip()
            if value:
                dcc = value
            i += 2
            continue
        # Unknown or positional argument: skip for now.
        i += 1

    return task_id, dcc


def run_user_tasks(task_id: Optional[str] = None, dcc: Optional[str] = None) -> int:
    """Create Qt application and show UserTasksWidget.

    Returns exit code (0 on success, non-zero on error).
    """
    try:
        from PySide6 import QtWidgets  # type: ignore
    except Exception as exc:  # pragma: no cover
        print(f"[run_user_tasks_launcher] Failed to import PySide6: {exc}")
        return 1

    try:
        from ftrack_inout.common.session_factory import get_shared_session
        from ftrack_inout.browser.simple_api_client import SimpleFtrackApiClient
        from ftrack_inout.browser.user_tasks_widget import UserTasksWidget
    except Exception as exc:
        print(f"[run_user_tasks_launcher] Failed to import ftrack_inout modules: {exc}")
        return 1

    # Use shared session (same cache as browser, Houdini, Maya).
    session = get_shared_session()
    if not session:
        print(
            "[run_user_tasks_launcher] ERROR: Could not create Ftrack session. "
            "Check FTRACK_* environment variables."
        )
        return 1

    # API client with shared session - uses same cache, no duplicate session.
    api_client = SimpleFtrackApiClient(session=session)

    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication(sys.argv)

    # Pass initial_task_id so UserTasksWidget does not need to rely only on
    # FTRACK_CONTEXTID when launched from actions or external tools.
    widget = UserTasksWidget(api_client=api_client, initial_task_id=task_id)
    widget.setWindowTitle("User Tasks - Mroya")
    widget.resize(900, 600)
    widget.show()

    if not getattr(app, "_is_running_event_loop", False):
        app._is_running_event_loop = True  # type: ignore[attr-defined]
        return app.exec()

    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point.

    Parses arguments and runs User Tasks. Intended for:
    - direct use: ``python -m ftrack_inout.browser.run_user_tasks_launcher ...``
    - ftrack Connect actions that spawn a new process.
    """
    if argv is None:
        argv = sys.argv[1:]
    task_id, dcc = _parse_cli_args(list(argv))
    # Currently *dcc* is not used directly; kept for future per-DCC handlers.
    return run_user_tasks(task_id=task_id, dcc=dcc)


if __name__ == "__main__":
    raise SystemExit(main())

