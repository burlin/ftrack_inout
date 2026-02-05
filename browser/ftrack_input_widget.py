from __future__ import annotations

"""
Standalone finput-like loader (DCC-agnostic).

Core: 3 main fields — Asset Version, Component Id, Component Name.
From (Asset Version + Component Name) we resolve Component Id and local file path
(e.g. copy version/name from web or browser → get component id + path).
Task ID is NOT the loader's primary input; component can live on any task.

Optional "use custom" block: browser by task_id (list assets under task parent)
to help fill the 3 fields; like fselector in publisher. Not required for loader.

Loader purpose: path to local copy of component + read metadata + update tracking.
Create node (Houdini) is DCC-specific and has no meaning in standalone.

See finput_hda_interface_spec.yaml for full HDA parameter reference.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional, TYPE_CHECKING

try:
    from PySide6 import QtWidgets, QtCore  # type: ignore
except Exception:
    from PySide2 import QtWidgets, QtCore  # type: ignore

if TYPE_CHECKING:
    from .simple_api_client import FtrackApiClient  # noqa: F401


@dataclass
class FtrackComponentSelection:
    """Resolved component: path, metadata, transfer state."""

    task_id: Optional[str]
    asset_id: Optional[str]
    asset_name: Optional[str]
    asset_type: Optional[str]
    version_id: Optional[str]
    version_number: Optional[int]
    component_id: Optional[str]
    component_name: Optional[str]
    # Как __ftrack_used_CompId в Houdini HDA — для скриптов, которые ищут, какие компоненты использованы в сцене
    used_component_id: Optional[str]
    file_path: str
    target_location_id: Optional[str]
    target_location_name: Optional[str]
    transfer_ready: bool
    transfer_from_id: Optional[str]
    transfer_to_id: Optional[str]
    variables: Dict[str, Any]
    metadata: Dict[str, Any]

    def as_hda_like_parms(self) -> Dict[str, Any]:
        """Словарь в духе параметров HDA (task_Id, componentid, __ftrack_used_CompId) для скриптов поиска использованных компонентов."""
        return {
            "task_Id": self.task_id,
            "componentid": self.component_id,
            "__ftrack_used_CompId": self.used_component_id or self.component_id,
        }


class FtrackInputWidget(QtWidgets.QWidget):
    """
    Standalone finput: 3 main fields (Asset Version, Component Id, Component Name),
    get from assetver → resolve component id + path; optional browser (use custom).
    """

    selectionResolved = QtCore.Signal(FtrackComponentSelection)
    transferRequested = QtCore.Signal(FtrackComponentSelection)

    def __init__(
        self,
        parent: Optional[QtWidgets.QWidget] = None,
        api_client: Optional["FtrackApiClient"] = None,
    ) -> None:
        super(FtrackInputWidget, self).__init__(parent)
        self._api_client: Optional["FtrackApiClient"] = api_client

        # Resolved state (after get from assetver or browser set_this)
        self._resolved_path: str = ""
        self._resolved_location_id: Optional[str] = None
        self._resolved_location_name: Optional[str] = None
        self._transfer_ready: bool = False
        self._current_asset_id: Optional[str] = None
        self._current_version_id: Optional[str] = None
        self._current_component_id: Optional[str] = None
        self._asset_cache: Dict[str, Any] = {}

        self._build_ui()
        self._connect_signals()

    def _get_api_client(self) -> Optional["FtrackApiClient"]:
        if self._api_client is not None:
            return self._api_client
        try:
            from .simple_api_client import FtrackApiClient
            self._api_client = FtrackApiClient()
            return self._api_client
        except Exception:
            return None

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        # --- Optional "use custom" browser block ---
        self._use_custom_cb = QtWidgets.QCheckBox("use custom")
        self._use_custom_cb.setToolTip("Show browser by task_id to fill Asset Version / Component (like fselector).")
        layout.addWidget(self._use_custom_cb)

        self._browser_widget = QtWidgets.QFrame()
        self._browser_widget.setVisible(False)
        browser_layout = QtWidgets.QVBoxLayout(self._browser_widget)
        browser_layout.setContentsMargins(0, 4, 0, 0)

        task_row = QtWidgets.QHBoxLayout()
        task_row.addWidget(QtWidgets.QLabel("Task ID:"))
        self._task_edit = QtWidgets.QLineEdit()
        self._task_edit.setPlaceholderText("Task ID (optional)...")
        task_row.addWidget(self._task_edit, 1)
        self._check_taskid_btn = QtWidgets.QPushButton("check taskid")
        self._get_ex_btn = QtWidgets.QPushButton("get_ex")
        task_row.addWidget(self._check_taskid_btn)
        task_row.addWidget(self._get_ex_btn)
        browser_layout.addLayout(task_row)

        self._asset_combo = QtWidgets.QComboBox()
        self._asset_combo.setEnabled(False)
        self._version_combo = QtWidgets.QComboBox()
        self._version_combo.setEnabled(False)
        self._component_combo = QtWidgets.QComboBox()
        self._component_combo.setEnabled(False)
        browser_layout.addWidget(QtWidgets.QLabel("Asset:"))
        browser_layout.addWidget(self._asset_combo)
        browser_layout.addWidget(QtWidgets.QLabel("Version:"))
        browser_layout.addWidget(self._version_combo)
        browser_layout.addWidget(QtWidgets.QLabel("Component:"))
        browser_layout.addWidget(self._component_combo)
        self._set_this_btn = QtWidgets.QPushButton("set_this (fill 3 fields)")
        self._set_this_btn.setEnabled(False)
        browser_layout.addWidget(self._set_this_btn)
        layout.addWidget(self._browser_widget)

        # --- Separator ---
        layout.addWidget(self._hline())

        # --- 3 main fields (loader core) ---
        form = QtWidgets.QFormLayout()
        form.setSpacing(4)
        self._asset_version_edit = QtWidgets.QLineEdit()
        self._asset_version_edit.setPlaceholderText("Asset Version id (from web/browser)")
        self._component_id_edit = QtWidgets.QLineEdit()
        self._component_id_edit.setPlaceholderText("Component Id (priority: if set, overrides Version+Name)")
        self._component_name_combo = QtWidgets.QComboBox()
        self._component_name_combo.setEnabled(False)
        self._component_name_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        self._component_name_combo.setToolTip("Components for current Asset Version; selecting one sets Component Id.")
        form.addRow("Asset Version:", self._asset_version_edit)
        form.addRow("Component Id:", self._component_id_edit)
        form.addRow("Component Name:", self._component_name_combo)
        layout.addLayout(form)

        # Subscribe to Updates
        self._subscribe_cb = QtWidgets.QCheckBox("Subscribe to Updates")
        layout.addWidget(self._subscribe_cb)

        # --- Buttons: get from assetver (Component Id has priority), transfer, accept update ---
        btn_row = QtWidgets.QHBoxLayout()
        self._get_from_assetver_btn = QtWidgets.QPushButton("get from assetver")
        self._get_from_assetver_btn.setToolTip("If Component Id set: fill Version+Name from it, then path. Else: from Version+Component Name → Component Id + path.")
        self._transfer_btn = QtWidgets.QPushButton("transfer_to_local")
        self._transfer_btn.setEnabled(False)
        self._accept_update_btn = QtWidgets.QPushButton("Accept Update")
        self._accept_update_btn.setEnabled(False)
        btn_row.addWidget(self._get_from_assetver_btn)
        btn_row.addWidget(self._transfer_btn)
        btn_row.addWidget(self._accept_update_btn)
        btn_row.addStretch(1)
        layout.addLayout(btn_row)

        # --- File Path (result) ---
        path_row = QtWidgets.QHBoxLayout()
        path_row.addWidget(QtWidgets.QLabel("File Path:"))
        self._file_path_edit = QtWidgets.QLineEdit()
        self._file_path_edit.setReadOnly(True)
        self._file_path_edit.setPlaceholderText("(resolved after get from assetver)")
        path_row.addWidget(self._file_path_edit, 1)
        layout.addLayout(path_row)

        # --- Message / status ---
        self._message_label = QtWidgets.QLabel("Set Component Id (or Asset Version + select Component), then 'get from assetver'.")
        self._message_label.setWordWrap(True)
        layout.addWidget(self._message_label)

        # --- show variables ---
        self._show_vars_cb = QtWidgets.QCheckBox("show variables")
        layout.addWidget(self._show_vars_cb)
        self._variables_text = QtWidgets.QTextEdit()
        self._variables_text.setReadOnly(True)
        self._variables_text.setMaximumHeight(80)
        self._variables_text.setPlaceholderText("variables (from component)")
        self._variables_text.setVisible(False)
        layout.addWidget(self._variables_text)
        self._metadict_text = QtWidgets.QTextEdit()
        self._metadict_text.setReadOnly(True)
        self._metadict_text.setMaximumHeight(80)
        self._metadict_text.setPlaceholderText("metadict")
        self._metadict_text.setVisible(False)
        layout.addWidget(self._metadict_text)

        layout.addStretch(1)

    def _hline(self) -> QtWidgets.QFrame:
        line = QtWidgets.QFrame()
        line.setFrameShape(QtWidgets.QFrame.HLine)
        line.setFrameShadow(QtWidgets.QFrame.Sunken)
        return line

    def _connect_signals(self) -> None:
        self._use_custom_cb.toggled.connect(self._on_use_custom_toggled)
        self._get_from_assetver_btn.clicked.connect(self._on_get_from_assetver)
        self._transfer_btn.clicked.connect(self._on_transfer_clicked)
        self._component_name_combo.currentIndexChanged.connect(self._on_component_name_combo_changed)
        self._show_vars_cb.toggled.connect(self._variables_text.setVisible)
        self._show_vars_cb.toggled.connect(self._metadict_text.setVisible)
        self._check_taskid_btn.clicked.connect(self._on_check_taskid)
        self._get_ex_btn.clicked.connect(self._on_get_ex)
        self._set_this_btn.clicked.connect(self._on_set_this)
        self._asset_combo.currentIndexChanged.connect(self._on_browser_asset_changed)
        self._version_combo.currentIndexChanged.connect(self._on_browser_version_changed)
        self._component_combo.currentIndexChanged.connect(self._on_browser_component_changed)

    def _on_use_custom_toggled(self, checked: bool) -> None:
        self._browser_widget.setVisible(checked)

    def _on_check_taskid(self) -> None:
        task_id = self._task_edit.text().strip()
        if not task_id:
            self._message_label.setText("Task ID is empty.")
            return
        self._message_label.setText(f"Loading assets for Task {task_id}...")
        api = self._get_api_client()
        if api:
            self._populate_assets_for_task(task_id, api)
        else:
            self._message_label.setText("API unavailable (stub).")

    def _on_get_ex(self) -> None:
        self._on_check_taskid()

    def _populate_assets_for_task(self, task_id: str, api: "FtrackApiClient") -> None:
        self._asset_combo.clear()
        self._version_combo.clear()
        self._component_combo.clear()
        self._set_this_btn.setEnabled(False)
        try:
            assets = api.get_assets_for_task(task_id)
            if not assets:
                self._message_label.setText(f"No assets for Task {task_id}.")
                self._asset_combo.setEnabled(True)
                return
            for asset in assets:
                aid = asset.get("id") or asset["id"]
                name = asset.get("name") or "Unknown"
                self._asset_combo.addItem(name, aid)
                self._asset_cache[aid] = asset
            self._asset_combo.setEnabled(True)
            self._message_label.setText(f"Loaded {len(assets)} asset(s). Select asset.")
        except Exception as e:
            self._message_label.setText(f"Error: {e}")
            self._asset_combo.setEnabled(True)

    def _on_browser_asset_changed(self, index: int) -> None:
        if index < 0:
            return
        asset_id = self._asset_combo.itemData(index)
        if not asset_id:
            return
        self._version_combo.blockSignals(True)
        self._version_combo.clear()
        self._version_combo.setEnabled(False)
        self._component_combo.clear()
        self._component_combo.setEnabled(False)
        self._version_combo.blockSignals(False)
        self._set_this_btn.setEnabled(False)
        api = self._get_api_client()
        if not api:
            return
        task_id = self._task_edit.text().strip()
        if not task_id:
            self._message_label.setText("Set Task ID first.")
            self._version_combo.setEnabled(True)
            return
        versions = api.get_versions_for_asset_and_task(str(asset_id), task_id)
        for v in versions:
            vid = v.get("id")
            vnum = v.get("version")
            label = f"v{vnum:03d}" if vnum is not None else str(vid)
            self._version_combo.addItem(label, {"id": vid, "version": vnum})
        self._version_combo.setEnabled(True)
        self._message_label.setText("Select version.")

    def _on_browser_version_changed(self, index: int) -> None:
        if index < 0:
            return
        data = self._version_combo.itemData(index)
        if not data:
            return
        version_id = data.get("id") if isinstance(data, dict) else data
        self._component_combo.blockSignals(True)
        self._component_combo.clear()
        self._component_combo.setEnabled(False)
        self._component_combo.blockSignals(False)
        self._set_this_btn.setEnabled(False)
        api = self._get_api_client()
        if not api:
            return
        components = api.get_components_for_version(str(version_id))
        for comp in components:
            label = comp.get("display_name") or comp.get("name") or comp.get("id")
            self._component_combo.addItem(label, comp.get("id"))
        self._component_combo.setEnabled(True)
        self._message_label.setText("Select component, then 'set_this'.")

    def _on_browser_component_changed(self, index: int) -> None:
        self._set_this_btn.setEnabled(index >= 0 and self._component_combo.itemData(index) is not None)

    def _on_set_this(self) -> None:
        """Как в Houdini applyCompSelection: только подстановка полей и списка, без разрешения пути. Путь — по «get from assetver»."""
        v_idx = self._version_combo.currentIndex()
        c_idx = self._component_combo.currentIndex()
        if v_idx < 0 or c_idx < 0:
            self._message_label.setText("Select version and component in browser.")
            return
        v_data = self._version_combo.itemData(v_idx)
        version_id = v_data.get("id") if isinstance(v_data, dict) else v_data
        component_id = self._component_combo.itemData(c_idx)
        self._asset_version_edit.setText(str(version_id))
        self._component_id_edit.setText(str(component_id))
        self._current_version_id = str(version_id)
        self._current_component_id = str(component_id)
        idx = self._asset_combo.currentIndex()
        if idx >= 0:
            aid = self._asset_combo.itemData(idx)
            if aid:
                self._current_asset_id = str(aid)
        # Копируем уже загруженный список из браузера в основной блок (без API)
        self._component_name_combo.blockSignals(True)
        self._component_name_combo.clear()
        for i in range(self._component_combo.count()):
            label = self._component_combo.itemText(i)
            cid = self._component_combo.itemData(i)
            self._component_name_combo.addItem(label, cid)
        self._component_name_combo.setEnabled(True)
        self._component_name_combo.setCurrentIndex(c_idx)
        self._component_name_combo.blockSignals(False)
        # Как в Houdini: applyCompSelection не вызывает get_component_path; путь — по «get from assetver»
        self._file_path_edit.setText("")
        self._message_label.setText("Selection applied. Click «get from assetver» to resolve path.")

    def _resolve_path_for_current_component(self) -> None:
        """Update file path and transfer state from current component id."""
        comp_id = self._component_id_edit.text().strip()
        if not comp_id:
            return
        self._current_component_id = comp_id
        api = self._get_api_client()
        if not api:
            self._file_path_edit.setText("")
            self._message_label.setText("API unavailable.")
            return
        try:
            info = api.get_component_location_info(comp_id)
            self._resolved_path = info.get("path") or ""
            self._resolved_location_id = info.get("location_id")
            self._resolved_location_name = info.get("location_name")
            self._transfer_ready = bool(info.get("transfer_ready"))
            self._file_path_edit.setText(self._resolved_path)
            self._transfer_btn.setEnabled(self._transfer_ready)
            av = info.get("availability", 0)
            loc_name = info.get("location_name") or "location"
            if self._transfer_ready:
                self._message_label.setText(f"Path not local (availability {av:.0f}% at {loc_name}). Use transfer_to_local.")
            elif self._resolved_path:
                self._message_label.setText("Path resolved.")
            else:
                self._message_label.setText(f"No path at {loc_name} (availability {av:.0f}%). Check location or transfer.")
        except Exception as e:
            self._message_label.setText(f"Resolve failed: {e}")
            self._transfer_btn.setEnabled(True)

    def _populate_component_name_combo(self, version_id: str) -> None:
        """Fill Component Name combo with components for this Asset Version (fast: no path resolution)."""
        self._component_name_combo.blockSignals(True)
        self._component_name_combo.clear()
        api = self._get_api_client()
        if not api or not version_id:
            self._component_name_combo.setEnabled(False)
            self._component_name_combo.blockSignals(False)
            return
        try:
            components = api.get_components_for_version(version_id)
            for comp in components:
                label = comp.get("display_name") or comp.get("name") or comp.get("id")
                cid = comp.get("id")
                self._component_name_combo.addItem(label, cid)
            self._component_name_combo.setEnabled(True)
        except Exception:
            self._component_name_combo.setEnabled(False)
        self._component_name_combo.blockSignals(False)

    def _on_component_name_combo_changed(self, index: int) -> None:
        """When user selects another component in list, set Component Id to selected (like applyCompSelection)."""
        if index < 0:
            return
        cid = self._component_name_combo.itemData(index)
        if cid:
            self._component_id_edit.setText(str(cid))
            self._current_component_id = str(cid)

    def _on_get_from_assetver(self) -> None:
        """Component Id has priority. If set: fill Asset Version + Component Name from it, then path. Else: from Version + Component Name combo → Component Id + path."""
        api = self._get_api_client()
        if not api:
            self._message_label.setText("API unavailable.")
            return
        comp_id = self._component_id_edit.text().strip()
        version_id = self._asset_version_edit.text().strip()

        if comp_id:
            # Component Id has priority: resolve version + name from component_id (get_fromcomp style)
            self._message_label.setText("Resolving from Component Id...")
            try:
                info = api.get_component_info(comp_id)
                if not info:
                    self._message_label.setText("Component not found.")
                    return
                version_id = info.get("version_id")
                component_name = info.get("component_name", "")
                self._asset_version_edit.setText(str(version_id))
                self._current_version_id = str(version_id)
                self._current_asset_id = info.get("asset_id")
                if self._current_asset_id:
                    self._asset_cache[self._current_asset_id] = {
                        "id": self._current_asset_id,
                        "name": info.get("asset_name", ""),
                        "type": info.get("asset_type", ""),
                    }
                self._populate_component_name_combo(version_id)
                # Select in combo the item matching this component_id
                for i in range(self._component_name_combo.count()):
                    if str(self._component_name_combo.itemData(i)) == str(comp_id):
                        self._component_name_combo.blockSignals(True)
                        self._component_name_combo.setCurrentIndex(i)
                        self._component_name_combo.blockSignals(False)
                        break
                self._current_component_id = str(comp_id)
                self._resolve_path_for_current_component()
                self.selectionResolved.emit(self._build_selection_result())
            except Exception as e:
                self._message_label.setText(f"Error: {e}")
            return

        if not version_id:
            self._message_label.setText("Enter Component Id or Asset Version.")
            return
        # From Asset Version + Component Name (combo): resolve component_id and path
        self._message_label.setText("Resolving...")
        try:
            self._populate_component_name_combo(version_id)
            if self._component_name_combo.count() == 0:
                self._message_label.setText("No components for this version.")
                return
            # Use current combo selection or first
            idx = self._component_name_combo.currentIndex()
            if idx < 0:
                idx = 0
                self._component_name_combo.setCurrentIndex(0)
            cid = self._component_name_combo.itemData(idx)
            if not cid:
                self._message_label.setText("No component selected.")
                return
            self._component_id_edit.setText(str(cid))
            self._current_version_id = version_id
            self._current_component_id = str(cid)
            self._resolve_path_for_current_component()
            self.selectionResolved.emit(self._build_selection_result())
        except Exception as e:
            self._message_label.setText(f"Error: {e}")

    def _on_transfer_clicked(self) -> None:
        sel = self._build_selection_result()
        if sel.component_id:
            self.transferRequested.emit(sel)
            self._message_label.setText("Transfer requested.")

    def _build_selection_result(self) -> FtrackComponentSelection:
        comp_name = None
        if self._component_name_combo.currentIndex() >= 0:
            txt = self._component_name_combo.currentText()
            comp_name = txt.split(" (")[0].strip() if txt else None
        version_number = None
        if self._version_combo.currentIndex() >= 0:
            data = self._version_combo.itemData(self._version_combo.currentIndex())
            if isinstance(data, dict):
                version_number = data.get("version")
        asset_name = None
        asset_type = None
        if self._current_asset_id and self._current_asset_id in self._asset_cache:
            a = self._asset_cache[self._current_asset_id]
            asset_name = a.get("name")
            t = a.get("type")
            asset_type = t.get("name") if t and hasattr(t, "get") else str(t) if t else None
        comp_id = self._component_id_edit.text().strip() or self._current_component_id
        return FtrackComponentSelection(
            task_id=self._task_edit.text().strip() or None,
            asset_id=self._current_asset_id,
            asset_name=asset_name,
            asset_type=asset_type,
            version_id=self._asset_version_edit.text().strip() or self._current_version_id,
            version_number=version_number,
            component_id=comp_id,
            component_name=comp_name,
            used_component_id=comp_id,
            file_path=self._file_path_edit.text().strip(),
            target_location_id=self._resolved_location_id,
            target_location_name=self._resolved_location_name,
            transfer_ready=self._transfer_ready,
            transfer_from_id=None,
            transfer_to_id=self._resolved_location_id if self._transfer_ready else None,
            variables={},
            metadata={},
        )


__all__ = ["FtrackInputWidget", "FtrackComponentSelection"]
