"""
Qt widget for listing tasks of the current user.

DCC-independent widget that can be used:
- as part of Task Hub;
- as a separate tab/panel in DCC;
- within a standalone application.

Shows tasks assigned to the current ftrack user (`session.api_user`),
and allows filtering them by project.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol
from collections.abc import Mapping

try:
    from PySide6 import QtWidgets, QtCore, QtGui  # type: ignore
except Exception:  # pragma: no cover - for environments without Qt
    QtWidgets = None  # type: ignore
    QtCore = None  # type: ignore
    QtGui = None  # type: ignore

from .simple_api_client import SimpleFtrackApiClient  # type: ignore


logger = logging.getLogger(__name__)


class UserTasksDccHandlers(Protocol):
    """Interface for DCC handlers for UserTasksWidget.

    Implementation in DCC layer (e.g., browser.dcc.houdini) can:
    - create/save scene in DCC;
    - apply Scene Setup (fps, frames);
    - close widget/dialog on completion.
    """

    def create_task_scene(
        self,
        widget: "UserTasksWidget",
        task_data: Dict[str, Any],
        dir_path: Path,
        scene_path: Path,
    ) -> None: ...

    def open_scene(
        self,
        widget: "UserTasksWidget",
        path: str,
        task_data: Dict[str, Any],
    ) -> None: ...


class UserTasksWidget(QtWidgets.QWidget):  # type: ignore[misc]
    """Simple browser for tasks assigned to the current user."""

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,  # type: ignore[name-defined]
        api_client: Optional[SimpleFtrackApiClient] = None,
        dcc_handlers: Optional[UserTasksDccHandlers] = None,
    ) -> None:
        if QtWidgets is None:  # pragma: no cover - defensive path
            raise RuntimeError("PySide6 is not available; UserTasksWidget cannot be created.")

        super().__init__(parent)

        self.api = api_client or SimpleFtrackApiClient()
        # simple_api_client provides get_session(), browser_widget.FtrackApiClient does not.
        self.session = getattr(self.api, "get_session", lambda: getattr(self.api, "session", None))()

        self._all_tasks: List[Dict[str, Any]] = []
        self._active_projects: Dict[str, str] = {}
        self._current_project_id: Optional[str] = None
        self._api_user: Optional[str] = None
        # Initial task from DCC context (e.g., FTRACK_CONTEXTID),
        # to focus on it when launching from a scene.
        self._initial_task_id: Optional[str] = os.environ.get("FTRACK_CONTEXTID") or None
        # Root of project working directory, used for building paths
        # to scenes for tasks.
        self._workdir_root = os.environ.get("FTRACK_WORKDIR") or None
        self._settings = QtCore.QSettings("mroya", "TaskHubUserTasks") if QtCore is not None else None  # type: ignore[call-arg]
        # DCC handlers (Houdini/Blender/Maya) for actions like scene creation.
        self._dcc_handlers: Optional[UserTasksDccHandlers] = dcc_handlers

        # Lazy initialization of target locations list for linked component transfer.
        self._transfer_locations_initialized: bool = False

        self._build_ui()
        self._load_tasks()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)

        # Toolbar: Project filter + refresh
        toolbar = QtWidgets.QHBoxLayout()

        project_label = QtWidgets.QLabel("Project:", self)
        toolbar.addWidget(project_label)

        self.project_combo = QtWidgets.QComboBox(self)
        self.project_combo.setMinimumWidth(200)
        self.project_combo.currentIndexChanged.connect(self._on_project_changed)
        toolbar.addWidget(self.project_combo)

        refresh_btn = QtWidgets.QPushButton("Refresh", self)
        refresh_btn.clicked.connect(self._load_tasks)
        toolbar.addWidget(refresh_btn)

        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        # Splitter: left = tasks tree + task actions, middle = files/snapshots, right = linked components
        splitter = QtWidgets.QSplitter(self)

        # Left pane: tasks tree + task action buttons
        left_widget = QtWidgets.QWidget(splitter)
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        self.task_tree = QtWidgets.QTreeWidget(left_widget)
        self.task_tree.setColumnCount(4)
        self.task_tree.setHeaderLabels(
            ["Name", "Project / Context", "Status", "Info"]
        )
        # Enable tree decoration to show hierarchy as in main browser.
        self.task_tree.setRootIsDecorated(True)
        self.task_tree.setAlternatingRowColors(True)
        self.task_tree.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        left_layout.addWidget(self.task_tree, 1)

        task_btn_bar = QtWidgets.QHBoxLayout()
        task_btn_bar.addStretch(1)
        self.create_scene_btn = QtWidgets.QPushButton("Create Task Scene", left_widget)
        self.create_scene_btn.clicked.connect(self._on_create_task_scene_clicked)
        self.create_scene_btn.setEnabled(False)
        task_btn_bar.addWidget(self.create_scene_btn)

        self.get_snapshots_btn = QtWidgets.QPushButton("Get Published Snapshots", left_widget)
        self.get_snapshots_btn.clicked.connect(self._on_get_published_snapshots_clicked)
        self.get_snapshots_btn.setEnabled(False)
        task_btn_bar.addWidget(self.get_snapshots_btn)

        left_layout.addLayout(task_btn_bar)

        splitter.addWidget(left_widget)

        # Middle pane: files + published snapshots for selected task
        middle_widget = QtWidgets.QWidget(splitter)
        middle_layout = QtWidgets.QVBoxLayout(middle_widget)
        middle_layout.setContentsMargins(0, 0, 0, 0)
        middle_layout.setSpacing(4)

        files_label = QtWidgets.QLabel("Task files for selected task:", middle_widget)
        middle_layout.addWidget(files_label, 0)

        self.files_tree = QtWidgets.QTreeWidget(middle_widget)
        self.files_tree.setColumnCount(4)
        self.files_tree.setHeaderLabels(
            ["Name", "Size", "Modified", "Path"]
        )
        self.files_tree.setRootIsDecorated(False)
        self.files_tree.setAlternatingRowColors(True)
        self.files_tree.itemSelectionChanged.connect(self._on_file_selection_changed)
        middle_layout.addWidget(self.files_tree, 1)

        # Button to open local scene from task files list
        files_btn_bar = QtWidgets.QHBoxLayout()
        files_btn_bar.addStretch(1)
        self.open_scene_btn = QtWidgets.QPushButton("Open Scene", middle_widget)
        self.open_scene_btn.setEnabled(False)
        self.open_scene_btn.clicked.connect(self._on_open_scene_clicked)
        files_btn_bar.addWidget(self.open_scene_btn)
        middle_layout.addLayout(files_btn_bar)

        snapshots_label = QtWidgets.QLabel("Published snapshots for selected task:", middle_widget)
        middle_layout.addWidget(snapshots_label, 0)

        self.snapshots_tree = QtWidgets.QTreeWidget(middle_widget)
        self.snapshots_tree.setColumnCount(5)
        self.snapshots_tree.setHeaderLabels(
            ["Asset", "Version", "Component / Type", "Path", "Available"]
        )
        self.snapshots_tree.setRootIsDecorated(False)
        self.snapshots_tree.setAlternatingRowColors(True)
        middle_layout.addWidget(self.snapshots_tree, 1)

        snapshots_btn_bar = QtWidgets.QHBoxLayout()
        snapshots_btn_bar.addStretch(1)
        self.copy_snapshot_btn = QtWidgets.QPushButton("Copy to local", middle_widget)
        self.copy_snapshot_btn.clicked.connect(self._on_copy_snapshot_to_local_clicked)
        snapshots_btn_bar.addWidget(self.copy_snapshot_btn)
        # Button to collect linked components now next to Copy to local
        self.collect_linked_btn = QtWidgets.QPushButton("Collect linked", middle_widget)
        self.collect_linked_btn.clicked.connect(self._on_collect_linked_clicked)
        snapshots_btn_bar.addWidget(self.collect_linked_btn)
        middle_layout.addLayout(snapshots_btn_bar)

        splitter.addWidget(middle_widget)

        # Right pane: linked components (ilink) for selected snapshot
        right_widget = QtWidgets.QWidget(splitter)
        right_layout = QtWidgets.QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        linked_label = QtWidgets.QLabel("Linked components (ilink):", right_widget)
        right_layout.addWidget(linked_label, 0)

        self.linked_tree = QtWidgets.QTreeWidget(right_widget)
        # Columns:
        #   Asset, Version, Component, Component.ext, Available, Size, Locations, To transfer
        # (without Path, to avoid confusing user when multiple locations exist).
        self.linked_tree.setColumnCount(8)
        self.linked_tree.setHeaderLabels(
            [
                "Asset",
                "Version",
                "Component",
                "Component.ext",
                "Available",
                "Size",
                "Locations",
                "To transfer",
            ]
        )
        self.linked_tree.setRootIsDecorated(False)
        self.linked_tree.setAlternatingRowColors(True)
        right_layout.addWidget(self.linked_tree, 1)

        # Panel for managing linked component transfer:
        # - transfer launch button (target location is selected automatically).
        linked_btn_bar = QtWidgets.QHBoxLayout()
        linked_btn_bar.addStretch(1)

        self.transfer_linked_btn = QtWidgets.QPushButton("Transfer to local", right_widget)
        self.transfer_linked_btn.clicked.connect(self._on_transfer_linked_to_local_clicked)
        linked_btn_bar.addWidget(self.transfer_linked_btn)

        # Informative label with selected target location name.
        self.transfer_target_info_label = QtWidgets.QLabel("(target: n/a)", right_widget)
        linked_btn_bar.addWidget(self.transfer_target_info_label)

        right_layout.addLayout(linked_btn_bar)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)

        layout.addWidget(splitter, 1)

        # Status label
        self.status_label = QtWidgets.QLabel("Ready", self)
        layout.addWidget(self.status_label)

        # Connect selection
        self.task_tree.itemSelectionChanged.connect(self._on_task_selection_changed)

    # ------------------------------------------------------------------ Data loading

    def _load_tasks(self) -> None:
        """Load tasks assigned to current user and populate UI."""
        t_start = time.perf_counter()
        logger.info("UserTasksWidget: _load_tasks started")

        self.task_tree.clear()
        self.project_combo.blockSignals(True)
        self.project_combo.clear()
        self.project_combo.addItem("All Projects", None)
        self.project_combo.blockSignals(False)

        if not self.session:
            self._set_status("No ftrack session available.")
            logger.warning("UserTasksWidget: no ftrack session.")
            return

        try:
            api_user = getattr(self.session, "api_user", None)
            if not api_user:
                self._set_status("No api_user on ftrack session.")
                logger.warning("UserTasksWidget: session.api_user is not set.")
                return
            self._api_user = api_user

            self._set_status(f"Loading tasks for user {api_user}...")
            logger.info("Loading tasks for current user: %s", api_user)

            # Determine list of "active" projects the same way as
            # main browser does: direct query Project where status is "active".
            allowed_project_ids: set[str] = set()
            t_projects_start = time.perf_counter()
            try:
                active_projects = self.session.query(
                    'Project where status is "active"'
                ).all()
                self._active_projects = {}
                for p in active_projects or []:
                    pid = p.get("id")
                    pname = p.get("name", "") or ""
                    if pid:
                        allowed_project_ids.add(pid)
                        self._active_projects[pid] = pname
                logger.info(
                    "UserTasksWidget: %d active projects detected for filtering",
                    len(allowed_project_ids),
                )
                logger.info(
                    "UserTasksWidget: active projects query+processing took %.3f s",
                    time.perf_counter() - t_projects_start,
                )
            except Exception as proj_exc:
                logger.warning(
                    "UserTasksWidget: could not load active project list for filtering: %s",
                    proj_exc,
                )
                self._active_projects = {}


            # Fill project combo: show all active projects, even if
            # current user has no tasks for them.
            self.project_combo.blockSignals(True)
            self.project_combo.clear()
            self.project_combo.addItem("All Projects", None)
            source_projects = (
                self._active_projects if self._active_projects else
                {t["project_id"]: t["project_name"] for t in self._all_tasks if t.get("project_id")}
            )
            for pid, pname in sorted(source_projects.items(), key=lambda kv: kv[1].lower()):
                self.project_combo.addItem(pname, pid)
            self.project_combo.blockSignals(False)

            # Determine initial filter: last used project or first project in list.
            last_project_id: Optional[str] = None
            if self._settings is not None:
                try:
                    last_project_id = self._settings.value("last_project_id", "", type=str)  # type: ignore[call-arg]
                    if not last_project_id:
                        last_project_id = None
                except Exception:
                    last_project_id = None

            initial_project_id: Optional[str] = None
            if last_project_id and last_project_id in source_projects:
                initial_project_id = last_project_id
            elif source_projects:
                # Take first alphabetically
                initial_project_id = sorted(source_projects.items(), key=lambda kv: kv[1].lower())[0][0]

            self._current_project_id = initial_project_id
            self._set_project_combo_to_current()

            # Load tasks only for current project (or all if All is selected).
            self._load_tasks_for_current_project()

            # If there is context on launch (FTRACK_CONTEXTID), try to focus on it.
            self._maybe_focus_initial_task()

            self._set_status("Tasks loaded")
            logger.info(
                "UserTasksWidget: _load_tasks finished in %.3f s",
                time.perf_counter() - t_start,
            )

        except Exception as exc:
            logger.error("Failed to load user tasks: %s", exc, exc_info=True)
            self._set_status(f"Error loading tasks: {exc}")

    def _set_project_combo_to_current(self) -> None:
        """Set current project in combo without triggering project change signal."""
        try:
            self.project_combo.blockSignals(True)
            target_id = self._current_project_id
            if target_id is None:
                # "All Projects" is always at index 0
                if self.project_combo.count() > 0:
                    self.project_combo.setCurrentIndex(0)
            else:
                for idx in range(self.project_combo.count()):
                    if self.project_combo.itemData(idx) == target_id:
                        self.project_combo.setCurrentIndex(idx)
                        break
        finally:
            self.project_combo.blockSignals(False)

    def _populate_tree(self) -> None:
        """Populate tree according to current project filter.

        Tree structure:
          Project
            └─ Parent context (parent.full_name)
                 └─ Task
        """
        self.task_tree.clear()

        # Determine list of projects to show in tree.
        projects_source = self._active_projects or {
            t["project_id"]: t["project_name"]
            for t in self._all_tasks
            if t.get("project_id")
        }

        project_items: Dict[str, QtWidgets.QTreeWidgetItem] = {}
        context_items: Dict[tuple[str, tuple[str, ...]], QtWidgets.QTreeWidgetItem] = {}

        # Create project nodes (even empty ones)
        for pid, pname in sorted(projects_source.items(), key=lambda kv: kv[1].lower()):
            if self._current_project_id and pid != self._current_project_id:
                continue
            proj_item = QtWidgets.QTreeWidgetItem(
                [pname or "Unassigned project", "", "", ""]
            )
            proj_item.setFirstColumnSpanned(True)
            project_items[pid] = proj_item
            self.task_tree.addTopLevelItem(proj_item)

        # Now distribute tasks to already created projects
        filtered_tasks = [
            t
            for t in self._all_tasks
            if (not self._current_project_id or t["project_id"] == self._current_project_id)
        ]

        filtered_tasks.sort(
            key=lambda t: (
                (t["project_name"] or "").lower(),
                (t["parent_full_name"] or "").lower(),
                (t["name"] or "").lower(),
            )
        )

        for t in filtered_tasks:
            project_id = t["project_id"] or ""
            project_name = t["project_name"] or ""
            parent_full = t["parent_full_name"] or ""

            proj_item = project_items.get(project_id)
            if proj_item is None:
                # Just in case create project if it wasn't in active list
                proj_item = QtWidgets.QTreeWidgetItem(
                    [project_name or "Unassigned project", "", "", ""]
                )
                proj_item.setFirstColumnSpanned(True)
                project_items[project_id] = proj_item
                self.task_tree.addTopLevelItem(proj_item)

            parent_item = proj_item
            segments = t.get("context_segments") or []
            if segments:
                current_path: list[str] = []
                for seg in segments:
                    current_path.append(seg)
                    key = (project_id, tuple(current_path))
                    if key not in context_items:
                        ctx_item = QtWidgets.QTreeWidgetItem([seg, "", "", ""])
                        context_items[key] = ctx_item
                        parent_item.addChild(ctx_item)
                    parent_item = context_items[key]

            info_str = ""
            if t["id"]:
                info_str = t["id"]

            task_item = QtWidgets.QTreeWidgetItem(
                [
                    t["name"] or "",
                    parent_full or project_name or "",
                    t["status_name"] or "",
                    info_str,
                ]
            )
            task_item.setData(0, QtCore.Qt.UserRole, t)  # type: ignore[attr-defined]
            parent_item.addChild(task_item)

        self.task_tree.expandAll()
        self.task_tree.resizeColumnToContents(0)

    # ------------------------------------------------------------------ Slots / helpers

    def _on_project_changed(self, index: int) -> None:
        data = self.project_combo.itemData(index)
        self._current_project_id = data or None
        if self._settings is not None:
            try:
                self._settings.setValue("last_project_id", self._current_project_id or "")
            except Exception:
                pass
        self._load_tasks_for_current_project()

    def _on_task_selection_changed(self) -> None:
        """Handle selection change in task tree.

        TEMPORARY: snapshot loading disabled for performance profiling.
        Clear right panel, update status and, if task directory already
        exists, show file list. Do not create new folders at this stage.
        """
        self.files_tree.clear()
        self.snapshots_tree.clear()
        self.linked_tree.clear()

        # By default task action buttons are disabled,
        # enable them only when a valid task is selected.
        self.create_scene_btn.setEnabled(False)
        self.get_snapshots_btn.setEnabled(False)
        self.open_scene_btn.setEnabled(False)

        current_item = self.task_tree.currentItem()
        if not current_item:
            return

        data = current_item.data(0, QtCore.Qt.UserRole)  # type: ignore[attr-defined]
        if not isinstance(data, dict):
            return

        task_name = data.get("name") or data.get("id") or "<task>"
        self._set_status(f"Selected task: {task_name}")

        # Enable actions only for valid task.
        self.create_scene_btn.setEnabled(True)
        self.get_snapshots_btn.setEnabled(True)

        # If working root is configured and directory already exists, show files.
        if self._workdir_root:
            self._populate_task_files_for_data(data, create_if_missing=False)

    # ------------------------------------------------------------------ Per-project task loading

    def _load_tasks_for_current_project(self) -> None:
        """Load tasks for current project selection from ftrack."""
        if not self.session or not self._api_user:
            logger.warning("UserTasksWidget: cannot load tasks for project, no session/api_user")
            return

        project_id = self._current_project_id

        t_tasks_query_start = time.perf_counter()
        base_query = (
            'select id, name, project.name, project.id, '
            'parent.full_name, status.name, project.status.name, link '
            f'from Task where assignments.resource.username is "{self._api_user}"'
        )
        if project_id:
            base_query += f' and project.id is "{project_id}"'

        tasks = self.session.query(base_query).all()
        logger.info(
            "UserTasksWidget: loaded %d tasks for user %s (project=%s) in %.3f s",
            len(tasks),
            self._api_user,
            project_id or "ALL",
            time.perf_counter() - t_tasks_query_start,
        )

        # Convert to simple dicts for easier handling
        t_transform_start = time.perf_counter()
        self._all_tasks = []

        # If only active projects are selected, filter just in case
        allowed_project_ids: set[str] = set(self._active_projects.keys())

        for t in tasks:
            project = t.get("project") or {}
            proj_name = project.get("name", "")
            proj_id = project.get("id", "")
            status_name = ""
            try:
                status_name = (t.get("status") or {}).get("name", "")
            except Exception:
                status_name = ""

            if allowed_project_ids and proj_id not in allowed_project_ids:
                continue

            link = t.get("link") or []
            context_segments: List[str] = []
            try:
                if isinstance(link, list) and len(link) >= 2:
                    for node in link[1:-1]:
                        if isinstance(node, dict):
                            name = node.get("name")
                        else:
                            name = None
                        if name:
                            context_segments.append(name)
            except Exception:
                context_segments = []

            parent_full_name = ""
            if context_segments:
                parent_full_name = ".".join([proj_name] + context_segments)

            self._all_tasks.append(
                {
                    "id": t["id"],
                    "name": t.get("name", ""),
                    "project_name": proj_name,
                    "project_id": proj_id,
                    "parent_full_name": parent_full_name,
                    "context_segments": context_segments,
                    "status_name": status_name,
                    "due": None,
                    "bid": None,
                }
            )

        logger.info(
            "UserTasksWidget: transformed %d tasks in %.3f s",
            len(self._all_tasks),
            time.perf_counter() - t_transform_start,
        )

        t_tree_start = time.perf_counter()
        self._populate_tree()
        logger.info(
            "UserTasksWidget: _populate_tree took %.3f s",
            time.perf_counter() - t_tree_start,
        )

    def _maybe_focus_initial_task(self) -> None:
        """If there is FTRACK_CONTEXTID context on launch, focus on that task.

        Logic:
        - try once to get task_id from self._initial_task_id;
        - determine its project_id (from already loaded tasks or direct get from ftrack);
        - if needed, switch project and reload tasks;
        - find corresponding Task in tree and select it.
        """
        task_id = self._initial_task_id
        if not task_id or not self.session:
            return

        task_id = str(task_id)
        logger.info("UserTasksWidget: trying to auto-select initial task %s", task_id)

        # First check if this task is already among loaded ones.
        found_task: Optional[Dict[str, Any]] = None
        for t in self._all_tasks:
            if str(t.get("id")) == task_id:
                found_task = t
                break

        project_id: Optional[str] = None
        if found_task is not None:
            project_id = found_task.get("project_id")
        else:
            # If tasks are not loaded yet or needed one not found, make light query by id.
            try:
                entity = self.session.get("Task", task_id)
            except Exception as exc:
                logger.warning(
                    "UserTasksWidget: failed to fetch initial Task %s: %s", task_id, exc
                )
                self._initial_task_id = None
                return

            if not entity:
                logger.warning(
                    "UserTasksWidget: initial Task %s not found on server", task_id
                )
                self._initial_task_id = None
                return

            try:
                project = entity.get("project") or {}
                project_id = project.get("id")
            except Exception:
                project_id = None

        # If we know project and it differs from current -- switch project and reload tasks.
        if project_id and project_id != self._current_project_id:
            logger.info(
                "UserTasksWidget: switching project filter to %s for initial task %s",
                project_id,
                task_id,
            )
            self._current_project_id = project_id
            self._set_project_combo_to_current()
            self._load_tasks_for_current_project()

        # Tree is already built, try to find and select needed task.
        if self._select_task_in_tree_by_id(task_id):
            logger.info(
                "UserTasksWidget: auto-selected task %s from initial context id", task_id
            )
        else:
            # Task exists (we were able to get it and project), but is not
            # in current user's task selection. Show regular task list
            # for project and notify about this in status.
            logger.info(
                "UserTasksWidget: initial task %s not found among user tasks", task_id
            )
            self._set_status(
                "The current DCC task is not assigned to you. Showing your tasks for this project."
            )

        # No longer try to auto-focus.
        self._initial_task_id = None

    def _select_task_in_tree_by_id(self, task_id: str) -> bool:
        """Find and select task in tree by id. Returns True if successful."""
        root = self.task_tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            if self._select_task_in_subtree(item, task_id):
                return True
        return False

    def _select_task_in_subtree(
        self, item: QtWidgets.QTreeWidgetItem, task_id: str  # type: ignore[name-defined]
    ) -> bool:
        data = item.data(0, QtCore.Qt.UserRole)  # type: ignore[attr-defined]
        if isinstance(data, dict) and str(data.get("id")) == task_id:
            self.task_tree.setCurrentItem(item)
            self.task_tree.scrollToItem(item)
            return True

        for i in range(item.childCount()):
            child = item.child(i)
            if self._select_task_in_subtree(child, task_id):
                return True
        return False

    # ------------------------------------------------------------------ Snapshot loading

    def _load_snapshots_for_task(self, task_id: str, task_data: Dict[str, Any]) -> None:
        """Load snapshot components (.hip) published from the given task."""
        self.snapshots_tree.clear()
        self.linked_tree.clear()

        if not self.session:
            return

        try:
            self._set_status(f"Loading snapshots for task {task_data.get('name', task_id)}...")

            # Step 1: get all versions for this task
            query = (
                'select id, version, asset.name, asset.id '
                f'from AssetVersion where task.id is "{task_id}"'
            )
            versions = self.session.query(query).all()

            if not versions:
                self._set_status("No versions found for this task.")
                return

            total_snapshots = 0
            # DCC-specific snapshot type filtering:
            # - Houdini: .hip / .hipnc / .hiplc
            # - Maya: .ma / .mb
            # - other: no filter.
            if self._is_houdini_context():
                snapshot_exts = {".hip", ".hipnc", ".hiplc"}
            elif self._is_maya_context():
                snapshot_exts = {".ma", ".mb"}
            else:
                snapshot_exts = None

            for v in versions:
                version_id = v["id"]
                version_number = v.get("version")
                asset_name = ""
                try:
                    asset = v.get("asset") or {}
                    asset_name = asset.get("name", "") or ""
                except Exception:
                    asset_name = ""

                # Step 2: get components with paths for this version and filter snapshots
                try:
                    components = self.api.get_components_with_paths_for_version(version_id)  # type: ignore[attr-defined]
                except Exception as exc:
                    logger.warning("Failed to get components for version %s: %s", version_id, exc)
                    continue

                for comp in components:
                    comp_name = comp.get("name", "").lower()
                    if comp_name != "snapshot":
                        continue

                    path = comp.get("path", "N/A")
                    file_type = comp.get("file_type", "")
                    display_comp = comp.get("display_name") or f"{comp.get('name')} ({file_type})"

                    # In DCC context show only snapshots with appropriate extension.
                    if snapshot_exts is not None:
                        try:
                            suffix = Path(str(path)).suffix.lower()
                        except Exception:
                            suffix = ""
                        if suffix not in snapshot_exts:
                            continue

                    # Availability on current machine: path exists and is not marked as N/A
                    is_local = bool(path) and not str(path).startswith("N/A") and Path(path).exists()
                    available_str = "Yes" if is_local else "No"

                    item = QtWidgets.QTreeWidgetItem(
                        [
                            asset_name or "<asset>",
                            f"v{version_number}" if version_number is not None else "",
                            display_comp,
                            path,
                            available_str,
                        ]
                    )
                    # Save component_id and version_id, as well as path, for further use
                    item.setData(0, QtCore.Qt.UserRole, {
                        "component_id": comp.get("id"),
                        "version_id": version_id,
                        "asset_name": asset_name,
                        "version_number": version_number,
                    })  # type: ignore[attr-defined]
                    item.setData(3, QtCore.Qt.UserRole, path)  # type: ignore[attr-defined]
                    self.snapshots_tree.addTopLevelItem(item)
                    total_snapshots += 1

            if total_snapshots == 0:
                self._set_status("No snapshot components found for this task.")
            else:
                self._set_status(f"{total_snapshots} snapshot(s) found for task {task_data.get('name', task_id)}")
                self.snapshots_tree.resizeColumnToContents(0)
                self.snapshots_tree.resizeColumnToContents(1)
                self.snapshots_tree.resizeColumnToContents(2)
                self.snapshots_tree.resizeColumnToContents(3)
                self.snapshots_tree.resizeColumnToContents(4)

        except Exception as exc:
            logger.error("Failed to load snapshots for task %s: %s", task_id, exc, exc_info=True)
            self._set_status(f"Error loading snapshots: {exc}")

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)


    # ------------------------------------------------------------------ Task scene helpers

    def _detect_scene_extension(self) -> str:
        """Determine scene extension depending on available DCC.

        Use simple heuristic:
        - if hou imports -> .hip
        - elif maya.cmds -> .ma
        - elif bpy -> .blend
        - else .scene
        """
        try:
            import hou  # type: ignore

            return ".hip"
        except Exception:
            pass

        try:
            import maya.cmds  # type: ignore  # noqa: F401

            return ".ma"
        except Exception:
            pass

        try:
            import bpy  # type: ignore  # noqa: F401

            return ".blend"
        except Exception:
            pass

        return ".scene"

    def _is_houdini_context(self) -> bool:
        """Determine if we are working inside Houdini (for DCC-specific filters).

        Use lazy import of hou, without hard dependency.
        """
        try:
            import hou  # type: ignore  # noqa: F401

            return True
        except Exception:
            return False

    def _is_maya_context(self) -> bool:
        """Determine if we are working inside Maya (for DCC-specific filters)."""
        try:
            import maya.cmds  # type: ignore  # noqa: F401

            return True
        except Exception:
            return False

    def _build_task_directory(self, task_data: Dict[str, Any]) -> Optional[Path]:
        """Build path to task directory relative to FTRACK_WORKDIR.

        Format:
          <FTRACK_WORKDIR>/<project_name>/<context_segments...>/<task_name>
        """
        if not self._workdir_root:
            return None

        root = Path(self._workdir_root)
        project_name = (task_data.get("project_name") or "").strip()
        task_name = (task_data.get("name") or "").strip()
        segments = task_data.get("context_segments") or []

        parts: List[str] = []
        if project_name:
            parts.append(project_name)
        for seg in segments:
            if seg:
                parts.append(str(seg))
        if task_name:
            parts.append(task_name)

        if not parts:
            return root

        return root.joinpath(*parts)

    def _slugify(self, name: str) -> str:
        """Simplify task name to safe filename."""
        import re

        name = name.strip()
        name = re.sub(r"[^\w\-\.]+", "_", name, flags=re.UNICODE)
        name = re.sub(r"_+", "_", name)
        return name.strip("_") or "scene"

    def _populate_task_files_for_data(
        self, task_data: Dict[str, Any], create_if_missing: bool = False
    ) -> None:
        """Populate right tree with task directory files.

        If create_if_missing=False, directory must already exist. When
        create_if_missing=True directory will be created if needed.
        """
        self.files_tree.clear()

        dir_path = self._build_task_directory(task_data)
        if dir_path is None:
            self._set_status("FTRACK_WORKDIR is not set; cannot build task directory.")
            return

        if not dir_path.exists():
            if not create_if_missing:
                # Simply don't show anything to avoid creating folder without user request.
                self._set_status(f"Task directory does not exist: {dir_path}")
                return
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
            except Exception as exc:
                self._set_status(f"Failed to create directory {dir_path}: {exc}")
                return

        try:
            entries = list(dir_path.iterdir())
        except Exception as exc:
            self._set_status(f"Failed to list directory {dir_path}: {exc}")
            return

        # Depending on DCC filter files by extension:
        # - Houdini: only .hip / .hipnc / .hiplc
        # - Maya: only .ma / .mb
        # - other: show all files.
        if self._is_houdini_context():
            scene_exts = {".hip", ".hipnc", ".hiplc"}
        elif self._is_maya_context():
            scene_exts = {".ma", ".mb"}
        else:
            scene_exts = None

        for entry in sorted(entries, key=lambda p: p.name.lower()):
            if entry.is_dir():
                continue
            if scene_exts is not None:
                if entry.suffix.lower() not in scene_exts:
                    continue
            stat = entry.stat()
            size_kb = f"{stat.st_size / 1024:.1f} KB"
            mtime = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
            item = QtWidgets.QTreeWidgetItem(
                [entry.name, size_kb, mtime, str(entry)]
            )
            self.files_tree.addTopLevelItem(item)

    def _on_create_task_scene_clicked(self) -> None:
        """Create recommended scene path for selected task and show its directory."""
        if not self._workdir_root:
            self._set_status("FTRACK_WORKDIR is not set; cannot create task scene path.")
            return

        current_item = self.task_tree.currentItem()
        if not current_item:
            self._set_status("No task selected.")
            return

        data = current_item.data(0, QtCore.Qt.UserRole)  # type: ignore[attr-defined]
        if not isinstance(data, dict):
            self._set_status("Selected item is not a task.")
            return

        dir_path = self._build_task_directory(data)
        if dir_path is None:
            self._set_status("Failed to build task directory.")
            return

        try:
            dir_path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self._set_status(f"Failed to create directory {dir_path}: {exc}")
            return

        task_name = data.get("name") or data.get("id") or "scene"
        slug = self._slugify(str(task_name))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = self._detect_scene_extension()
        scene_path = dir_path / f"{slug}_{ts}{ext}"

        self._set_status(f"Proposed scene path: {scene_path}")
        logger.info("UserTasksWidget: proposed scene path %s", scene_path)

        # If DCC handler exists (e.g., Houdini), delegate scene creation to it.
        if self._dcc_handlers is not None:
            try:
                self._dcc_handlers.create_task_scene(self, data, dir_path, scene_path)
            except Exception as exc:
                logger.error("UserTasksWidget: DCC create_task_scene failed: %s", exc, exc_info=True)
                self._set_status(f"Failed to create task scene via DCC: {exc}")
                return

        # Update right panel with task directory file list, creating it if needed.
        self._populate_task_files_for_data(data, create_if_missing=True)

    def _on_get_published_snapshots_clicked(self) -> None:
        """Load published snapshots for selected task."""
        current_item = self.task_tree.currentItem()
        if not current_item:
            self._set_status("No task selected.")
            return

        data = current_item.data(0, QtCore.Qt.UserRole)  # type: ignore[attr-defined]
        if not isinstance(data, dict):
            self._set_status("Selected item is not a task.")
            return

        task_id = data.get("id")
        if not task_id:
            self._set_status("Selected task has no id.")
            return

        self._load_snapshots_for_task(str(task_id), data)

    def _on_copy_snapshot_to_local_clicked(self) -> None:
        """Copy selected snapshot to local task directory.

        Filename is formed by pattern:
            <Asset>.<Version>.<DATE><ext>
        where DATE = YYYYMMDD_HHMMSS. If snapshot path is unavailable, show
        warning.
        """
        if not self._workdir_root:
            self._set_status("FTRACK_WORKDIR is not set; cannot copy snapshot to local.")
            return

        task_item = self.task_tree.currentItem()
        if not task_item:
            self._set_status("No task selected.")
            return

        task_data = task_item.data(0, QtCore.Qt.UserRole)  # type: ignore[attr-defined]
        if not isinstance(task_data, dict):
            self._set_status("Selected task is invalid.")
            return

        snap_item = self.snapshots_tree.currentItem()
        if not snap_item:
            self._set_status("No snapshot selected.")
            return

        # Try to get path from UserRole (where we save it when loading snapshots),
        # and if it's not there, from text column.
        src_path = snap_item.data(3, QtCore.Qt.UserRole) or snap_item.text(3)  # type: ignore[attr-defined]
        if not src_path or src_path in ("", "N/A"):
            self._set_status("Selected snapshot has no filesystem path (not available on any location).")
            return

        if not os.path.exists(src_path):
            self._set_status(f"Snapshot file is not accessible on this workstation: {src_path}")
            return

        dest_dir = self._build_task_directory(task_data)
        if dest_dir is None:
            self._set_status("Failed to build local task directory path.")
            return

        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self._set_status(f"Failed to create local task directory {dest_dir}: {exc}")
            return

        asset_name = (task_data.get("name") or "").strip() or "asset"
        version_label = snap_item.text(1).strip() or "v01"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = os.path.splitext(src_path)[1]
        base_name = f"{asset_name}.{version_label}.{ts}"
        new_name = base_name + (ext or "")
        dest_path = dest_dir / new_name

        # Don't overwrite existing files with same name.
        counter = 1
        while dest_path.exists():
            new_name = f"{base_name}_{counter}{ext or ''}"
            dest_path = dest_dir / new_name
            counter += 1

        try:
            shutil.copy2(src_path, dest_path)
        except Exception as exc:
            self._set_status(f"Failed to copy snapshot to {dest_path}: {exc}")
            return

        self._set_status(f"Snapshot copied to {dest_path}")
        logger.info("UserTasksWidget: copied snapshot %s -> %s", src_path, dest_path)

        # Update local file list for task.
        self._populate_task_files_for_current_selection()

    def _populate_task_files_for_current_selection(self) -> None:
        """Convenient helper: update file list for currently selected task."""
        current_item = self.task_tree.currentItem()
        if not current_item or not self._workdir_root:
            return

        data = current_item.data(0, QtCore.Qt.UserRole)  # type: ignore[attr-defined]
        if not isinstance(data, dict):
            return

        self._populate_task_files_for_data(data, create_if_missing=False)

    # ------------------------------------------------------------------ Linked components (ilink)

    def _format_size(self, size_bytes: int) -> str:
        """Human-readable file size."""
        try:
            if size_bytes < 1024:
                return f"{size_bytes} B"
            kb = size_bytes / 1024.0
            if kb < 1024:
                return f"{kb:.1f} KB"
            mb = kb / 1024.0
            if mb < 1024:
                return f"{mb:.1f} MB"
            gb = mb / 1024.0
            return f"{gb:.1f} GB"
        except Exception:
            return str(size_bytes)

    def _get_accessible_locations(self) -> List[Any]:
        """Return list of locations available on current machine (as in main browser).

        Filtering:
        - only locations with accessor (real storage);
        - exclude service ftrack.* locations;
        - sort by label / name.
        """
        if not self.session:
            return []

        try:
            # IMPORTANT: don't request priority in select, because in some
            # schema versions this field is unavailable and causes ParseError.
            # Priority value itself can be read later
            # via loc.get('priority') / loc['priority'] if needed.
            all_locations = self.session.query(
                "select id, name, label from Location"
            ).all()
        except Exception as exc:
            logger.warning("UserTasksWidget: failed to query Location list: %s", exc)
            return []

        accessible: List[Any] = []
        for loc in all_locations or []:
            try:
                if getattr(loc, "accessor", None):
                    accessible.append(loc)
            except Exception:
                # If for some reason accessor is unavailable -- consider location unused.
                continue

        excluded_names = {
            "ftrack.origin",
            "ftrack.connect",
            "ftrack.server",
            "ftrack.unmanaged",
            "ftrack.review",
        }

        filtered: List[Any] = []
        for loc in accessible:
            try:
                name = (loc.get("name") or "").strip()
            except Exception:
                name = ""
            if not name or name in excluded_names:
                continue

            # Try to carefully read priority without breaking old schemas.
            pr: Any
            try:
                pr = loc.get("priority")
            except Exception:
                try:
                    pr = getattr(loc, "priority", None)
                except Exception:
                    pr = None

            filtered.append(loc)
            logger.info(
                "UserTasksWidget: accessible location candidate: name=%s, priority=%r",
                name,
                pr,
            )

        try:
            filtered.sort(key=lambda loc: ((loc.get("label") or loc.get("name") or "").lower()))
        except Exception:
            pass

        return filtered

    def _pick_default_target_location(self, locations: List[Any]) -> Optional[Any]:
        """Pick default target location.

        Based on official ftrack API logic:
        :meth:`Session.pick_location` returns «highest priority accessible
        location». First try to use it, and only if
        for some reason it didn't work, fall back to manual
        selection by numeric ``priority`` within *locations*.
        """
        if not locations:
            return None

        # 1) Try official Session.pick_location (without component).
        if self.session is not None:
            try:
                picked = self.session.pick_location()
            except Exception as exc:
                logger.warning(
                    "UserTasksWidget: Session.pick_location() failed, "
                    "falling back to manual priority scan: %s",
                    exc,
                )
                picked = None

            if picked is not None:
                try:
                    logger.info(
                        "UserTasksWidget: target location from Session.pick_location(): %s (priority=%r)",
                        picked.get("name"),
                        getattr(picked, "priority", None),
                    )
                except Exception:
                    pass
                return picked

        # 2) Fallback: take Location with minimum numeric priority from *locations*.
        best: Optional[Any] = None
        best_pr: Optional[int] = None
        for loc in locations:
            # Work maximally defensively here, as documentation advises.
            try:
                try:
                    pr = loc.get("priority")
                except Exception:
                    pr = getattr(loc, "priority", None)
                pr_val = int(pr) if pr is not None else None
            except Exception:
                pr_val = None
            if pr_val is None:
                continue
            if best_pr is None or pr_val < best_pr:
                best_pr = pr_val
                best = loc

        if best is not None:
            try:
                logger.info(
                    "UserTasksWidget: target location by manual priority=%s: %s",
                    best_pr,
                    best.get("name"),
                )
            except Exception:
                pass
        return best

    def _update_transfer_target_label(self, location: Optional[Any]) -> None:
        """Update label next to transfer button."""
        if not hasattr(self, "transfer_target_info_label"):
            return
        if not location:
            text = "(target: n/a)"
        else:
            try:
                name = (location.get("name") or "").strip()
            except Exception:
                name = ""
            if not name:
                name = "<unknown>"
            text = f"(target: {name})"
        self.transfer_target_info_label.setText(text)

    def _get_component_locations_for_ids(self, component_ids: List[str]) -> Dict[str, List[Dict[str, str]]]:
        """Return for each component_id list of locations where it is present.

        IMPORTANT: don't rely on external transfer_components.* package (it's not always
        in sys.path), so use local copy of ComponentLocation query,
        similar to get_component_locations_minimal().
        """
        result: Dict[str, List[Dict[str, str]]] = {}
        if not component_ids or not self.session:
            return result

        # Local analog of transfer_components.core.ftrack_utils.get_component_locations_minimal
        try:
            # Same list of excluded service locations as in plugin.
            excluded_locations = [
                "ftrack.origin",
                "ftrack.connect",
                "ftrack.server",
                "ftrack.unmanaged",
                "ftrack.review",
            ]
            excluded_str = ",".join(f'"{name}"' for name in excluded_locations)

            if len(component_ids) == 1:
                cid = component_ids[0]
                query = (
                    "select "
                    "id, "
                    "resource_identifier, "
                    "location.id, "
                    "location.name, "
                    "component.id "
                    f'from ComponentLocation where component.id is "{cid}"'
                    f" and location.name not_in ({excluded_str})"
                )
            else:
                quoted_ids = [f'"{cid}"' for cid in component_ids]
                query = (
                    "select "
                    "id, "
                    "resource_identifier, "
                    "location.id, "
                    "location.name, "
                    "component.id "
                    f"from ComponentLocation where component.id in ({','.join(quoted_ids)})"
                    f" and location.name not_in ({excluded_str})"
                )

            cl_entities = self.session.query(query).all()
        except Exception as exc:
            logger.warning(
                "UserTasksWidget: local ComponentLocation query failed: %s", exc
            )
            return result

        for cl in cl_entities or []:
            try:
                comp = cl.get("component")
                loc = cl.get("location")
                cid = (comp.get("id") if comp is not None else None)  # type: ignore[union-attr]
                loc_id = (loc.get("id") if loc is not None else None)  # type: ignore[union-attr]
                loc_name = (loc.get("name") if loc is not None else "")  # type: ignore[union-attr]
            except Exception:
                continue

            if not cid or not loc_id or not loc_name:
                continue

            entry = {"id": str(loc_id), "name": str(loc_name)}
            bucket = result.setdefault(str(cid), [])
            # Avoid duplicates by id.
            if all(existing["id"] != entry["id"] for existing in bucket):
                bucket.append(entry)

        return result

    def _describe_component_locations(self, component: Any, locations: List[Any]) -> str:
        """Return string with list of locations where component is present."""
        if not locations or component is None:
            return ""

        names: List[str] = []
        for loc in locations:
            try:
                # get_component_url is safe for checking component presence in location.
                url = loc.get_component_url(component)
            except Exception:
                url = None
            if url:
                name = (loc.get("name") or "").strip()
                if name:
                    names.append(name)

        # Remove duplicates and sort for stable display.
        names = sorted(set(names), key=lambda n: n.lower())
        return ", ".join(names)

    def _populate_transfer_locations_if_needed(self) -> None:
        """(No longer used) Fill dropdown list of target locations.

        Target location combo box removed from UI; method left only for
        compatibility, but no longer called anywhere.
        """
        if self._transfer_locations_initialized:
            return
        if not self.session:
            return
        if not hasattr(self, "transfer_target_combo"):
            return

        locations = self._get_accessible_locations()
        if not locations:
            logger.warning("UserTasksWidget: no accessible locations found for transfer combo.")
            return

        self.transfer_target_combo.blockSignals(True)
        self.transfer_target_combo.clear()

        preferred_index = 0
        index = 0

        for loc in locations:
            name = (loc.get("name") or "").strip()
            if not name:
                continue
            name_lower = name.lower()
            # It doesn't make sense to include s3.minio in target list -- it's most likely a source.
            if name_lower == "s3.minio":
                continue

            self.transfer_target_combo.addItem(name, loc.get("id"))

            # Try to select local user location by default.
            if any(key in name_lower for key in ("burlin.local", "x.local", "burlin.backup")):
                preferred_index = index

            index += 1

        if self.transfer_target_combo.count() > 0:
            self.transfer_target_combo.setCurrentIndex(preferred_index)
            self._transfer_locations_initialized = True

        self.transfer_target_combo.blockSignals(False)

    def _parse_ilink_ids(self, ilink_raw: Any) -> List[str]:
        """Normalize metadata['ilink'] value to list of component id strings."""
        if not ilink_raw:
            return []

        # Already a list
        if isinstance(ilink_raw, (list, tuple)):
            return [str(x).strip() for x in ilink_raw if str(x).strip()]

        # Try to parse as JSON
        text = str(ilink_raw).strip()
        try:
            parsed = json.loads(text)
            if isinstance(parsed, (list, tuple)):
                return [str(x).strip() for x in parsed if str(x).strip()]
        except Exception:
            pass

        # Fallback: string with ids separated by comma
        return [p.strip() for p in text.split(",") if p.strip()]

    def _on_collect_linked_clicked(self) -> None:
        """Collect and display linked components (ilink) for selected snapshot."""
        self.linked_tree.clear()

        if not self.session:
            self._set_status("No active ftrack session; cannot collect linked components.")
            return

        snap_item = self.snapshots_tree.currentItem()
        if not snap_item:
            self._set_status("No snapshot selected.")
            return

        meta = snap_item.data(0, QtCore.Qt.UserRole)  # type: ignore[attr-defined]
        if not isinstance(meta, dict):
            self._set_status("Snapshot meta-data not found; cannot resolve component id.")
            return

        component_id = meta.get("component_id")
        if not component_id:
            self._set_status("Snapshot component id is missing; cannot read metadata.")
            return

        try:
            comp_entity = self.session.get("Component", str(component_id))
        except Exception as exc:
            logger.error("Failed to fetch Component %s: %s", component_id, exc, exc_info=True)
            self._set_status(f"Error fetching snapshot component {component_id}: {exc}")
            return

        if not comp_entity:
            self._set_status(f"Component {component_id} not found in ftrack.")
            return

        metadata = {}
        try:
            metadata = comp_entity.get("metadata") or {}
        except Exception:
            metadata = {}

        # Log metadata for debugging formats (new/old).
        logger.info(
            "UserTasksWidget: metadata for snapshot component %s: %r",
            component_id,
            metadata,
        )

        # Main path: "ilink" field (new format).
        ilink_raw = metadata.get("ilink")
        logger.info("UserTasksWidget: raw ilink value for component %s: %r", component_id, ilink_raw)
        ilink_ids = self._parse_ilink_ids(ilink_raw)

        # Fallback for old format:
        # metadata had key/value pairs like "0": "<component_id>", "1": "<component_id>", ...
        # In practice metadata comes as KeyValueMappedCollectionProxy, so check for Mapping.
        if not ilink_ids and isinstance(metadata, Mapping):
            legacy_ids: List[str] = []
            for k, v in metadata.items():
                # Key could be string "0" or int 0 -- normalize to string.
                key_str = str(k)
                if key_str.isdigit() and v:
                    s = str(v).strip()
                    if s:
                        legacy_ids.append(s)
            if legacy_ids:
                ilink_ids = legacy_ids

        if not ilink_ids:
            self._set_status("No linked component ids found in snapshot metadata.")
            return

        # List of all available locations -- both for display and for selecting
        # source/target.
        locations = self._get_accessible_locations()
        by_location_id: Dict[str, Any] = {}
        for loc in locations:
            try:
                lid = str(loc.get("id"))
            except Exception:
                lid = ""
            if lid:
                by_location_id[lid] = loc

        # Default target location (by minimum priority).
        target_location = self._pick_default_target_location(locations)
        self._update_transfer_target_label(target_location)
        target_loc_id: Optional[str] = None
        if target_location is not None:
            try:
                tlid = target_location.get("id")
                if tlid:
                    target_loc_id = str(tlid)
            except Exception:
                target_loc_id = None

        # Map component_id -> list of locations where it is actually present.
        all_component_ids: List[str] = [str(component_id)] + [str(x) for x in ilink_ids]
        comp_locations_map = self._get_component_locations_for_ids(all_component_ids)
        
        # IMPORTANT: Filter comp_locations_map to only include accessible locations
        # This prevents showing components as transferable when they're only in inaccessible locations like burlin.local
        accessible_location_ids = {str(loc.get("id")) for loc in locations if loc.get("id")}
        filtered_comp_locations_map: Dict[str, List[Dict[str, str]]] = {}
        for comp_id, loc_list in comp_locations_map.items():
            filtered_locs = [
                loc_entry for loc_entry in loc_list
                if str(loc_entry.get("id", "")) in accessible_location_ids
            ]
            if filtered_locs:
                filtered_comp_locations_map[comp_id] = filtered_locs
        
        comp_locations_map = filtered_comp_locations_map

        total = 0

        # --- First add snapshot component itself as first list item ---
        try:
            snap_asset_name = ""
            snap_version_label = ""
            snap_comp_ext = ""
            try:
                snap_version = comp_entity.get("version") or {}
                snap_asset = snap_version.get("asset") or {}
                snap_asset_name = snap_asset.get("name", "") or ""
                snap_version_number = snap_version.get("version")
                if snap_version_number is not None:
                    snap_version_label = f"v{snap_version_number}"
                # Component extension: try to extract from path or file_type.
                try:
                    comp_name = comp_entity.get("name") or ""
                except Exception:
                    comp_name = ""
                try:
                    # get_filesystem_path may return real path for one of locations.
                    any_loc_path = None
                    for entry in loc_entries or []:
                        lid = entry.get("id")
                        if not lid:
                            continue
                        loc_obj = by_location_id.get(str(lid))
                        if not loc_obj:
                            continue
                        try:
                            p = loc_obj.get_filesystem_path(comp_entity)
                        except Exception:
                            p = None
                        if p:
                            any_loc_path = str(p)
                            break
                    if any_loc_path:
                        snap_comp_ext = os.path.splitext(any_loc_path)[1] or ""
                except Exception:
                    snap_comp_ext = ""
                if not snap_comp_ext:
                    try:
                        ft = comp_entity.get("file_type") or ""
                        snap_comp_ext = str(ft)
                    except Exception:
                        snap_comp_ext = ""
            except Exception:
                snap_asset_name = ""
                snap_version_label = ""

            snap_path = "N/A"
            snap_available = "No"
            snap_size_str = ""
            snap_locations = ""

            # Locations where component actually resides (according to ComponentLocation data).
            loc_entries = comp_locations_map.get(str(component_id), [])

            # String for Locations column.
            try:
                snap_locations = ", ".join(
                    sorted(
                        {entry["name"] for entry in loc_entries if entry.get("name")},
                        key=lambda n: n.lower(),
                    )
                )
            except Exception:
                snap_locations = ""
            if not snap_locations:
                snap_locations = "-"

            # For path and Available try to find first available local location
            # from those where component actually is present.
            for entry in loc_entries:
                lid = entry.get("id")
                if not lid:
                    continue
                loc = by_location_id.get(str(lid))
                if not loc:
                    continue
                try:
                    sp = loc.get_filesystem_path(comp_entity)
                    if sp is None:
                        continue
                    snap_path = str(sp)
                    if os.path.exists(snap_path):
                        snap_available = "Yes"
                        try:
                            snap_size_bytes = os.path.getsize(snap_path)
                            snap_size_str = self._format_size(snap_size_bytes)
                        except Exception:
                            snap_size_str = ""
                    else:
                        snap_available = "No"
                    # Path found -- exit loop over locations.
                    break
                except Exception as exc:
                    logger.warning(
                        "Failed to resolve filesystem path for snapshot Component %s in location %s: %s",
                        component_id,
                        entry.get("name"),
                        exc,
                    )
                    continue

            # Determine if component is already present in target location.
            already_in_target = False
            if target_loc_id is not None:
                try:
                    already_in_target = any(
                        str(entry.get("id")) == target_loc_id for entry in loc_entries
                    )
                except Exception:
                    already_in_target = False

            # Check if component has at least one accessible source location (not target)
            has_accessible_source = False
            if not already_in_target:
                for entry in loc_entries:
                    lid = entry.get("id")
                    if lid and str(lid) != target_loc_id and str(lid) in accessible_location_ids:
                        has_accessible_source = True
                        break

            snap_item = QtWidgets.QTreeWidgetItem(
                [
                    snap_asset_name or "<asset>",             # Asset
                    snap_version_label,                       # Version
                    str(comp_entity.get("name") or component_id),  # Component
                    snap_comp_ext,                            # Component.ext
                    snap_available,                           # Available
                    snap_size_str,                            # Size
                    snap_locations,                           # Locations
                    "",                                       # To transfer (checkbox)
                ]
            )
            snap_item.setData(0, QtCore.Qt.UserRole, str(component_id))  # type: ignore[attr-defined]
            # By default mark snapshot itself for transfer ONLY if file is not
            # on available local location and is absent in target location.
            if already_in_target:
                default_state = QtCore.Qt.Unchecked
            else:
                default_state = (
                    QtCore.Qt.Unchecked
                    if snap_available == "Yes"
                    else QtCore.Qt.Checked
                )
            # Column "To transfer" is now at index 7.
            snap_item.setCheckState(7, default_state)  # type: ignore[attr-defined]
            # If component is already in target location OR has no accessible source locations, make checkbox unavailable.
            if already_in_target or not has_accessible_source:
                flags = snap_item.flags()
                flags &= ~QtCore.Qt.ItemIsUserCheckable  # type: ignore[attr-defined]
                snap_item.setFlags(flags)
                if not has_accessible_source and not already_in_target:
                    logger.debug(
                        "UserTasksWidget: snapshot component %s checkbox disabled - no accessible source locations",
                        component_id[:8]
                    )
            self.linked_tree.addTopLevelItem(snap_item)
            total += 1
        except Exception as exc:
            logger.warning("UserTasksWidget: failed to add snapshot component to linked list: %s", exc, exc_info=True)

        # --- Then add all components from ilink ---
        for linked_id in ilink_ids:
            try:
                linked_comp = self.session.get("Component", str(linked_id))
            except Exception as exc:
                logger.warning("Failed to fetch linked Component %s: %s", linked_id, exc)
                continue

            if not linked_comp:
                continue

            # Asset name / version number / component extension
            asset_name = ""
            version_label = ""
            comp_ext = ""
            try:
                version = linked_comp.get("version") or {}
                asset = version.get("asset") or {}
                asset_name = asset.get("name", "") or ""
                version_number = version.get("version")
                if version_number is not None:
                    version_label = f"v{version_number}"
                # Try to determine component extension (by path or file_type).
                try:
                    any_loc_path = None
                    for entry in loc_entries or []:
                        lid = entry.get("id")
                        if not lid:
                            continue
                        loc_obj = by_location_id.get(str(lid))
                        if not loc_obj:
                            continue
                        try:
                            p = loc_obj.get_filesystem_path(linked_comp)
                        except Exception:
                            p = None
                        if p:
                            any_loc_path = str(p)
                            break
                    if any_loc_path:
                        comp_ext = os.path.splitext(any_loc_path)[1] or ""
                except Exception:
                    comp_ext = ""
                if not comp_ext:
                    try:
                        ft = linked_comp.get("file_type") or ""
                        comp_ext = str(ft)
                    except Exception:
                        comp_ext = ""
            except Exception:
                asset_name = ""
                version_label = ""
                comp_ext = ""

            path = "N/A"
            available = "No"
            size_str = ""
            locations_str = ""

            # Locations where this linked component is present.
            loc_entries = comp_locations_map.get(str(linked_id), [])
            try:
                locations_str = ", ".join(
                    sorted(
                        {entry["name"] for entry in loc_entries if entry.get("name")},
                        key=lambda n: n.lower(),
                    )
                )
            except Exception:
                locations_str = ""
            if not locations_str:
                locations_str = "-"

            # Determine if component is already present in target location.
            already_in_target = False
            if target_loc_id is not None:
                try:
                    already_in_target = any(
                        str(entry.get("id")) == target_loc_id for entry in loc_entries
                    )
                except Exception:
                    already_in_target = False

            # Check if component has at least one accessible source location (not target)
            has_accessible_source = False
            if not already_in_target:
                for entry in loc_entries:
                    lid = entry.get("id")
                    if lid and str(lid) != target_loc_id and str(lid) in accessible_location_ids:
                        has_accessible_source = True
                        break

            # For path and Available try to find first available local location
            # from those where component actually is present.
            for entry in loc_entries:
                lid = entry.get("id")
                if not lid:
                    continue
                loc = by_location_id.get(str(lid))
                if not loc:
                    continue
                try:
                    p = loc.get_filesystem_path(linked_comp)
                    if p is None:
                        continue
                    path = str(p)
                    if os.path.exists(path):
                        available = "Yes"
                        try:
                            size_bytes = os.path.getsize(path)
                            size_str = self._format_size(size_bytes)
                        except Exception:
                            size_str = ""
                    else:
                        available = "No"
                    break
                except Exception as exc:
                    logger.warning(
                        "Failed to resolve filesystem path for linked Component %s in location %s: %s",
                        linked_id,
                        entry.get("name"),
                        exc,
                    )
                    continue

            item = QtWidgets.QTreeWidgetItem(
                [
                    asset_name or "<asset>",                  # Asset
                    version_label,                            # Version
                    str(linked_comp.get("name") or linked_id),# Component
                    comp_ext,                                 # Component.ext
                    available,                                # Available
                    size_str,                                 # Size
                    locations_str,                            # Locations
                    "",                                       # To transfer (checkbox)
                ]
            )
            # Save component id just in case
            item.setData(0, QtCore.Qt.UserRole, str(linked_id))  # type: ignore[attr-defined]
            # Checkbox for marking components for transfer (column 7).
            item.setCheckState(7, QtCore.Qt.Unchecked)  # type: ignore[attr-defined]
            # If component is already in target location OR has no accessible source locations, make checkbox unavailable.
            if already_in_target or not has_accessible_source:
                flags = item.flags()
                flags &= ~QtCore.Qt.ItemIsUserCheckable  # type: ignore[attr-defined]
                item.setFlags(flags)
                if not has_accessible_source and not already_in_target:
                    logger.debug(
                        "UserTasksWidget: component %s checkbox disabled - no accessible source locations",
                        linked_id[:8]
                    )
            self.linked_tree.addTopLevelItem(item)
            total += 1

        if total == 0:
            self._set_status("No linked components resolved from ilink metadata.")
        else:
            self._set_status(f"Collected {total} linked component(s) from ilink.")

    def _on_transfer_linked_to_local_clicked(self) -> None:
        """Launch actual transfer for marked linked components.

        Use same TransferWorker and TransferStatusDialog as main browser.
        Target location is selected automatically as location with minimum priority.
        """

        selected_ids: List[str] = []
        root_count = self.linked_tree.topLevelItemCount()
        for i in range(root_count):
            item = self.linked_tree.topLevelItem(i)
            # Column "To transfer" now has index 7.
            if item.checkState(7) == QtCore.Qt.Checked:  # type: ignore[attr-defined]
                comp_id = item.data(0, QtCore.Qt.UserRole)
                if comp_id:
                    selected_ids.append(str(comp_id))

        logger.info("UserTasksWidget: Transfer to local requested for linked components: %r", selected_ids)
        if not selected_ids:
            self._set_status("No linked components selected for transfer.")
            return

        if not self.session:
            self._set_status("No ftrack session available for transfer.")
            logger.warning("UserTasksWidget: cannot start transfer without ftrack session.")
            return

        # Import same stack that main browser uses.
        try:
            from .transfer_status_widget import get_transfer_dialog  # type: ignore
            from .browser_widget import TransferWorker  # type: ignore
        except Exception as exc:
            logger.error("UserTasksWidget: failed to import transfer stack: %s", exc, exc_info=True)
            self._set_status("Transfer stack (TransferWorker/StatusDialog) not available.")
            return

        # Determine from/to locations.
        locations = self._get_accessible_locations()
        if not locations:
            logger.error("UserTasksWidget: no accessible locations available for transfer.")
            self._set_status("Cannot query accessible locations for transfer.")
            return

        # Dictionary id -> Location for fast lookups.
        by_id: Dict[str, Any] = {}
        for loc in locations:
            loc_id = loc.get("id")
            if loc_id:
                by_id[str(loc_id)] = loc

        # Target location: take Location with minimum priority among available.
        to_location = self._pick_default_target_location(locations)

        if to_location is None:
            self._set_status("Cannot determine target location for transfer.")
            logger.warning("UserTasksWidget: to_location is None (locations=%r)", locations)
            return

        to_location_id = to_location["id"]
        to_location_name = to_location.get("name", "Target")
        # Update label under button so user explicitly sees target.
        self._update_transfer_target_label(to_location)

        # ---------- Determine where we can actually pull each component from ----------
        # Build set of "best" sources for each selected component:
        # - if component is already in target location and nowhere else -- skip;
        # - if present both in target and other locations -- take non-target as source;
        # - if not in any location -- skip;
        # - from all possible sources prefer s3.minio, then backup, then others.

        # Map component_id -> list of locations where it is present
        comp_locations_map = self._get_component_locations_for_ids(selected_ids)
        
        # Build set of accessible location IDs for filtering
        accessible_location_ids = {str(loc.get("id")) for loc in locations if loc.get("id")}
        
        # Filter comp_locations_map to only include accessible locations
        # This ensures we don't try to transfer from inaccessible locations like burlin.local
        filtered_comp_locations_map: Dict[str, List[Dict[str, str]]] = {}
        for comp_id, loc_list in comp_locations_map.items():
            filtered_locs = [
                loc_entry for loc_entry in loc_list
                if str(loc_entry.get("id", "")) in accessible_location_ids
            ]
            if filtered_locs:
                filtered_comp_locations_map[comp_id] = filtered_locs
            else:
                logger.debug(
                    "UserTasksWidget: component %s has no accessible source locations (only: %r)",
                    comp_id[:8],
                    [loc.get("name") for loc in loc_list]
                )
        
        comp_locations_map = filtered_comp_locations_map

        def _choose_source_for_component(component_id: str) -> Optional[Any]:
            """Return suitable source Location for component or None if there's nowhere to get it from.
            
            IMPORTANT: Only consider accessible locations (locations that are in the accessible_locations list).
            This prevents selecting unavailable locations like burlin.local that user cannot access.
            """
            loc_entries = comp_locations_map.get(str(component_id), [])
            if not loc_entries:
                return None

            # Build set of accessible location IDs for fast lookup
            accessible_location_ids = {str(loc.get("id")) for loc in locations if loc.get("id")}

            # Source candidates -- all component locations except target, AND only accessible locations.
            candidates: List[Any] = []
            for entry in loc_entries:
                lid = entry.get("id")
                if not lid or str(lid) == str(to_location_id):
                    continue
                # IMPORTANT: Only consider accessible locations
                if str(lid) not in accessible_location_ids:
                    logger.debug(
                        "UserTasksWidget: skipping location %s for component %s (not accessible)",
                        entry.get("name", "unknown"),
                        component_id[:8]
                    )
                    continue
                loc = by_id.get(str(lid))
                if loc:
                    candidates.append(loc)

            if not candidates:
                # Component exists only in target or only in inaccessible locations -- no need to copy it.
                logger.debug(
                    "UserTasksWidget: no accessible source locations for component %s (locations: %r)",
                    component_id[:8],
                    [e.get("name") for e in loc_entries]
                )
                return None

            def _weight(loc: Any) -> int:
                name = (loc.get("name") or "").lower()
                if name == "s3.minio" or "s3" in name:
                    return 0
                if "backup" in name:
                    return 1
                return 10

            candidates.sort(key=_weight)
            selected = candidates[0]
            logger.debug(
                "UserTasksWidget: selected source location '%s' for component %s (from %d candidates)",
                selected.get("name", "unknown"),
                component_id[:8],
                len(candidates)
            )
            return selected

        # Form batches: source_location_id -> list of component_id
        batches: Dict[str, List[str]] = {}
        component_entities: Dict[str, Any] = {}
        skipped_missing_source: List[str] = []
        skipped_only_in_target: List[str] = []

        for cid in selected_ids:
            try:
                comp = self.session.get("Component", str(cid))
            except Exception as exc:
                logger.warning("UserTasksWidget: failed to fetch Component %s for transfer: %s", cid, exc)
                skipped_missing_source.append(cid)
                continue

            if not comp:
                skipped_missing_source.append(cid)
                continue

            source_loc = _choose_source_for_component(cid)
            if source_loc is None:
                # Either component is not stored anywhere, or exists only in target.
                # Distinguishing these cases for logs is expensive, so just mark it.
                skipped_only_in_target.append(cid)
                continue

            src_id = str(source_loc.get("id"))
            if not src_id:
                skipped_missing_source.append(cid)
                continue

            batches.setdefault(src_id, []).append(cid)
            component_entities[cid] = comp

        if not batches:
            self._set_status(
                "No linked components can be transferred: all either missing in source locations or already in target."
            )
            logger.info(
                "UserTasksWidget: no transferable components. skipped_missing_source=%r, skipped_only_in_target=%r",
                skipped_missing_source,
                skipped_only_in_target,
            )
            return

        # Determine current user id.
        try:
            user = self.session.query(f'User where username is "{self.session.api_user}"').one()
            user_id = user["id"]
        except Exception as exc:
            logger.error("UserTasksWidget: failed to resolve current user id: %s", exc, exc_info=True)
            self._set_status("Cannot resolve current user id for transfer.")
            return

        # Local TransferStatusDialog window is no longer raised -- common manager
        # lives in "Mroya Transfer Manager" tab inside ftrack Connect.
        transfer_dialog = None

        # For each batch (source -> list of components) create a separate TransferWorker.
        total_planned = 0
        for from_location_id, comp_ids in batches.items():
            from_location = by_id.get(str(from_location_id))
            if not from_location:
                logger.warning("UserTasksWidget: source location id %s not found in by_id map.", from_location_id)
                continue

            from_location_name = from_location.get("name", "Source")

            selection_entities = [{"entityType": "Component", "entityId": cid} for cid in comp_ids]
            selected_components = [
                {
                    "id": cid,
                    "name": str(component_entities.get(cid).get("name") or cid),
                }
                for cid in comp_ids
            ]

            if not selection_entities:
                continue

            # Human-readable label for batch of components.
            if len(selected_components) == 1:
                component_label = selected_components[0]["name"]
            else:
                component_label = f"{len(selected_components)} components from {from_location_name}"

            logger.info(
                "UserTasksWidget: transfer batch from '%s' (%s) to '%s' (%s), %d component(s)",
                from_location_name,
                from_location_id,
                to_location_name,
                to_location_id,
                len(comp_ids),
            )

            worker = TransferWorker(
                selection_entities,
                from_location_id,
                to_location_id,
                user_id,
                component_label,
                to_location_name,
            )

            # Log/status only to console / UserTasks status bar.
            worker.signals.job_created.connect(
                lambda job, comp_name, src_name=from_location_name: logger.info(
                    "UserTasksWidget transfer started for '%s' from '%s' to '%s', job %s",
                    comp_name,
                    src_name,
                    to_location_name,
                    job.get("id", "n/a"),
                )
            )
            worker.signals.error.connect(
                lambda error_msg, src_name=from_location_name: logger.error(
                    "UserTasksWidget transfer error (from %s): %s", src_name, error_msg
                )
            )

            QtCore.QThreadPool.globalInstance().start(worker)  # type: ignore[attr-defined]
            total_planned += len(comp_ids)

        if transfer_dialog:
            try:
                transfer_dialog.show()
                transfer_dialog.raise_()
                transfer_dialog.activateWindow()
            except Exception:
                pass

        self._set_status(
            f"Initiated transfer for {total_planned} linked component(s) to {to_location_name}."
        )

    # ------------------------------------------------------------------ File selection / open scene

    def _on_file_selection_changed(self) -> None:
        """Enable / disable Open Scene button depending on file selection."""
        if not hasattr(self, "open_scene_btn"):
            return

        selected = self.files_tree.selectedItems()
        self.open_scene_btn.setEnabled(bool(selected))

    def _on_open_scene_clicked(self) -> None:
        """Open selected local scene file through system handler."""
        selected = self.files_tree.selectedItems()
        if not selected:
            self._set_status("No local file selected to open.")
            return

        item = selected[0]
        path = item.text(3).strip()
        if not path:
            self._set_status("Selected entry has no filesystem path.")
            return

        if not os.path.exists(path):
            self._set_status(f"File does not exist: {path}")
            return

        # Current task (if any) is passed to DCC layer as context.
        task_data: Dict[str, Any] = {}
        try:
            task_item = self.task_tree.currentItem()
            if task_item is not None:
                td = task_item.data(0, QtCore.Qt.UserRole)  # type: ignore[attr-defined]
                if isinstance(td, dict):
                    task_data = td
        except Exception:
            task_data = {}

        # If DCC handlers (Houdini/Maya/Blender) are available, let them open scene and close window.
        if self._dcc_handlers is not None:
            try:
                self._dcc_handlers.open_scene(self, path, task_data)  # type: ignore[arg-type]
                self._set_status(f"Opening scene via DCC: {path}")
                logger.info("UserTasksWidget: opening scene via DCC %s", path)
                return
            except Exception as exc:
                logger.error("UserTasksWidget: DCC open_scene failed: %s", exc, exc_info=True)
                self._set_status(f"Failed to open scene via DCC: {exc}")
                return

        # Standard behavior for standalone mode.
        try:
            if QtGui is not None:
                url = QtCore.QUrl.fromLocalFile(path)  # type: ignore[attr-defined]
                QtGui.QDesktopServices.openUrl(url)  # type: ignore[attr-defined]
            else:
                # Fallback: platform-dependent opening without QtGui.
                if os.name == "nt":
                    os.startfile(path)  # type: ignore[attr-defined]
                else:
                    import subprocess

                    subprocess.Popen(["xdg-open", path])
            self._set_status(f"Opening scene: {path}")
            logger.info("UserTasksWidget: opening scene file %s", path)
        except Exception as exc:
            logger.error("UserTasksWidget: failed to open scene %s: %s", path, exc, exc_info=True)
            self._set_status(f"Failed to open scene: {exc}")
