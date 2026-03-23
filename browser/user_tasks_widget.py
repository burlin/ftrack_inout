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
import re
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

# Keys on Asset.metadata that hold structured blobs, not flat component-id pairs.
_ASSET_METADATA_NON_PAIR_KEYS = frozenset(
    {
        "use_this_list",
        "latest_published_list",
        "status_note",
        "ilink",
    }
)

# Typical ftrack UUID component id (also used for other entity ids).
_COMPONENT_ID_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _looks_like_ftrack_entity_id(value: str) -> bool:
    """Heuristic: *value* is probably an ftrack id (UUID or long hex token)."""
    t = value.strip()
    if len(t) < 8:
        return False
    if _COMPONENT_ID_UUID_RE.match(t):
        return True
    if len(t) >= 32 and re.fullmatch(r"[0-9a-f]+", t, flags=re.IGNORECASE):
        return True
    # Opaque ids without spaces (avoid catching sentences or URLs).
    if (
        len(t) >= 20
        and not any(c in t for c in " \n\r\t")
        and "://" not in t
        and "=" not in t
    ):
        return True
    return False


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
        initial_task_id: Optional[str] = None,
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
        # Initial task context, used to focus specific task on launch.
        # Prefer explicit argument (e.g., from CLI --task-id), fall back to
        # FTRACK_CONTEXTID environment variable for DCC integrations.
        self._initial_task_id: Optional[str] = (
            str(initial_task_id).strip() if initial_task_id else None
        ) or os.environ.get("FTRACK_CONTEXTID") or None
        # Root of project working directory, used for building paths
        # to scenes for tasks.
        self._workdir_root = os.environ.get("FTRACK_WORKDIR") or None
        self._settings = QtCore.QSettings("mroya", "TaskHubUserTasks") if QtCore is not None else None  # type: ignore[call-arg]
        # DCC handlers (Houdini/Blender/Maya) for actions like scene creation.
        self._dcc_handlers: Optional[UserTasksDccHandlers] = dcc_handlers

        # Lazy initialization of target locations list for linked component transfer.
        self._transfer_locations_initialized: bool = False
        # Guard recursive use_this_tree itemChanged handling.
        self._use_this_tree_syncing: bool = False
        # One-time vertical splitter sizes for the right pane (shot deps vs ilink).
        self._right_vert_split_sizes_set: bool = False
        # One-time sizes for shot-linked list vs use_this tree inside the shot-deps stack.
        self._shot_deps_vert_split_sizes_set: bool = False
        # After Collect linked: hide shot deps; show only ilink (legacy single frame).
        self._right_pane_ilink_only: bool = False
        # Board: ideal width for all status columns; actual splitter uses min(desired, window cap).
        self._board_desired_left_width: Optional[int] = None

        # Optional status filter for Board view (normalized lowercase status names).
        # None means show all statuses; a non-empty set filters to specific ones.
        # By default show only "In progress" column when no explicit task is provided.
        default_board_status = "in progress"
        self._board_filter_statuses: Optional[set[str]] = {default_board_status}
        # When widget is launched with specific task context, Board filter will be
        # refined to that task status in _maybe_focus_initial_task.
        if self._initial_task_id:
            self._board_filter_statuses = None

        self._build_ui()
        self._load_tasks()

    # ------------------------------------------------------------------ UI

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(4)

        # Toolbar: Project filter + refresh + view mode
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

        # View mode: Tree / Board
        self.view_mode_combo = QtWidgets.QComboBox(self)
        self.view_mode_combo.addItem("Tree")
        self.view_mode_combo.addItem("Board")
        self.view_mode_combo.currentIndexChanged.connect(self._on_view_mode_changed)
        toolbar.addWidget(self.view_mode_combo)

        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        # Main splitter: left = tasks (Tree / Board) + actions,
        # middle = files/snapshots, right = linked components.
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)  # type: ignore[attr-defined]
        layout.addWidget(splitter, 1)
        self._main_splitter = splitter
        self._splitter_initial_sizes_set = False

        # Left pane: stacked task views (Tree / Board) + task action buttons.
        left_widget = QtWidgets.QWidget(splitter)
        self._left_pane_widget = left_widget
        left_layout = QtWidgets.QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        # Stacked widget with alternative task views.
        self.task_view_stack = QtWidgets.QStackedWidget(left_widget)

        # ---- Tree view page (existing three-pane UI left side) ----
        tree_view_page = QtWidgets.QWidget(self.task_view_stack)
        tree_view_layout = QtWidgets.QVBoxLayout(tree_view_page)
        tree_view_layout.setContentsMargins(0, 0, 0, 0)
        tree_view_layout.setSpacing(0)

        self.task_tree = QtWidgets.QTreeWidget(tree_view_page)
        self.task_tree.setColumnCount(4)
        self.task_tree.setHeaderLabels(
            ["Name", "Project / Context", "Status", "Info"]
        )
        # Allow sorting by clicking on header columns.
        # Default order is still defined by _populate_tree (name/context),
        # but user can change it interactively.
        self.task_tree.setSortingEnabled(True)
        # Enable tree decoration to show hierarchy as in main browser.
        self.task_tree.setRootIsDecorated(True)
        self.task_tree.setAlternatingRowColors(True)
        self.task_tree.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.task_tree.itemDoubleClicked.connect(self._on_task_tree_item_double_clicked)
        tree_view_layout.addWidget(self.task_tree, 1)

        self.task_view_stack.addWidget(tree_view_page)
        left_layout.addWidget(self.task_view_stack, 1)

        # Task action buttons (shared for both Tree and Board selections).
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
        # Allow sorting by header click in Task files view.
        self.files_tree.setSortingEnabled(True)
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
        # Allow sorting by header click in Published snapshots view.
        self.snapshots_tree.setSortingEnabled(True)
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

        # Right pane: shot links + use_this_list (task mode); ilink lives here but stays hidden
        # until Collect linked (then shot block hides and ilink fills the pane).
        right_widget = QtWidgets.QWidget(splitter)
        right_layout = QtWidgets.QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        self._right_vert_split = QtWidgets.QSplitter(
            QtCore.Qt.Vertical, right_widget  # type: ignore[attr-defined]
        )

        # Inner vertical split: shot-linked tasks (top) vs asset metadata tree (bottom).
        self._shot_deps_vert_split = QtWidgets.QSplitter(
            QtCore.Qt.Vertical, self._right_vert_split  # type: ignore[attr-defined]
        )
        self._shot_deps_vert_split.setChildrenCollapsible(False)  # type: ignore[attr-defined]
        self._shot_deps_vert_split.setHandleWidth(6)
        self._shot_deps_vert_split.setStretchFactor(0, 1)
        self._shot_deps_vert_split.setStretchFactor(1, 2)

        shot_top_widget = QtWidgets.QWidget(self._shot_deps_vert_split)
        shot_top_layout = QtWidgets.QVBoxLayout(shot_top_widget)
        shot_top_layout.setContentsMargins(0, 0, 0, 0)
        shot_top_layout.setSpacing(4)
        shot_top_widget.setMinimumHeight(72)

        shot_links_header = QtWidgets.QLabel(
            "Shot-linked tasks (web Links: Task incoming/outgoing_links, same parent):",
            shot_top_widget,
        )
        shot_top_layout.addWidget(shot_links_header)

        self.shot_links_list = QtWidgets.QListWidget(shot_top_widget)
        self.shot_links_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.shot_links_list.itemSelectionChanged.connect(self._on_shot_link_selection_changed)
        # Match Board task cards: two-line items, comfortable row height.
        self.shot_links_list.setSpacing(3)
        self.shot_links_list.setWordWrap(True)
        shot_top_layout.addWidget(self.shot_links_list, 1)

        shot_bottom_widget = QtWidgets.QWidget(self._shot_deps_vert_split)
        shot_bottom_layout = QtWidgets.QVBoxLayout(shot_bottom_widget)
        shot_bottom_layout.setContentsMargins(0, 0, 0, 0)
        shot_bottom_layout.setSpacing(4)
        shot_bottom_widget.setMinimumHeight(96)

        use_this_header = QtWidgets.QLabel(
            "Components from asset metadata (lists + pairs; select a linked task above):",
            shot_bottom_widget,
        )
        shot_bottom_layout.addWidget(use_this_header)

        self.use_this_tree = QtWidgets.QTreeWidget(shot_bottom_widget)
        self.use_this_tree.setColumnCount(5)
        self.use_this_tree.setHeaderLabels(
            ["Asset / key", "Component id", "Available", "Locations", "Transfer"]
        )
        self.use_this_tree.setSortingEnabled(True)
        self.use_this_tree.setAlternatingRowColors(True)
        self.use_this_tree.itemChanged.connect(self._on_use_this_tree_item_changed)
        shot_bottom_layout.addWidget(self.use_this_tree, 1)

        use_this_btn_bar = QtWidgets.QHBoxLayout()
        use_this_btn_bar.addStretch(1)
        self.select_all_use_this_btn = QtWidgets.QPushButton(
            "Select all transferable", shot_bottom_widget
        )
        self.select_all_use_this_btn.clicked.connect(self._on_select_all_use_this_clicked)
        use_this_btn_bar.addWidget(self.select_all_use_this_btn)
        shot_bottom_layout.addLayout(use_this_btn_bar)

        self._shot_deps_vert_split.addWidget(shot_top_widget)
        self._shot_deps_vert_split.addWidget(shot_bottom_widget)

        self._shot_deps_widget = self._shot_deps_vert_split
        self._right_vert_split.addWidget(self._shot_deps_vert_split)

        ilink_widget = QtWidgets.QWidget(self._right_vert_split)
        ilink_layout = QtWidgets.QVBoxLayout(ilink_widget)
        ilink_layout.setContentsMargins(0, 0, 0, 0)
        ilink_layout.setSpacing(4)

        linked_label = QtWidgets.QLabel("Linked components (ilink):", ilink_widget)
        ilink_layout.addWidget(linked_label, 0)

        self.linked_tree = QtWidgets.QTreeWidget(ilink_widget)
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
        # Allow sorting by header click in Linked components view.
        self.linked_tree.setSortingEnabled(True)
        self.linked_tree.setRootIsDecorated(False)
        self.linked_tree.setAlternatingRowColors(True)
        ilink_layout.addWidget(self.linked_tree, 1)

        self._ilink_widget = ilink_widget
        self._right_vert_split.addWidget(ilink_widget)
        self._right_vert_split.setChildrenCollapsible(True)  # type: ignore[attr-defined]
        self._right_vert_split.setStretchFactor(0, 3)
        self._right_vert_split.setStretchFactor(1, 2)

        right_layout.addWidget(self._right_vert_split, 1)

        # Single transfer bar for both use_this_list (split mode) and ilink (collect-linked mode).
        right_transfer_bar = QtWidgets.QHBoxLayout()
        right_transfer_bar.addStretch(1)
        self.transfer_to_local_btn = QtWidgets.QPushButton("Transfer to local", right_widget)
        self.transfer_to_local_btn.clicked.connect(self._on_transfer_to_local_clicked)
        right_transfer_bar.addWidget(self.transfer_to_local_btn)
        self.transfer_target_info_label = QtWidgets.QLabel("(target: n/a)", right_widget)
        right_transfer_bar.addWidget(self.transfer_target_info_label)
        right_layout.addLayout(right_transfer_bar)

        splitter.addWidget(right_widget)

        # Task mode: only shot links + use_this (ilink hidden until Collect linked succeeds).
        self._set_right_pane_ilink_only(False)

        # So that all panes scale with the window and fill the frame (no empty stretch on the right).
        expanding = QtWidgets.QSizePolicy.Expanding  # type: ignore[attr-defined]
        preferred = QtWidgets.QSizePolicy.Preferred  # type: ignore[attr-defined]
        for w in (left_widget, middle_widget, right_widget):
            w.setSizePolicy(expanding, preferred)
        for tree in (
            self.task_tree,
            self.files_tree,
            self.snapshots_tree,
            self.linked_tree,
            self.use_this_tree,
        ):
            tree.setSizePolicy(expanding, expanding)

        # Stretch: left gets a solid share so it scales; middle and right fill the rest.
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        left_widget.setMinimumWidth(max(220, int(220 * self._content_scale_factor())))

        # ---------------- Board page (tasks grouped by status) ----------------
        # Board view lives in the same left pane as the tree, using the stacked widget.
        self._build_board_page()

        # Default view is Board: it becomes the primary task selection surface.
        try:
            self.view_mode_combo.blockSignals(True)
            if self.view_mode_combo.count() > 1:
                # Index 1 corresponds to "Board".
                self.view_mode_combo.setCurrentIndex(1)
                # Switch stacked view to Board (index 1).
                if self.task_view_stack.count() > 1:
                    self.task_view_stack.setCurrentIndex(1)
        finally:
            self.view_mode_combo.blockSignals(False)

        # Status label
        self.status_label = QtWidgets.QLabel("Ready", self)
        layout.addWidget(self.status_label)

        # Connect selection from tree view
        self.task_tree.itemSelectionChanged.connect(self._on_task_selection_changed)

    def showEvent(self, event: Any) -> None:  # type: ignore[override]
        """Set initial splitter sizes once so left pane and detail panes get a sensible share."""
        super().showEvent(event)
        if getattr(self, "_splitter_initial_sizes_set", True):
            return
        splitter = getattr(self, "_main_splitter", None)
        if splitter is not None and splitter.count() >= 3:
            total = splitter.width()
            if total > 100:
                scale = self._content_scale_factor()
                min_left = max(220, int(220 * scale))
                max_left = max(320, int(320 * scale))
                left = max(min_left, min(max_left, total // 4))
                rest = total - left
                mid = rest * 3 // 5
                right = rest - mid
                splitter.setSizes([left, mid, right])
                self._splitter_initial_sizes_set = True

        rvs = getattr(self, "_right_vert_split", None)
        if (
            rvs is not None
            and not getattr(self, "_right_vert_split_sizes_set", True)
            and rvs.height() > 80
            and not getattr(self, "_right_pane_ilink_only", False)
        ):
            h = rvs.height()
            iw = getattr(self, "_ilink_widget", None)
            if iw is not None and not iw.isVisible():
                rvs.setSizes([max(160, h), 0])
            else:
                rvs.setSizes([max(160, int(h * 0.55)), max(120, int(h * 0.45))])
            self._right_vert_split_sizes_set = True

        svs = getattr(self, "_shot_deps_vert_split", None)
        if (
            svs is not None
            and not self._shot_deps_vert_split_sizes_set
            and svs.height() > 120
            and not getattr(self, "_right_pane_ilink_only", False)
        ):
            ih = svs.height()
            # Upper: linked tasks; lower: metadata tree (user can drag the handle).
            svs.setSizes([max(100, int(ih * 0.34)), max(140, int(ih * 0.66))])
            self._shot_deps_vert_split_sizes_set = True

    def _set_right_pane_ilink_only(self, ilink_only: bool) -> None:
        """Toggle right pane: shot links + use_this only vs ilink only (after Collect linked)."""
        self._right_pane_ilink_only = bool(ilink_only)
        sdw = getattr(self, "_shot_deps_widget", None)
        iw = getattr(self, "_ilink_widget", None)
        rvs = getattr(self, "_right_vert_split", None)
        if sdw is None or rvs is None:
            return
        if ilink_only:
            sdw.hide()
            if iw is not None:
                iw.show()
            rvs.setStretchFactor(0, 0)
            rvs.setStretchFactor(1, 1)

            def _resize_ilink_full() -> None:
                h = max(rvs.height(), 120)
                rvs.setSizes([0, h])

            QtCore.QTimer.singleShot(0, _resize_ilink_full)
        else:
            if iw is not None:
                iw.hide()
            sdw.show()
            rvs.setStretchFactor(0, 1)
            rvs.setStretchFactor(1, 0)

            def _resize_shot_only() -> None:
                h = max(rvs.height(), 200)
                # All vertical space to shot deps; ilink hidden (no third empty panel).
                rvs.setSizes([h, 0])

            QtCore.QTimer.singleShot(0, _resize_shot_only)

    def _build_board_page(self) -> None:
        """Create Board view page (tasks grouped by status) inside task view stack."""
        board_page = QtWidgets.QWidget(self.task_view_stack)
        board_layout = QtWidgets.QVBoxLayout(board_page)
        board_layout.setContentsMargins(0, 0, 0, 0)
        board_layout.setSpacing(4)

        scroll = QtWidgets.QScrollArea(board_page)
        scroll.setWidgetResizable(True)

        container = QtWidgets.QWidget()
        self.board_layout = QtWidgets.QHBoxLayout(container)
        self.board_layout.setContentsMargins(4, 4, 4, 4)
        self.board_layout.setSpacing(8)

        scroll.setWidget(container)
        board_layout.addWidget(scroll, 1)

        self.board_container = container
        self._board_lists: Dict[str, QtWidgets.QListWidget] = {}
        self.task_view_stack.addWidget(board_page)

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

    # ------------------------------------------------------------------ Board helpers

    def _build_status_groups(self) -> Dict[str, List[Dict[str, Any]]]:
        """Group tasks by status_name for current project filter."""
        filtered_tasks = [
            t
            for t in self._all_tasks
            if (not self._current_project_id or t["project_id"] == self._current_project_id)
        ]

        groups: Dict[str, List[Dict[str, Any]]] = {}
        for t in filtered_tasks:
            status = (t.get("status_name") or "No Status").strip() or "No Status"
            groups.setdefault(status, []).append(t)

        # Sort tasks inside each status for stable display
        for status, tasks in groups.items():
            tasks.sort(
                key=lambda tt: (
                    (tt.get("project_name") or "").lower(),
                    (tt.get("parent_full_name") or "").lower(),
                    (tt.get("name") or "").lower(),
                )
            )
        return groups

    def _populate_board(self) -> None:
        """Populate Board view according to current project filter."""
        if not hasattr(self, "board_layout"):
            return

        # Clear previous columns
        while self.board_layout.count():
            item = self.board_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        self._board_lists = {}

        groups = self._build_status_groups()
        if not groups:
            self._apply_left_pane_sizing_for_view_mode(is_board=True)
            self._update_splitter_for_board()
            self._schedule_board_splitter_refresh()
            return

        # Optional status filter for Board view (e.g. only "In progress").
        filter_set: Optional[set[str]] = None
        if self._board_filter_statuses:
            filter_set = {
                s.strip().lower() for s in self._board_filter_statuses if s and s.strip()
            }

        # Deterministic order of statuses
        statuses = sorted(groups.keys(), key=lambda s: s.lower())

        for status in statuses:
            if filter_set is not None:
                norm_status = (status or "").strip().lower()
                if norm_status not in filter_set:
                    continue

            column_widget = QtWidgets.QWidget(self.board_container)
            column_layout = QtWidgets.QVBoxLayout(column_widget)
            column_layout.setContentsMargins(2, 2, 2, 2)
            column_layout.setSpacing(4)

            title = QtWidgets.QLabel(f"{status} ({len(groups[status])})", column_widget)
            title.setStyleSheet("font-weight: bold;")
            column_layout.addWidget(title)

            list_widget = QtWidgets.QListWidget(column_widget)
            list_widget.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
            list_widget.itemDoubleClicked.connect(self._on_board_item_double_clicked)
            list_widget.itemSelectionChanged.connect(
                lambda lw=list_widget: self._on_board_selection_changed(lw)
            )
            column_layout.addWidget(list_widget, 1)

            for task in groups[status]:
                text = task.get("name") or "<task>"
                ctx = task.get("parent_full_name") or task.get("project_name") or ""
                if ctx:
                    text = f"{text}\n{ctx}"
                item = QtWidgets.QListWidgetItem(text)
                item.setData(QtCore.Qt.UserRole, task)  # type: ignore[attr-defined]
                list_widget.addItem(item)

            self.board_layout.addWidget(column_widget)
            self._board_lists[status] = list_widget

        # Wide boards scroll inside the left pane QScrollArea; splitter share is capped.
        self._apply_left_pane_sizing_for_view_mode(is_board=True)
        self._update_splitter_for_board()
        self._schedule_board_splitter_refresh()

    def _schedule_board_splitter_refresh(self) -> None:
        """Re-apply board splitter after the window has a real width (standalone launch)."""
        if QtCore is None:
            return

        def _deferred() -> None:
            if not hasattr(self, "view_mode_combo"):
                return
            if self.view_mode_combo.currentText() != "Board":
                return
            self._update_splitter_for_board()

        QtCore.QTimer.singleShot(0, _deferred)

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

    def _content_scale_factor(self) -> float:
        """Scale factor for layout sizes (Windows DPI scaling 125%, 150%, 175%, etc.)."""
        try:
            # devicePixelRatioF() reflects OS scale (e.g. 1.75 for 175%).
            scale = float(self.devicePixelRatioF())  # type: ignore[attr-defined]
            # Ensure at least 1.25 so long names fit even if DPI is not reported.
            return max(1.25, scale)
        except Exception:
            return 1.25

    def _board_left_min_width(self) -> int:
        """Minimum width for the Board left column (splitter + widget).

        Using ``220 * devicePixelRatio`` as the floor makes 175% DPI (~385px) eat
        small standalone windows; blend part of the scale so the pane stays readable
        but leaves room for files / links columns.
        """
        scale = self._content_scale_factor()
        blended = 1.0 + (scale - 1.0) * 0.45
        return max(200, int(220 * blended))

    def _apply_left_pane_sizing_for_view_mode(self, is_board: bool) -> Optional[int]:
        """Board mode: record ideal board width; splitter caps share so center/right stay usable.

        Tree mode: left pane stretches horizontally.
        """
        left = getattr(self, "_left_pane_widget", None)
        if left is None:
            return None
        expanding = QtWidgets.QSizePolicy.Expanding  # type: ignore[attr-defined]
        preferred = QtWidgets.QSizePolicy.Preferred  # type: ignore[attr-defined]
        if is_board:
            # Ideal width if all status columns were visible without horizontal scroll.
            scale = self._content_scale_factor()
            num_cols = len(getattr(self, "_board_lists", {}))
            if num_cols == 0:
                num_cols = 1
            # Base 300px per column so "project.shots.taskname" fits; scale for DPI.
            board_col_width = int(300 * scale)
            board_col_spacing = int(12 * scale)
            board_extra = int(90 * scale)  # scrollbar, margins, list padding
            content_width = num_cols * board_col_width + (num_cols - 1) * board_col_spacing + board_extra
            self._board_desired_left_width = content_width
            # Do not lock min=max to content_width: narrow windows (e.g. standalone 900px)
            # would leave the task list taking half the frame. Extra columns scroll inside
            # the board QScrollArea.
            left.setMinimumWidth(self._board_left_min_width())
            left.setMaximumWidth(16777215)  # QWIDGETSIZE_MAX
            left.setSizePolicy(preferred, left.sizePolicy().verticalPolicy())
            return content_width
        else:
            self._board_desired_left_width = None
            left.setMinimumWidth(max(220, int(220 * self._content_scale_factor())))
            left.setMaximumWidth(16777215)  # QWIDGETSIZE_MAX
            left.setSizePolicy(expanding, left.sizePolicy().verticalPolicy())
            return None

    def _update_splitter_for_board(self) -> None:
        """Set main splitter so the board column gets min(desired width, capped fraction of window)."""
        left = getattr(self, "_left_pane_widget", None)
        splitter = getattr(self, "_main_splitter", None)
        if left is None or splitter is None or splitter.count() < 3:
            return
        total = splitter.width()
        if total < 280:
            return
        min_left = self._board_left_min_width()
        desired = getattr(self, "_board_desired_left_width", None)
        if desired is None:
            desired = min_left
        desired = max(min_left, int(desired))
        # Cap board pane: ~30% of width (42% was still too wide at 125%+ DPI).
        max_left_frac = max(min_left, int(total * 0.30))
        left_w = min(desired, max_left_frac)
        rest = total - left_w
        if rest < 200:
            left_w = max(min_left, total - 360)
            rest = total - left_w
        mid = rest * 3 // 5
        right = rest - mid
        splitter.setSizes([left_w, mid, right])

    def _on_view_mode_changed(self, index: int) -> None:
        """Handle switching between Tree and Board views (dropdown)."""
        if not hasattr(self, "task_view_stack"):
            return
        # Determine target view based on combo text: 0 = Tree, 1 = Board.
        use_board = self.view_mode_combo.currentText() == "Board"
        target_index = 1 if use_board else 0
        if 0 <= target_index < self.task_view_stack.count():
            self.task_view_stack.setCurrentIndex(target_index)
        self._apply_left_pane_sizing_for_view_mode(use_board)
        # Re-populate current view using already loaded tasks
        if use_board:
            self._populate_board()
        else:
            self._populate_tree()

    def _on_tab_changed(self, index: int) -> None:
        """Handle switching via tab click: populate view and sync dropdown."""
        if index == 1:
            # Board tab clicked — fill board and sync dropdown
            try:
                self.view_mode_combo.blockSignals(True)
                self.view_mode_combo.setCurrentIndex(1)
            finally:
                self.view_mode_combo.blockSignals(False)
            self._populate_board()
        elif index == 0:
            # Tree tab clicked — fill tree and sync dropdown
            try:
                self.view_mode_combo.blockSignals(True)
                self.view_mode_combo.setCurrentIndex(0)
            finally:
                self.view_mode_combo.blockSignals(False)
            self._populate_tree()

    def _on_task_tree_item_double_clicked(
        self, item: QtWidgets.QTreeWidgetItem, column: int  # type: ignore[name-defined]
    ) -> None:
        """On double-click on a task in Tree: set board filter to task status, switch to Board, focus task.

        Allows switching from a task in review (or other state) to other tasks by
        focusing the board column for the double-clicked task's status.
        """
        data = item.data(0, QtCore.Qt.UserRole) if item else None  # type: ignore[attr-defined]
        if not isinstance(data, dict) or not data.get("id"):
            return

        task_id = str(data["id"])
        status_name = (data.get("status_name") or "No Status").strip() or "No Status"
        norm_status = status_name.lower()

        self._board_filter_statuses = {norm_status}
        try:
            self.view_mode_combo.blockSignals(True)
            if self.view_mode_combo.count() > 1:
                self.view_mode_combo.setCurrentIndex(1)
            if hasattr(self, "task_view_stack") and self.task_view_stack.count() > 1:
                self.task_view_stack.setCurrentIndex(1)
        finally:
            self.view_mode_combo.blockSignals(False)

        self._populate_board()
        self._select_task_in_board_by_id(task_id)
        self._on_task_selected(data)

    def _on_task_selection_changed(self) -> None:
        """Handle selection change in task tree.

        TEMPORARY: snapshot loading disabled for performance profiling.
        Clear right panel, update status and, if task directory already
        exists, show file list. Do not create new folders at this stage.
        """
        current_item = self.task_tree.currentItem()
        if not current_item:
            return

        data = current_item.data(0, QtCore.Qt.UserRole)  # type: ignore[attr-defined]
        if not isinstance(data, dict):
            return

        self._on_task_selected(data)

    def _on_task_selected(self, task_data: Dict[str, Any]) -> None:
        """Common handler when a task is selected (tree or board)."""
        # Clear right panel
        self.files_tree.clear()
        self.snapshots_tree.clear()
        self.linked_tree.clear()
        self._clear_shot_deps_ui()
        self._set_right_pane_ilink_only(False)

        # By default task action buttons are disabled,
        # enable them only when a valid task is selected.
        self.create_scene_btn.setEnabled(False)
        self.get_snapshots_btn.setEnabled(False)
        self.open_scene_btn.setEnabled(False)

        task_name = task_data.get("name") or task_data.get("id") or "<task>"
        self._set_status(f"Selected task: {task_name}")

        # Enable actions only for valid task.
        self.create_scene_btn.setEnabled(True)
        self.get_snapshots_btn.setEnabled(True)

        # If working root is configured and directory already exists, show files.
        if self._workdir_root:
            self._populate_task_files_for_data(task_data, create_if_missing=False)

        self._load_shot_linked_tasks_for_selection(task_data)

    def _on_board_item_double_clicked(self, item: QtWidgets.QListWidgetItem) -> None:  # type: ignore[misc]
        """Handle double-click on task in Board view."""
        data = item.data(QtCore.Qt.UserRole)  # type: ignore[attr-defined]
        if not isinstance(data, dict):
            return

        # Select task and switch to Tree view to show details / files / snapshots.
        self._on_task_selected(data)

        task_id = data.get("id")
        if task_id:
            try:
                self.view_mode_combo.setCurrentText("Tree")
            except Exception:
                pass
            # Ensure tree is populated and try to focus corresponding task.
            self._populate_tree()
            self._select_task_in_tree_by_id(str(task_id))

    def _on_board_selection_changed(self, source_list: QtWidgets.QListWidget) -> None:  # type: ignore[misc]
        """Ensure only one task is selected across all Board columns."""
        if not hasattr(self, "_board_lists"):
            return
        # If nothing is selected in this list, nothing to do.
        if not source_list.selectedItems():
            return

        # Clear selection in all other lists to keep exactly one selected task.
        for lw in self._board_lists.values():
            if lw is source_list:
                continue
            lw.blockSignals(True)
            lw.clearSelection()
            lw.blockSignals(False)

        # Use the currently selected item as the active task and update details pane.
        current = source_list.currentItem()
        if current is None:
            return
        data = current.data(QtCore.Qt.UserRole)  # type: ignore[attr-defined]
        if isinstance(data, dict):
            self._on_task_selected(data)

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
            'parent.id, parent.full_name, status.name, project.status.name, link '
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

            parent_entity = t.get("parent") or {}
            parent_id_val = parent_entity.get("id")
            parent_id_str = str(parent_id_val) if parent_id_val else None

            self._all_tasks.append(
                {
                    "id": t["id"],
                    "name": t.get("name", ""),
                    "project_name": proj_name,
                    "project_id": proj_id,
                    "parent_id": parent_id_str,
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

        # Populate current view (Tree or Board)
        t_view_start = time.perf_counter()
        if hasattr(self, "view_mode_combo") and self.view_mode_combo.currentText() == "Board":
            self._populate_board()
        else:
            self._populate_tree()
        logger.info(
            "UserTasksWidget: task view populate took %.3f s",
            time.perf_counter() - t_view_start,
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

        # After (re)loading tasks for the correct project, try to find the task
        # in the loaded list and adjust Board/Tree views accordingly.
        found_task = None
        for t in self._all_tasks:
            if str(t.get("id")) == task_id:
                found_task = t
                break

        if found_task is not None:
            status_name = (found_task.get("status_name") or "No Status").strip() or "No Status"
            norm_status = status_name.lower()

            # Refine Board filter to only the status of initial task so board shows
            # the lane that contains this task.
            self._board_filter_statuses = {norm_status} if norm_status else None

            # Make Board the active view and repopulate it with the refined filter.
            try:
                if hasattr(self, "view_mode_combo"):
                    self.view_mode_combo.blockSignals(True)
                    if self.view_mode_combo.count() > 1:
                        # Index 1 corresponds to "Board".
                        self.view_mode_combo.setCurrentIndex(1)
                        if hasattr(self, "task_view_stack") and self.task_view_stack.count() > 1:
                            self.task_view_stack.setCurrentIndex(1)
            finally:
                if hasattr(self, "view_mode_combo"):
                    self.view_mode_combo.blockSignals(False)

            self._populate_board()
            if self._select_task_in_board_by_id(task_id):
                logger.info(
                    "UserTasksWidget: auto-selected task %s in Board view from initial context id",
                    task_id,
                )

            # Also populate Tree and select the same task there so that when user
            # switches to Tree view, the selection and context are consistent.
            self._populate_tree()
            if self._select_task_in_tree_by_id(task_id):
                logger.info(
                    "UserTasksWidget: auto-selected task %s in Tree view from initial context id",
                    task_id,
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

    def _select_task_in_board_by_id(self, task_id: str) -> bool:
        """Find and select task in Board view by id. Returns True if successful."""
        if not hasattr(self, "_board_lists"):
            return False
        for lw in self._board_lists.values():
            if lw is None:
                continue
            for row in range(lw.count()):
                item = lw.item(row)
                if item is None:
                    continue
                data = item.data(QtCore.Qt.UserRole)  # type: ignore[attr-defined]
                if isinstance(data, dict) and str(data.get("id")) == task_id:
                    lw.setCurrentItem(item)
                    try:
                        lw.scrollToItem(item)
                    except Exception:
                        pass
                    return True
        return False

    # ------------------------------------------------------------------ Snapshot loading

    def _load_snapshots_for_task(self, task_id: str, task_data: Dict[str, Any]) -> None:
        """Load snapshot components (.hip) published from the given task."""
        self.snapshots_tree.clear()
        self.linked_tree.clear()
        self._set_right_pane_ilink_only(False)

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

    def _update_transfer_target_label(
        self,
        location: Optional[Any],
        label_widget: Optional[Any] = None,
    ) -> None:
        """Update label next to transfer button(s)."""
        widget = label_widget
        if widget is None:
            widget = getattr(self, "transfer_target_info_label", None)
        if widget is None:
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
        widget.setText(text)

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
        self._set_right_pane_ilink_only(False)

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
            self._set_right_pane_ilink_only(False)
        else:
            self._set_status(f"Collected {total} linked component(s) from ilink.")
            self._set_right_pane_ilink_only(True)

    # ------------------------------------------------------------------ Shot-linked tasks + use_this_list

    def _clear_shot_deps_ui(self) -> None:
        """Clear shot link list and use_this tree (no network)."""
        if hasattr(self, "shot_links_list"):
            self.shot_links_list.clear()
        if hasattr(self, "use_this_tree"):
            self.use_this_tree.clear()

    @staticmethod
    def _typed_context_type_name(other: Dict[str, Any]) -> str:
        """Task type label from entity (type or object_type, depending on schema)."""
        try:
            t = (other.get("type") or {}).get("name") or ""
        except Exception:
            t = ""
        if t:
            return str(t)
        try:
            return str((other.get("object_type") or {}).get("name") or "")
        except Exception:
            return ""

    def _query_task_parent_id(self, other_task_id: str) -> Optional[str]:
        """Resolve Task.parent.id when link projection did not include parent."""
        if not self.session or not other_task_id:
            return None
        try:
            row = self.session.query(
                f'select parent.id from Task where id is "{other_task_id}"'
            ).first()
        except Exception as exc:
            logger.debug(
                "UserTasksWidget: parent.id lookup for Task %s failed: %s",
                other_task_id,
                exc,
            )
            return None
        if not row:
            return None
        par = row.get("parent") or {}
        pid = par.get("id")
        return str(pid) if pid else None

    def _append_linked_task_rows(
        self,
        results: List[Dict[str, Any]],
        seen: set[str],
        task_id: str,
        rows: Any,
        direction: str,
        field: str,
        parent_id: str,
        *,
        filter_parent_in_python: bool,
    ) -> None:
        """Merge query rows into *results*; optionally keep only same Task.parent."""
        for row in rows or []:
            other = row.get(field) or {}
            oid = other.get("id")
            if not oid:
                continue
            if filter_parent_in_python:
                opar = other.get("parent") or {}
                opid = opar.get("id")
                if opid is None:
                    opid = self._query_task_parent_id(str(oid))
                if opid is None:
                    continue
                if str(opid) != str(parent_id):
                    continue
            sid = str(oid)
            if sid == str(task_id) or sid in seen:
                continue
            # ``type.name`` on Task is usually pipeline type (Animation, Layout), not "Task".
            type_name = self._typed_context_type_name(other)
            seen.add(sid)
            results.append(
                {
                    "id": sid,
                    "name": other.get("name") or sid,
                    "type_name": type_name,
                    "direction": direction,
                }
            )

    def _fetch_same_parent_task_links(
        self,
        task_id: str,
        parent_id: Optional[str],
    ) -> List[Dict[str, Any]]:
        """Linked tasks as on ftrack web Links tab (same shot parent).

        Per ftrack Developer Hub "Using entity links":
        TypedContext (including Task) has ``incoming_links`` and ``outgoing_links``;
        each link has ``from`` and ``to``. For incoming links to this task,
        ``link['to']`` is this task and ``link['from']`` is the linked context.
        See: https://developer.ftrack.com/api-clients/examples/entity-links
        """
        if not self.session or not task_id or not parent_id:
            return []

        tid = str(task_id)
        pid = str(parent_id)
        results: List[Dict[str, Any]] = []
        seen: set[str] = set()

        # Try several projections: object_type in nested select breaks some servers.
        query_variants = [
            (
                f"select id, "
                f"incoming_links.from.id, incoming_links.from.name, "
                f"incoming_links.from.type.name, incoming_links.from.parent.id, "
                f"outgoing_links.to.id, outgoing_links.to.name, "
                f"outgoing_links.to.type.name, outgoing_links.to.parent.id "
                f'from Task where id is "{tid}"'
            ),
            (
                f'select id, incoming_links, outgoing_links from Task where id is "{tid}"'
            ),
        ]

        task: Any = None
        for q_idx, q in enumerate(query_variants):
            try:
                task = self.session.query(q).first()
            except Exception as exc:
                logger.debug(
                    "UserTasksWidget: Task links query variant %s failed: %s",
                    q_idx,
                    exc,
                )
                task = None
                continue
            if task is not None:
                break

        if task is None:
            try:
                task = self.session.get("Task", tid)
            except Exception as exc:
                logger.warning("UserTasksWidget: session.get(Task) failed: %s", exc)
                return []

        def _consume_links(links: Any, direction: str, other_key: str) -> None:
            if not links:
                return
            try:
                links = list(links)
            except Exception:
                pass
            for link in links:
                try:
                    other = link.get(other_key) or {}
                except Exception:
                    continue
                self._append_linked_task_rows(
                    results,
                    seen,
                    tid,
                    [{other_key: other}],
                    direction,
                    other_key,
                    pid,
                    filter_parent_in_python=True,
                )

        try:
            _consume_links(task.get("incoming_links"), "incoming", "from")
            _consume_links(task.get("outgoing_links"), "outgoing", "to")
        except Exception as exc:
            logger.warning(
                "UserTasksWidget: reading Task incoming_links/outgoing_links failed: %s",
                exc,
            )

        results.sort(key=lambda r: (r.get("name") or "").lower())
        return results

    def _load_shot_linked_tasks_for_selection(self, task_data: Dict[str, Any]) -> None:
        """Populate shot-linked task list when user selects a task."""
        self._clear_shot_deps_ui()
        if not hasattr(self, "shot_links_list"):
            return

        task_id = str(task_data.get("id") or "").strip()
        parent_id = task_data.get("parent_id")
        if not task_id:
            return

        if not parent_id:
            tip = QtWidgets.QListWidgetItem(
                "(Selected task has no Task.parent id; cannot filter same-shot links.)"
            )
            tip.setFlags(QtCore.Qt.NoItemFlags)  # type: ignore[attr-defined]
            self.shot_links_list.addItem(tip)
            self._set_status("Task has no parent id; shot links need parent context.")
            return

        self._set_status("Loading shot-level linked tasks...")
        rows = self._fetch_same_parent_task_links(task_id, str(parent_id))

        if not rows:
            self._set_status(
                "No linked tasks with the same parent (web Links / incoming_links & outgoing_links)."
            )
            return

        shot_ctx = task_data.get("parent_full_name") or task_data.get("project_name") or ""
        scale = self._content_scale_factor()
        row_h = max(40, int(40 * scale))

        for row in rows:
            name = row.get("name") or row["id"]
            type_name = (row.get("type_name") or "").strip()
            direction = (row.get("direction") or "").strip()
            line2: List[str] = []
            if shot_ctx:
                line2.append(shot_ctx)
            if type_name:
                line2.append(type_name)
            if direction:
                line2.append(direction.capitalize())
            text = f"{name}\n{' · '.join(line2)}" if line2 else name
            lw = QtWidgets.QListWidgetItem(text)
            lw.setData(QtCore.Qt.UserRole, row)  # type: ignore[attr-defined]
            try:
                lw.setSizeHint(QtCore.QSize(0, row_h))  # type: ignore[attr-defined,call-arg]
            except Exception:
                pass
            self.shot_links_list.addItem(lw)

        self._set_status(f"{len(rows)} shot-linked task(s). Select one for use_this_list.")

    def _on_shot_link_selection_changed(self) -> None:
        """Load use_this_list for the linked task selected in shot_links_list."""
        if not hasattr(self, "use_this_tree") or not hasattr(self, "shot_links_list"):
            return
        items = self.shot_links_list.selectedItems()
        if not items:
            self.use_this_tree.clear()
            return
        data = items[0].data(QtCore.Qt.UserRole)  # type: ignore[attr-defined]
        if not isinstance(data, dict) or not data.get("id"):
            return
        self._load_use_this_for_linked_task(str(data["id"]))

    def _query_assets_for_linked_task(self, linked_task_id: str) -> List[Any]:
        """Resolve Assets for a task for ``use_this_list`` (stored on Asset.metadata).

        ftrack links tasks to publish data via ``AssetVersion.task``; the parent of a
        version is the ``Asset``. Query versions for the task, collect distinct
        ``asset`` dicts, then read ``use_this_list`` from ``Asset.metadata``.
        """
        if not self.session:
            return []
        tid = str(linked_task_id).strip()
        if not tid:
            return []

        seen: set[str] = set()
        assets: List[Any] = []

        def _add_asset_entity(a: Any) -> None:
            if not isinstance(a, dict):
                return
            aid = a.get("id")
            if not aid:
                return
            sid = str(aid)
            if sid in seen:
                return
            seen.add(sid)
            assets.append(a)

        try:
            versions = self.session.query(
                f'select asset.id, asset.name, asset.metadata '
                f'from AssetVersion where task.id is "{tid}"'
            ).all()
        except Exception as exc:
            logger.warning(
                "UserTasksWidget: AssetVersion query for task %s failed: %s",
                tid,
                exc,
            )
            versions = []

        for v in versions or []:
            _add_asset_entity(v.get("asset") or {})

        return assets

    def _parse_asset_metadata_keyed_component_blob(self, raw: Any) -> Dict[str, str]:
        """Parse ``use_this_list`` / ``latest_published_list`` value: JSON or dict, key -> component id."""
        if raw is None:
            return {}
        try:
            if isinstance(raw, str):
                use_map = json.loads(raw)
            elif isinstance(raw, dict):
                use_map = dict(raw)
            else:
                return {}
        except Exception:
            return {}
        if not isinstance(use_map, dict):
            return {}
        use_map.pop("status_note", None)
        clean: Dict[str, str] = {}
        for k, v in use_map.items():
            ks = str(k).strip()
            vs = str(v).strip()
            if ks and vs:
                clean[ks] = vs
        return clean

    def _metadata_flat_component_pairs(self, meta: Mapping[str, Any]) -> Dict[str, str]:
        """Flat Asset.metadata entries ``key -> component_id`` (transitional, no list blobs).

        Skips structured keys (``use_this_list``, etc.). Numeric keys (``\"0\"``, ``\"1\"``)
        accept any non-empty value, matching legacy ilink-style metadata.
        """
        out: Dict[str, str] = {}
        for k, v in meta.items():
            ks = str(k).strip()
            if not ks or ks.lower() in _ASSET_METADATA_NON_PAIR_KEYS:
                continue
            if v is None:
                continue
            if isinstance(v, (dict, list, bytes)):
                continue
            vs = str(v).strip()
            if not vs:
                continue
            if ks.isdigit():
                out[ks] = vs
                continue
            if _looks_like_ftrack_entity_id(vs):
                out[ks] = vs
        return out

    def _build_component_map_from_asset_metadata(self, meta: Mapping[str, Any]) -> Dict[str, str]:
        """Merge ``use_this_list``, ``latest_published_list``, and flat metadata pairs.

        ``use_this_list`` wins over ``latest_published_list`` on the same key; flat pairs
        only add keys not already set from either list blob.
        """
        combined: Dict[str, str] = {}
        combined.update(self._parse_asset_metadata_keyed_component_blob(meta.get("use_this_list")))
        for k, v in self._parse_asset_metadata_keyed_component_blob(
            meta.get("latest_published_list")
        ).items():
            if k not in combined:
                combined[k] = v
        for k, v in self._metadata_flat_component_pairs(meta).items():
            if k not in combined:
                combined[k] = v
        return combined

    def _load_use_this_for_linked_task(self, linked_task_id: str) -> None:
        """Show Assets on linked task and component ids from metadata (lists + flat pairs)."""
        if not self.session or not hasattr(self, "use_this_tree"):
            return

        self._use_this_tree_syncing = True
        self.use_this_tree.blockSignals(True)
        self.use_this_tree.clear()
        self.use_this_tree.blockSignals(False)
        self._use_this_tree_syncing = False

        locations = self._get_accessible_locations()
        by_location_id: Dict[str, Any] = {}
        for loc in locations:
            lid = loc.get("id")
            if lid:
                by_location_id[str(lid)] = loc

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

        accessible_location_ids = {str(loc.get("id")) for loc in locations if loc.get("id")}

        assets = self._query_assets_for_linked_task(linked_task_id)
        if not assets:
            self._set_status(
                "No assets for this task (no AssetVersions linked to this task)."
            )
            return

        comp_ids_flat: List[str] = []
        per_asset: List[tuple[Any, Dict[str, str]]] = []

        for asset_entity in assets or []:
            meta = asset_entity.get("metadata") or {}
            if not isinstance(meta, Mapping):
                meta = {}
            clean = self._build_component_map_from_asset_metadata(meta)
            for _k, cid in clean.items():
                comp_ids_flat.append(cid)
            per_asset.append((asset_entity, clean))

        comp_locations_map: Dict[str, List[Dict[str, str]]] = {}
        if comp_ids_flat:
            comp_locations_map = self._get_component_locations_for_ids(comp_ids_flat)
            filtered_clm: Dict[str, List[Dict[str, str]]] = {}
            for comp_id, loc_list in comp_locations_map.items():
                filtered_locs = [
                    loc_entry
                    for loc_entry in loc_list
                    if str(loc_entry.get("id", "")) in accessible_location_ids
                ]
                if filtered_locs:
                    filtered_clm[comp_id] = filtered_locs
            comp_locations_map = filtered_clm

        total_rows = 0
        self._use_this_tree_syncing = True
        self.use_this_tree.setSortingEnabled(False)
        try:
            for asset_entity, use_map in per_asset:
                aid = str(asset_entity.get("id") or "")
                aname = asset_entity.get("name") or aid or "<asset>"
                asset_item = QtWidgets.QTreeWidgetItem([aname, aid, "", "", ""])
                asset_item.setData(
                    0,
                    QtCore.Qt.UserRole,
                    {"role": "asset", "asset_id": aid},
                )  # type: ignore[attr-defined]
                af = asset_item.flags()
                af |= QtCore.Qt.ItemIsUserCheckable  # type: ignore[attr-defined]
                asset_item.setFlags(af)
                asset_item.setCheckState(4, QtCore.Qt.Unchecked)  # type: ignore[attr-defined]

                if not use_map:
                    empty = QtWidgets.QTreeWidgetItem(
                        ["(no component keys in metadata)", "", "-", "-", ""]
                    )
                    empty.setFlags(QtCore.Qt.ItemIsEnabled)  # type: ignore[attr-defined]
                    asset_item.addChild(empty)
                    self.use_this_tree.addTopLevelItem(asset_item)
                    continue

                for comp_key, cid in sorted(use_map.items(), key=lambda kv: kv[0].lower()):
                    self._append_use_this_component_row(
                        asset_item,
                        comp_key,
                        cid,
                        by_location_id,
                        comp_locations_map,
                        target_loc_id,
                        accessible_location_ids,
                    )
                    total_rows += 1

                any_checkable = False
                for j in range(asset_item.childCount()):
                    ch = asset_item.child(j)
                    if ch.flags() & QtCore.Qt.ItemIsUserCheckable:  # type: ignore[attr-defined]
                        any_checkable = True
                        break
                if not any_checkable:
                    af_plain = asset_item.flags()
                    af_plain &= ~QtCore.Qt.ItemIsUserCheckable  # type: ignore[attr-defined]
                    asset_item.setFlags(af_plain)

                self.use_this_tree.addTopLevelItem(asset_item)
                asset_item.setExpanded(True)

        finally:
            self.use_this_tree.setSortingEnabled(True)
            self._use_this_tree_syncing = False

        if total_rows == 0:
            self._set_status(
                "Linked task has Assets but no component ids "
                "(use_this_list / latest_published_list / flat metadata pairs)."
            )
        else:
            self._set_status(
                f"Asset metadata: {total_rows} component row(s) "
                "(lists + pairs). Use asset row checkbox to select all transferable in that asset."
            )

    def _append_use_this_component_row(
        self,
        asset_item: QtWidgets.QTreeWidgetItem,  # type: ignore[name-defined]
        comp_key: str,
        component_id: str,
        by_location_id: Dict[str, Any],
        comp_locations_map: Dict[str, List[Dict[str, str]]],
        target_loc_id: Optional[str],
        accessible_location_ids: set[str],
    ) -> None:
        """Add child row under *asset_item* for one use_this_list component."""
        loc_entries = comp_locations_map.get(str(component_id), [])

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

        available = "No"

        linked_comp = None
        try:
            linked_comp = self.session.get("Component", str(component_id))
        except Exception as exc:
            logger.debug("UserTasksWidget: get Component %s: %s", component_id, exc)

        if linked_comp:
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
                    else:
                        available = "No"
                    break
                except Exception:
                    continue

        already_in_target = False
        if target_loc_id is not None:
            try:
                already_in_target = any(
                    str(entry.get("id")) == target_loc_id for entry in loc_entries
                )
            except Exception:
                already_in_target = False

        has_accessible_source = False
        if not already_in_target:
            for entry in loc_entries:
                lid = entry.get("id")
                if lid and str(lid) != target_loc_id and str(lid) in accessible_location_ids:
                    has_accessible_source = True
                    break

        child = QtWidgets.QTreeWidgetItem(
            [
                comp_key,
                str(component_id),
                available,
                locations_str,
                "",
            ]
        )
        child.setData(
            0,
            QtCore.Qt.UserRole,
            {"role": "component", "component_id": str(component_id)},
        )  # type: ignore[attr-defined]
        cf = child.flags()
        cf |= QtCore.Qt.ItemIsUserCheckable  # type: ignore[attr-defined]
        child.setFlags(cf)

        if already_in_target or not has_accessible_source:
            cf2 = child.flags()
            cf2 &= ~QtCore.Qt.ItemIsUserCheckable  # type: ignore[attr-defined]
            child.setFlags(cf2)
        else:
            default_state = (
                QtCore.Qt.Checked
                if available != "Yes"
                else QtCore.Qt.Unchecked
            )  # type: ignore[attr-defined]
            child.setCheckState(4, default_state)

    def _on_use_this_tree_item_changed(
        self,
        item: QtWidgets.QTreeWidgetItem,  # type: ignore[name-defined]
        column: int,
    ) -> None:
        """When asset row Transfer column toggles, sync checkable children."""
        if self._use_this_tree_syncing or column != 4:
            return
        if not hasattr(self, "use_this_tree"):
            return

        meta = item.data(0, QtCore.Qt.UserRole)  # type: ignore[attr-defined]
        if not isinstance(meta, dict) or meta.get("role") != "asset":
            return
        if not (item.flags() & QtCore.Qt.ItemIsUserCheckable):  # type: ignore[attr-defined]
            return

        state = item.checkState(4)
        self._use_this_tree_syncing = True
        try:
            for i in range(item.childCount()):
                ch = item.child(i)
                if ch.flags() & QtCore.Qt.ItemIsUserCheckable:  # type: ignore[attr-defined]
                    ch.setCheckState(4, state)
        finally:
            self._use_this_tree_syncing = False

    def _on_select_all_use_this_clicked(self) -> None:
        """Check Transfer for components that are not available locally but can transfer."""
        if not hasattr(self, "use_this_tree"):
            return
        root = self.use_this_tree.invisibleRootItem()
        self._use_this_tree_syncing = True
        try:
            for i in range(root.childCount()):
                parent_it = root.child(i)
                for j in range(parent_it.childCount()):
                    ch = parent_it.child(j)
                    if not (ch.flags() & QtCore.Qt.ItemIsUserCheckable):  # type: ignore[attr-defined]
                        continue
                    if ch.text(2) != "Yes":
                        ch.setCheckState(4, QtCore.Qt.Checked)  # type: ignore[attr-defined]
        finally:
            self._use_this_tree_syncing = False

    def _collect_checked_use_this_component_ids(self) -> List[str]:
        """Checked component rows under use_this_tree (column 4)."""
        ids: List[str] = []
        if not hasattr(self, "use_this_tree"):
            return ids
        root = self.use_this_tree.invisibleRootItem()
        for i in range(root.childCount()):
            parent_it = root.child(i)
            for j in range(parent_it.childCount()):
                ch = parent_it.child(j)
                if ch.checkState(4) != QtCore.Qt.Checked:  # type: ignore[attr-defined]
                    continue
                if not (ch.flags() & QtCore.Qt.ItemIsUserCheckable):  # type: ignore[attr-defined]
                    continue
                meta = ch.data(0, QtCore.Qt.UserRole)  # type: ignore[attr-defined]
                if isinstance(meta, dict) and meta.get("component_id"):
                    ids.append(str(meta["component_id"]))
                else:
                    txt = ch.text(1).strip()
                    if txt:
                        ids.append(txt)
        return ids

    def _collect_checked_linked_tree_component_ids(self) -> List[str]:
        """Return component ids for rows checked in linked_tree (column 7)."""
        selected_ids: List[str] = []
        root_count = self.linked_tree.topLevelItemCount()
        for i in range(root_count):
            item = self.linked_tree.topLevelItem(i)
            # Column "To transfer" now has index 7.
            if item.checkState(7) == QtCore.Qt.Checked:  # type: ignore[attr-defined]
                comp_id = item.data(0, QtCore.Qt.UserRole)
                if comp_id:
                    selected_ids.append(str(comp_id))
        return selected_ids

    def _start_transfer_jobs_for_component_ids(
        self,
        selected_ids: List[str],
        result_label_word: str = "component",
    ) -> None:
        """Run TransferWorker batches for the given component ids (ilink + use_this_list)."""
        if not selected_ids:
            self._set_status("No components selected for transfer.")
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
                "No components can be transferred: all either missing in source locations or already in target."
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
            f"Initiated transfer for {total_planned} {result_label_word}(s) to {to_location_name}."
        )

    def _on_transfer_to_local_clicked(self) -> None:
        """Transfer checked components: ilink list after Collect linked, else use_this_list."""
        if getattr(self, "_right_pane_ilink_only", False):
            selected_ids = self._collect_checked_linked_tree_component_ids()
            logger.info("UserTasksWidget: Transfer to local (ilink): %r", selected_ids)
            self._start_transfer_jobs_for_component_ids(
                selected_ids,
                result_label_word="linked component",
            )
        else:
            selected_ids = self._collect_checked_use_this_component_ids()
            logger.info("UserTasksWidget: Transfer to local (use_this_list): %r", selected_ids)
            self._start_transfer_jobs_for_component_ids(
                selected_ids,
                result_label_word="use_this component",
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
