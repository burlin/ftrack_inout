# User Tasks — Logic Overview

This document describes the logic of the **User Tasks** feature in `ftrack_inout`: data flow, UI, actions, and DCC integration.

---

## 1. Purpose and Entry Points

**User Tasks** shows tasks assigned to the current ftrack user (`session.api_user`) and lets them:

- Filter by project
- View tasks as Tree or Board (by status)
- Create/open task scenes in DCC
- Load published snapshots and linked components (ilink)
- Copy snapshots locally and transfer linked components to local

**Entry points:**

| Entry | Module / File | Notes |
|-------|----------------|--------|
| Standalone / CLI | `run_user_tasks_launcher.py` | `python -m ftrack_inout.browser.run_user_tasks_launcher [--task-id=ID] [--dcc=NAME]` |
| External wrapper | `tools/run_user_tasks.py` | Bootstraps env, then calls `run_user_tasks_launcher.main()` |
| Maya | `ftrack-framework-maya-24.11.1/.../mroya_maya_taskhub_launcher.py` | Opens `UserTasksWidget` with `MayaUserTasksHandlers` |
| Houdini | Houdini package launcher | Opens widget with `HoudiniUserTasksHandlers` |

---

## 2. Startup Flow (Launcher)

**File:** `browser/run_user_tasks_launcher.py`

1. **CLI parsing**  
   `_parse_cli_args(argv)` → `(task_id, dcc)` from `--task-id=...` and `--dcc=...`.  
   `dcc` is reserved for future use.

2. **Session and API**  
   - `get_shared_session()` from `ftrack_inout.common.session_factory` (shared cache with browser/DCC).  
   - `SimpleFtrackApiClient(session=session)` — same session, no duplicate connection.

3. **Qt and widget**  
   - Create/reuse `QApplication`.  
   - `UserTasksWidget(api_client=api_client, initial_task_id=task_id)`.  
   - No `dcc_handlers` here; DCC-specific launchers (Maya/Houdini) inject handlers when they create the widget.

4. **Return**  
   - `run_user_tasks()` returns exit code; `main()` uses it for `SystemExit`.

---

## 3. UserTasksWidget — Core State

**File:** `browser/user_tasks_widget.py`

| State | Meaning |
|-------|--------|
| `self.api` | `SimpleFtrackApiClient` (session, cache, helpers). |
| `self.session` | ftrack session from `api.get_session()` or `api.session`. |
| `self._all_tasks` | List of task dicts for current project (or all). |
| `self._active_projects` | `{project_id: project_name}` for projects with `status == "active"`. |
| `self._current_project_id` | Selected project filter; `None` = "All Projects". |
| `self._api_user` | Current user login from `session.api_user`. |
| `self._initial_task_id` | Task to focus on open: from constructor or `FTRACK_CONTEXTID`. |
| `self._workdir_root` | Root for task dirs from `FTRACK_WORKDIR`. |
| `self._dcc_handlers` | Optional `UserTasksDccHandlers`: create scene, open scene, etc. |
| `self._board_filter_statuses` | Board view: restrict columns to these statuses; `None` = all. |

---

## 4. Data Loading

### 4.1 Initial load (`_load_tasks`)

1. Clear tree and project combo; add "All Projects".
2. **Session check:** no session → status "No ftrack session", return.
3. **Current user:** `session.api_user` → `self._api_user`. Missing → status and return.
4. **Active projects:**  
   `session.query('Project where status is "active"').all()` → `_active_projects` and allowed project set.
5. **Project combo:** fill from `_active_projects` (or from existing `_all_tasks` if no active list), sorted by name.
6. **Initial project:**  
   From QSettings `last_project_id` if valid; else first project in list.  
   Set `_current_project_id` and combo without emitting.
7. **Tasks for current project:** `_load_tasks_for_current_project()`.
8. **Focus initial task:** `_maybe_focus_initial_task()` if `_initial_task_id` set.

### 4.2 Tasks per project (`_load_tasks_for_current_project`)

1. **Query:**  
   `Task where assignments.resource.username is "<api_user>"`  
   optionally `and project.id is "<_current_project_id>"`.  
   Select: `id, name, project.name, project.id, parent.full_name, status.name, project.status.name, link`.

2. **Filter:**  
   Drop tasks whose project is not in `_active_projects` (if that list is non-empty).

3. **Transform to dicts:**  
   For each task: `id`, `name`, `project_name`, `project_id`, `parent_full_name`, `context_segments` (from `link`), `status_name`, `due`, `bid` → `_all_tasks`.

4. **UI:**  
   If view mode is Board → `_populate_board()`, else `_populate_tree()`.

### 4.3 Focus initial task (`_maybe_focus_initial_task`)

1. If no `_initial_task_id` or session → return.
2. Try to find task in `_all_tasks` by id.
3. If not found: `session.get("Task", task_id)` and read `project_id` from entity.
4. If project differs from `_current_project_id`: set project, update combo, call `_load_tasks_for_current_project()` again.
5. Find task again in `_all_tasks`.  
   - If found: set `_board_filter_statuses = {status of that task}`, switch to Board, `_populate_board()`, select task in Board and in Tree.  
   - If not found: status message that DCC task is not assigned to user.
6. Clear `_initial_task_id` so it is not applied again.

---

## 5. UI Structure

- **Toolbar:** Project combo, Refresh, View mode (Tree / Board).
- **Left pane:**  
  - Stacked: **Tree** (project → context → task) and **Board** (columns = statuses, items = tasks).  
  - Buttons: "Create Task Scene", "Get Published Snapshots".
- **Middle pane:**  
  - Task files tree (local files for selected task).  
  - "Open Scene".  
  - Published snapshots tree.  
  - "Copy to local", "Collect linked".
- **Right pane:**  
  - Linked components (ilink) tree (Asset, Version, Component, Available, To transfer, etc.).  
  - "Transfer to local" + target location label.
- **Status line** at bottom.

Selection in Tree or Board sets the “current task”; middle/right panes react to that.

---

## 6. Task Selection and Detail Loading

- **Tree:** `task_tree.itemSelectionChanged` → `_on_task_selection_changed` → take `UserRole` dict → `_on_task_selected(task_data)`.
- **Board:**  
  - Single selection across columns in `_on_board_selection_changed`.  
  - Double-click → `_on_task_selected` + switch to Tree and select same task in tree.
- **`_on_task_selected(task_data)`:**  
  - Clear files/snapshots/linked trees.  
  - Enable "Create Task Scene" and "Get Published Snapshots".  
  - If `FTRACK_WORKDIR` set and task dir exists → `_populate_task_files_for_data(task_data, create_if_missing=False)` (no auto-create).

Snapshots and linked components are loaded only on demand (e.g. "Get Published Snapshots", "Collect linked"), not on every task selection.

---

## 7. Task Directory and Scene Paths

- **Root:** `FTRACK_WORKDIR`.
- **Path:**  
  `<root>/<project_name>/<context_segments...>/<task_name>`  
  (`_build_task_directory(task_data)`).
- **Create Task Scene:**  
  - Build dir, create if missing.  
  - Scene name: `_slugify(task_name)_<YYYYMMDD_HHMMSS><.hip|.ma|.blend|.scene>` (`_detect_scene_extension`).  
  - If `_dcc_handlers` present → `create_task_scene(widget, task_data, dir_path, scene_path)` (DCC creates/saves scene, applies setup, may close widget).  
  - Then refresh task files list.

---

## 8. Published Snapshots

- **Trigger:** "Get Published Snapshots" with a task selected.
- **Query:**  
  `AssetVersion where task.id is "<task_id>"`; for each version, components with paths via `api.get_components_with_paths_for_version(version_id)`.
- **Filter:**  
  Component name `"snapshot"`; in Houdini only `.hip/.hipnc/.hiplc`, in Maya only `.ma/.mb`.
- **Display:** Asset, version, component/type, path, "Available" (path exists and not N/A).
- **Copy to local:**  
  Copy selected snapshot file into task directory; name pattern e.g. `<asset>.<version>.<date><ext>`; then refresh task files.

---

## 9. Linked Components (ilink)

- **Trigger:** "Collect linked" after snapshots are loaded; one snapshot row selected.
- **Logic:**  
  Read component id from snapshot row; load component metadata; read `component["metadata"]["ilink"]` (or similar); resolve linked component ids; for each, check locations and availability.
- **UI:**  
  Linked tree: Asset, Version, Component, ext, Available, Size, Locations, "To transfer" checkbox.  
  Only locations that are accessible (with accessor, not ftrack.*) are considered; components with no accessible source can be disabled.
- **Transfer to local:**  
  - Selected = rows with "To transfer" checked.  
  - Target location = `_pick_default_target_location(locations)` (e.g. by priority).  
  - For each component, choose source location (prefer e.g. s3.minio, then backup), build batches by source.  
  - Use same transfer stack as main browser: `TransferWorker`, optional `TransferStatusDialog`; run transfer jobs.  
  - No automatic open of scene after transfer; user uses "Open Scene" if needed.

---

## 10. DCC Handlers (Protocol)

**Protocol:** `UserTasksDccHandlers` in `user_tasks_widget.py`.

- **`create_task_scene(widget, task_data, dir_path, scene_path)`**  
  Create/save scene in DCC, apply scene setup (fps, frame range from shot if applicable), optionally close widget.

- **`open_scene(widget, path, task_data)`**  
  Open scene by path in DCC, optionally set task context and close widget.

Implementations:

- **Maya:** `browser/dcc/maya/__init__.py` → `MayaUserTasksHandlers` (set task vars, shot info, frame range, save/load scene).
- **Houdini:** `browser/dcc/houdini/__init__.py` → `HoudiniUserTasksHandlers` (same idea, Houdini API and .hip paths).

When the widget is created inside Maya/Houdini, the host passes these handlers so "Create Task Scene" and "Open Scene" run DCC-specific code.

---

## 11. Open Scene (Local File)

- **Trigger:** "Open Scene" in the task files area when a file row is selected.
- **Path:** From selected row (e.g. column Path or stored path).
- If `_dcc_handlers` and `open_scene` exist → call `open_scene(widget, path, task_data)`.  
  Else fallback: e.g. `os.startfile` / `subprocess` to open file (no DCC).

---

## 12. Summary Diagram

```
Launcher (run_user_tasks_launcher / tools / Maya / Houdini)
    → get_shared_session()
    → SimpleFtrackApiClient(session)
    → UserTasksWidget(api_client, initial_task_id, [dcc_handlers])

UserTasksWidget init
    → _build_ui()   (toolbar, Tree/Board stack, files, snapshots, linked, buttons)
    → _load_tasks() (session, api_user, active projects, project combo, _load_tasks_for_current_project, _maybe_focus_initial_task)

_load_tasks_for_current_project
    → query Task where assignments.resource.username + optional project
    → filter by active projects, transform to _all_tasks
    → _populate_board() or _populate_tree()

User actions
    → Project/Refresh/View change → reload or repopulate
    → Select task (Tree/Board) → _on_task_selected → enable buttons, optional task files if dir exists
    → Create Task Scene → build dir/path → dcc_handlers.create_task_scene (or just propose path)
    → Get Published Snapshots → _load_snapshots_for_task (AssetVersion + components, filter snapshot type)
    → Copy to local (snapshot) → copy file to task dir
    → Collect linked → resolve ilink for selected snapshot → fill linked tree
    → Transfer to local (linked) → pick target location, batch by source, TransferWorker
    → Open Scene → dcc_handlers.open_scene or external open
```

This is the full logic of User Task in `ftrack_inout`: from launcher and session, through loading and filtering tasks, to Tree/Board, task dirs, snapshots, ilink, transfer, and DCC handlers.
