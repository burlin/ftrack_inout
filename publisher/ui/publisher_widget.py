"""
Standalone Qt UI for Universal Publisher.

This widget replicates the Houdini HDA interface structure and parameter names
for compatibility with existing publisher code.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import Any, Dict, List, Optional

# Compatibility: imp module was removed in Python 3.12+, but ftrack_api dependencies may need it
# Add imp module stub before importing ftrack_api (only for Python 3.12+)
# Note: Python 3.11 (used in Houdini/Maya) still has imp module, so this stub is not needed there
if sys.version_info >= (3, 12) and 'imp' not in sys.modules:
    import types
    class ImpModule:
        """Minimal imp module stub for Python 3.12+ compatibility"""
        @staticmethod
        def find_module(name, path=None):
            return None
        @staticmethod
        def load_module(name, file=None, pathname=None, description=None):
            raise ImportError(f"imp.load_module is not supported in Python 3.12+")
        @staticmethod
        def new_module(name):
            return types.ModuleType(name)
        @staticmethod
        def get_suffixes():
            return []
        @staticmethod
        def acquire_lock():
            pass
        @staticmethod
        def release_lock():
            pass
    sys.modules['imp'] = ImpModule()  # type: ignore

try:
    from PySide2 import QtCore, QtGui, QtWidgets
    QT_VERSION = "PySide2"
except ImportError:
    try:
        from PySide6 import QtCore, QtGui, QtWidgets
        QT_VERSION = "PySide6"
    except ImportError:
        try:
            from PyQt5 import QtCore, QtGui, QtWidgets
            QT_VERSION = "PyQt5"
        except ImportError:
            raise ImportError(
                "No Qt bindings found. Please install PySide2, PySide6, or PyQt5.\n"
                "Example: pip install PySide2"
            )

_log = logging.getLogger(__name__)

# Compatibility: imp module was removed in Python 3.12+, but ftrack_api dependencies may need it
# Add imp module stub before importing ftrack_api (only for Python 3.12+)
# Note: Python 3.11 (used in Houdini/Maya) still has imp module, so this stub is not needed there
if sys.version_info >= (3, 12) and 'imp' not in sys.modules:
    import types
    class ImpModule:
        """Minimal imp module stub for Python 3.12+ compatibility"""
        @staticmethod
        def find_module(name, path=None):
            return None
        @staticmethod
        def load_module(name, file=None, pathname=None, description=None):
            raise ImportError(f"imp.load_module is not supported in Python 3.12+")
        @staticmethod
        def new_module(name):
            return types.ModuleType(name)
        @staticmethod
        def get_suffixes():
            return []
        @staticmethod
        def acquire_lock():
            pass
        @staticmethod
        def release_lock():
            pass
    sys.modules['imp'] = ImpModule()  # type: ignore

# Try to import ftrack_api
try:
    import ftrack_api
    FTRACK_AVAILABLE = True
except ImportError as e:
    FTRACK_AVAILABLE = False
    _log.warning(f"ftrack_api not available: {e}. Ftrack functionality will be disabled.")

# Import core logic through Qt bridge
try:
    from ftrack_inout.publisher.dcc.qt_bridge import (
        check_task_id_qt,
        apply_task_id_qt,
        apply_asset_params_qt,
        get_assets_list_qt,
        apply_name_qt,
    )
    CORE_LOGIC_AVAILABLE = True
except ImportError as e:
    CORE_LOGIC_AVAILABLE = False
    _log.warning(f"Core publisher logic not available: {e}")


class ComponentTabWidget(QtWidgets.QWidget):
    """Widget for a single component tab (comp_name, file_path, metadata)."""
    
    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.index = index
        self._init_ui()
    
    def _init_ui(self):
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Export checkbox
        self.export_checkbox = QtWidgets.QCheckBox("export")
        self.export_checkbox.setChecked(True)
        layout.addWidget(self.export_checkbox)
        
        # Component name
        name_layout = QtWidgets.QHBoxLayout()
        name_layout.addWidget(QtWidgets.QLabel("comp_name:"))
        self.comp_name_edit = QtWidgets.QLineEdit()
        name_layout.addWidget(self.comp_name_edit)
        layout.addLayout(name_layout)
        
        # File path
        path_layout = QtWidgets.QHBoxLayout()
        path_layout.addWidget(QtWidgets.QLabel("file_path:"))
        self.file_path_edit = QtWidgets.QLineEdit()
        self.file_path_edit.setPlaceholderText("File path or sequence pattern (e.g., file.%04d.exr)")
        path_layout.addWidget(self.file_path_edit)
        browse_btn = QtWidgets.QPushButton("...")
        browse_btn.setToolTip("Browse single file")
        browse_btn.setMaximumWidth(30)
        browse_btn.clicked.connect(self._browse_file)
        path_layout.addWidget(browse_btn)
        browse_seq_btn = QtWidgets.QPushButton("Seq")
        browse_seq_btn.setToolTip("Browse and detect sequence")
        browse_seq_btn.setMaximumWidth(40)
        browse_seq_btn.clicked.connect(self._browse_sequence)
        path_layout.addWidget(browse_seq_btn)
        layout.addLayout(path_layout)
        
        # Metadata records
        meta_layout = QtWidgets.QHBoxLayout()
        meta_layout.addWidget(QtWidgets.QLabel("metadata records:"))
        self.meta_count_spin = QtWidgets.QSpinBox()
        self.meta_count_spin.setMinimum(0)
        self.meta_count_spin.setMaximum(100)
        self.meta_count_spin.setValue(0)
        self.meta_count_spin.valueChanged.connect(self._update_metadata_widgets)
        meta_layout.addWidget(self.meta_count_spin)
        plus_btn = QtWidgets.QPushButton("+")
        plus_btn.setMaximumWidth(30)
        plus_btn.clicked.connect(lambda: self.meta_count_spin.setValue(self.meta_count_spin.value() + 1))
        meta_layout.addWidget(plus_btn)
        minus_btn = QtWidgets.QPushButton("-")
        minus_btn.setMaximumWidth(30)
        minus_btn.clicked.connect(lambda: self.meta_count_spin.setValue(max(0, self.meta_count_spin.value() - 1)))
        meta_layout.addWidget(minus_btn)
        clear_btn = QtWidgets.QPushButton("Clear")
        clear_btn.clicked.connect(lambda: self.meta_count_spin.setValue(0))
        meta_layout.addWidget(clear_btn)
        layout.addLayout(meta_layout)
        
        # Metadata key/value pairs
        self.metadata_scroll = QtWidgets.QScrollArea()
        self.metadata_scroll.setWidgetResizable(True)
        self.metadata_widget = QtWidgets.QWidget()
        self.metadata_layout = QtWidgets.QVBoxLayout(self.metadata_widget)
        self.metadata_layout.setContentsMargins(0, 0, 0, 0)
        self.metadata_scroll.setWidget(self.metadata_widget)
        layout.addWidget(self.metadata_scroll)
        
        # Store metadata widgets
        self.metadata_widgets: List[Dict[str, QtWidgets.QWidget]] = []
    
    def _browse_file(self):
        """Browse for file or sequence."""
        try:
            current_path = self.file_path_edit.text()
            start_dir = ""
            if current_path:
                parent = os.path.dirname(current_path)
                if os.path.isdir(parent):
                    start_dir = parent
            
            # Show dialog with option to select file
            file_path, selected_filter = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Select File (for sequence, select one frame)",
                start_dir,
                "All Files (*);;Images (*.exr *.png *.jpg *.tif *.tiff);;Caches (*.abc *.vdb *.bgeo.sc)"
            )
            if file_path:
                # Detect sequence pattern from selected file
                sequence_path = self._detect_sequence_pattern(file_path)
                self.file_path_edit.setText(sequence_path)
        except Exception as e:
            _log.error(f"[ComponentTabWidget] Error in _browse_file: {e}", exc_info=True)
    
    def _detect_sequence_pattern(self, file_path: str) -> str:
        """Detect if file is part of a sequence and return pattern.
        
        Example: /path/frame.0001.exr -> /path/frame.%04d.exr
        """
        if not file_path:
            return file_path
        
        dirname = os.path.dirname(file_path)
        basename = os.path.basename(file_path)
        
        # Try to find frame number pattern (e.g., .0001. or _0001_ or 0001.)
        patterns = [
            (r'(\.)(\d{2,})(\.[^.]+)$', r'\g<1>%0{}d\g<3>'),      # .0001.ext
            (r'(_)(\d{2,})(\.[^.]+)$', r'\g<1>%0{}d\g<3>'),       # _0001.ext
            (r'(\.)(\d{2,})(_[^.]+\.[^.]+)$', r'\g<1>%0{}d\g<3>'), # .0001_suffix.ext
        ]
        
        for pattern, replacement in patterns:
            match = re.search(pattern, basename)
            if match:
                frame_digits = len(match.group(2))
                new_basename = re.sub(pattern, replacement.format(frame_digits), basename)
                sequence_path = os.path.join(dirname, new_basename)
                
                # Normalize path separators
                sequence_path = sequence_path.replace('\\', '/')
                
                _log.debug(f"[ComponentTabWidget] Detected sequence: {file_path} -> {sequence_path}")
                return sequence_path
        
        # No sequence pattern found, return original
        return file_path.replace('\\', '/')
    
    def _browse_sequence(self):
        """Browse for sequence - select directory and detect sequences."""
        try:
            current_path = self.file_path_edit.text()
            start_dir = ""
            if current_path:
                parent = os.path.dirname(current_path)
                if os.path.isdir(parent):
                    start_dir = parent
            
            # First, let user select a directory
            directory = QtWidgets.QFileDialog.getExistingDirectory(
                self,
                "Select Directory with Sequences",
                start_dir
            )
            
            if not directory:
                return
            
            # Scan directory for sequences
            sequences = self._find_sequences_in_directory(directory)
            
            if not sequences:
                QtWidgets.QMessageBox.information(
                    self, "No Sequences Found",
                    f"No image/cache sequences found in:\n{directory}\n\n"
                    "Sequences are detected by frame numbers in filenames like:\n"
                    "  file.0001.exr, file_0001.vdb, etc."
                )
                return
            
            # Show dialog to select sequence
            items = []
            for seq_info in sequences:
                pattern = seq_info['pattern']
                frame_range = seq_info['frame_range']
                count = seq_info['count']
                items.append(f"{pattern}  [{frame_range[0]}-{frame_range[1]}] ({count} frames)")
            
            selected, ok = QtWidgets.QInputDialog.getItem(
                self,
                "Select Sequence",
                f"Found {len(sequences)} sequence(s) in:\n{directory}\n\nSelect sequence:",
                items,
                0,
                False
            )
            
            if ok and selected:
                # Find the selected sequence
                idx = items.index(selected)
                seq_info = sequences[idx]
                sequence_path = seq_info['pattern']
                self.file_path_edit.setText(sequence_path)
                
                _log.info(f"[ComponentTabWidget] Selected sequence: {sequence_path}")
                
        except Exception as e:
            _log.error(f"[ComponentTabWidget] Error in _browse_sequence: {e}", exc_info=True)
            QtWidgets.QMessageBox.critical(self, "Error", f"Failed to browse sequences:\n{e}")
    
    def _find_sequences_in_directory(self, directory: str) -> list:
        """Find all sequences in directory.
        
        Returns list of dicts: {'pattern': str, 'frame_range': (int, int), 'count': int}
        """
        sequences = []
        
        # Try to use fileseq if available
        try:
            import fileseq
            for seq in fileseq.findSequencesOnDisk(directory):
                if len(seq) > 1:  # Only include actual sequences (more than 1 frame)
                    # Get printf-style pattern from fileseq
                    # fileseq format: name.1001-1100#.ext or name.1001-1100@@@@.ext
                    # We need: name.%04d.ext
                    
                    # Use fileseq's format method to get printf pattern
                    # seq.format('{dirname}{basename}{padding}{extension}') with padding as %0Nd
                    try:
                        # Get components
                        dirname = seq.dirname()
                        basename = seq.basename()
                        ext = seq.extension()
                        padding = seq.padding()
                        
                        # Convert padding to printf format
                        if padding:
                            # padding is like '#' or '@@@@'
                            if '#' in padding:
                                pad_width = seq.zfill()  # Get padding width
                                printf_pad = f'%0{pad_width}d'
                            elif '@' in padding:
                                pad_width = len(padding)
                                printf_pad = f'%0{pad_width}d'
                            else:
                                printf_pad = '%04d'  # Default
                        else:
                            printf_pad = '%04d'
                        
                        # Build printf pattern
                        pattern = os.path.join(dirname, f"{basename}{printf_pad}{ext}")
                        pattern = pattern.replace('\\', '/')
                        
                    except Exception as fmt_err:
                        _log.warning(f"[ComponentTabWidget] Error formatting sequence: {fmt_err}")
                        # Fallback: try to convert string representation
                        pattern = str(seq)
                        # Remove frame range (e.g., "1131-1297")
                        pattern = re.sub(r'\d+-\d+', '', pattern)
                        # Convert # or @ to printf format
                        pattern = re.sub(r'#+', lambda m: f'%0{len(m.group())}d', pattern)
                        pattern = re.sub(r'@+', lambda m: f'%0{len(m.group())}d', pattern)
                        pattern = pattern.replace('\\', '/')
                    
                    sequences.append({
                        'pattern': pattern,
                        'frame_range': (seq.start(), seq.end()),
                        'count': len(seq)
                    })
            if sequences:
                return sequences
        except ImportError:
            _log.debug("[ComponentTabWidget] fileseq not available, using fallback")
        except Exception as e:
            _log.warning(f"[ComponentTabWidget] fileseq error: {e}, using fallback")
        
        # Fallback: manual sequence detection
        return self._find_sequences_manual(directory)
    
    def _find_sequences_manual(self, directory: str) -> list:
        """Manually detect sequences in directory without fileseq."""
        sequences = {}
        
        # Patterns to detect frame numbers
        frame_patterns = [
            (r'^(.+)\.(\d{2,})\.([^.]+)$', 1, 2, 3),      # name.0001.ext
            (r'^(.+)_(\d{2,})\.([^.]+)$', 1, 2, 3),       # name_0001.ext
            (r'^(.+)\.(\d{2,})_([^.]+)\.([^.]+)$', 1, 2, 4),  # name.0001_suffix.ext
        ]
        
        try:
            for filename in os.listdir(directory):
                filepath = os.path.join(directory, filename)
                if not os.path.isfile(filepath):
                    continue
                
                for pattern, name_group, frame_group, ext_group in frame_patterns:
                    match = re.match(pattern, filename)
                    if match:
                        groups = match.groups()
                        name = groups[name_group - 1]
                        frame_str = groups[frame_group - 1]
                        ext = groups[ext_group - 1]
                        frame_num = int(frame_str)
                        padding = len(frame_str)
                        
                        # Create sequence key
                        seq_key = (name, ext, padding)
                        
                        if seq_key not in sequences:
                            sequences[seq_key] = {
                                'name': name,
                                'ext': ext,
                                'padding': padding,
                                'frames': []
                            }
                        sequences[seq_key]['frames'].append(frame_num)
                        break
            
            # Convert to result format
            result = []
            for seq_key, seq_data in sequences.items():
                frames = sorted(seq_data['frames'])
                if len(frames) > 1:  # Only sequences with more than 1 frame
                    name = seq_data['name']
                    ext = seq_data['ext']
                    padding = seq_data['padding']
                    pattern = os.path.join(directory, f"{name}.%0{padding}d.{ext}")
                    pattern = pattern.replace('\\', '/')
                    
                    result.append({
                        'pattern': pattern,
                        'frame_range': (frames[0], frames[-1]),
                        'count': len(frames)
                    })
            
            # Sort by name
            result.sort(key=lambda x: x['pattern'])
            return result
            
        except Exception as e:
            _log.error(f"[ComponentTabWidget] Error scanning directory: {e}")
            return []
    
    def _update_metadata_widgets(self, count: int):
        """Update metadata key/value widgets based on count."""
        current_count = len(self.metadata_widgets)
        
        # Add new widgets if count increased
        for i in range(current_count, count):
            meta_widget = QtWidgets.QWidget()
            meta_layout = QtWidgets.QHBoxLayout(meta_widget)
            meta_layout.setContentsMargins(0, 0, 0, 0)
            
            key_edit = QtWidgets.QLineEdit()
            key_edit.setPlaceholderText(f"key {i+1}")
            value_edit = QtWidgets.QLineEdit()
            value_edit.setPlaceholderText(f"value {i+1}")
            
            meta_layout.addWidget(key_edit)
            meta_layout.addWidget(value_edit)
            
            self.metadata_layout.addWidget(meta_widget)
            self.metadata_widgets.append({
                'key': key_edit,
                'value': value_edit,
                'widget': meta_widget
            })
        
        # Remove widgets if count decreased
        for i in range(count, current_count):
            widget_data = self.metadata_widgets.pop()
            widget_data['widget'].setParent(None)
            widget_data['widget'].deleteLater()
    
    def get_component_data(self) -> Dict[str, Any]:
        """Get component data matching HDA parameter structure."""
        idx = self.index + 1  # 1-based index
        
        data = {
            f'export{idx}': 1 if self.export_checkbox.isChecked() else 0,
            f'comp_name{idx}': self.comp_name_edit.text(),
            f'file_path{idx}': self.file_path_edit.text(),
            f'meta_count{idx}': self.meta_count_spin.value(),
        }
        
        # Add metadata key/value pairs
        for i, meta_widget in enumerate(self.metadata_widgets):
            meta_idx = i + 1
            data[f'key{idx}_{meta_idx}'] = meta_widget['key'].text()
            data[f'value{idx}_{meta_idx}'] = meta_widget['value'].text()
        
        return data
    
    def set_component_data(self, data: Dict[str, Any]):
        """Set component data from HDA parameter structure."""
        idx = self.index + 1  # 1-based index
        
        # Export
        export_val = data.get(f'export{idx}', 1)
        self.export_checkbox.setChecked(export_val == 1)
        
        # Name and path
        self.comp_name_edit.setText(data.get(f'comp_name{idx}', ''))
        self.file_path_edit.setText(data.get(f'file_path{idx}', ''))
        
        # Metadata count
        meta_count = data.get(f'meta_count{idx}', 0)
        self.meta_count_spin.setValue(meta_count)
        
        # Metadata key/value pairs
        for i in range(meta_count):
            meta_idx = i + 1
            key = data.get(f'key{idx}_{meta_idx}', '')
            value = data.get(f'value{idx}_{meta_idx}', '')
            if i < len(self.metadata_widgets):
                self.metadata_widgets[i]['key'].setText(key)
                self.metadata_widgets[i]['value'].setText(value)


class PublisherWidget(QtWidgets.QWidget):
    """Main publisher widget - functional copy of Houdini HDA interface."""
    
    def __init__(self, parent=None, session=None):
        super().__init__(parent)
        self._parameter_values: Dict[str, Any] = {}
        self._assets_menu_ids: List[str] = []  # Store asset IDs for menu items
        
        # Ftrack session - use shared session factory for optimized caching
        if session is not None:
            self._session = session
            _log.info("Ftrack session provided to PublisherWidget")
        elif FTRACK_AVAILABLE:
            try:
                # Try to use shared session factory (with optimized caching)
                from ..common.session_factory import get_shared_session
                self._session = get_shared_session()
                if self._session:
                    _log.info("Ftrack session obtained from shared session factory")
                else:
                    # Fallback: create new session
                    self._session = ftrack_api.Session(auto_connect_event_hub=True)
                    _log.info("Ftrack session created for PublisherWidget")
            except ImportError:
                # Fallback: common module not available
                try:
                    self._session = ftrack_api.Session(auto_connect_event_hub=True)
                    _log.info("Ftrack session created for PublisherWidget (fallback)")
                except Exception as e:
                    _log.warning(f"Failed to create Ftrack session: {e}")
                    self._session = None
            except Exception as e:
                _log.warning(f"Failed to get/create Ftrack session: {e}")
                _log.debug("Session creation requires FTRACK_SERVER, FTRACK_API_KEY, and FTRACK_API_USER environment variables")
                import traceback
                _log.debug(traceback.format_exc())
                self._session = None
        else:
            self._session = None
            _log.info("Ftrack API not available, session will be None")
        
        self._init_ui()
    
    def _init_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_widget = QtWidgets.QWidget()
        scroll_layout = QtWidgets.QVBoxLayout(scroll_widget)
        
        # Task Definition Section
        self._create_task_section(scroll_layout)
        
        # Task Section (read-only)
        self._create_task_readonly_section(scroll_layout)
        
        # Asset Section (read-only)
        self._create_asset_readonly_section(scroll_layout)
        
        # Snapshot/Playblast Section
        self._create_snapshot_playblast_section(scroll_layout)
        
        # Components Section
        self._create_components_section(scroll_layout)
        
        # Comment Section
        self._create_comment_section(scroll_layout)
        
        scroll.setWidget(scroll_widget)
        main_layout.addWidget(scroll)
        
        # Render/Publish button
        self.publish_btn = QtWidgets.QPushButton("Render")
        self.publish_btn.setMinimumHeight(40)
        self.publish_btn.clicked.connect(self._on_publish_clicked)
        main_layout.addWidget(self.publish_btn)
    
    def _create_task_section(self, parent_layout):
        """Create Task Definition section."""
        group = QtWidgets.QGroupBox("Task Definition")
        layout = QtWidgets.QVBoxLayout(group)
        
        # use_custom checkbox
        self.use_custom_checkbox = QtWidgets.QCheckBox("use custom")
        self.use_custom_checkbox.setChecked(True)
        self.use_custom_checkbox.toggled.connect(self._on_use_custom_changed)
        layout.addWidget(self.use_custom_checkbox)
        
        # Container for all content that should be hidden when use_custom == 0
        self.task_definition_content = QtWidgets.QWidget()
        content_layout = QtWidgets.QVBoxLayout(self.task_definition_content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        
        # task_id
        task_id_layout = QtWidgets.QHBoxLayout()
        task_id_layout.addWidget(QtWidgets.QLabel("task_id:"))
        self.task_id_edit = QtWidgets.QLineEdit()
        self.task_id_edit.setPlaceholderText("Paste task_id from browser")
        task_id_layout.addWidget(self.task_id_edit)
        apply_task_btn = QtWidgets.QPushButton("apply to asset")
        apply_task_btn.clicked.connect(self._on_apply_task_clicked)
        task_id_layout.addWidget(apply_task_btn)
        content_layout.addLayout(task_id_layout)
        
        # Buttons: get_from_env, get_from_scene, check taskid
        buttons_layout = QtWidgets.QHBoxLayout()
        get_env_btn = QtWidgets.QPushButton("get_from_env")
        get_env_btn.clicked.connect(self._on_get_from_env_clicked)
        buttons_layout.addWidget(get_env_btn)
        get_scene_btn = QtWidgets.QPushButton("get_from_scene")
        get_scene_btn.clicked.connect(self._on_get_from_scene_clicked)
        buttons_layout.addWidget(get_scene_btn)
        check_task_btn = QtWidgets.QPushButton("check taskid")
        check_task_btn.clicked.connect(self._on_check_taskid_clicked)
        buttons_layout.addWidget(check_task_btn)
        content_layout.addLayout(buttons_layout)
        
        # Task info (read-only)
        self.task_info_label = QtWidgets.QLabel("project: - parent: - taskname: -")
        content_layout.addWidget(self.task_info_label)
        
        # Asset names section
        self.asset_names_group = QtWidgets.QGroupBox("Asset names")
        asset_names_layout = QtWidgets.QVBoxLayout(self.asset_names_group)
        
        # Buttons: cr_new, get_ex
        asset_buttons_layout = QtWidgets.QHBoxLayout()
        cr_new_btn = QtWidgets.QPushButton("cr_new")
        cr_new_btn.clicked.connect(self._on_cr_new_clicked)
        asset_buttons_layout.addWidget(cr_new_btn)
        get_ex_btn = QtWidgets.QPushButton("get_ex")
        get_ex_btn.clicked.connect(self._on_get_ex_clicked)
        asset_buttons_layout.addWidget(get_ex_btn)
        asset_names_layout.addLayout(asset_buttons_layout)
        
        # Assets menu (created dynamically by get_ex, hidden when use_custom == 0)
        assets_label_layout = QtWidgets.QHBoxLayout()
        self.assets_label = QtWidgets.QLabel("Asset names:")
        assets_label_layout.addWidget(self.assets_label)
        self.assets_combo = QtWidgets.QComboBox()
        self.assets_combo.setEditable(False)
        assets_label_layout.addWidget(self.assets_combo)
        self.assets_widget = QtWidgets.QWidget()
        self.assets_widget.setLayout(assets_label_layout)
        self.assets_widget.setVisible(False)  # Hidden by default until get_ex is clicked
        asset_names_layout.addWidget(self.assets_widget)
        self._assets_created = False  # Track if assets widget was created via get_ex
        
        # Asset name input (created dynamically by cr_new, hidden when use_custom == 0)
        name_label_layout = QtWidgets.QHBoxLayout()
        name_label_layout.addWidget(QtWidgets.QLabel("Asset name:"))
        self.name_edit = QtWidgets.QLineEdit()
        name_label_layout.addWidget(self.name_edit)
        self.name_widget = QtWidgets.QWidget()
        self.name_widget.setLayout(name_label_layout)
        self.name_widget.setVisible(False)  # Hidden by default until cr_new is clicked
        asset_names_layout.addWidget(self.name_widget)
        self._name_created = False  # Track if name widget was created via cr_new
        
        # Type dropdown (created dynamically by cr_new, hidden when use_custom == 0)
        type_label_layout = QtWidgets.QHBoxLayout()
        type_label_layout.addWidget(QtWidgets.QLabel("Asset type:"))
        self.ass_type_combo = QtWidgets.QComboBox()
        self.ass_type_combo.setEditable(False)
        # Add default asset types
        self.ass_type_combo.addItems(['Geometry', 'Animation', 'Rig', 'Scene', 'Usd', 'Camera', 'FX', 'Textures'])
        type_label_layout.addWidget(self.ass_type_combo)
        self.ass_type_widget = QtWidgets.QWidget()
        self.ass_type_widget.setLayout(type_label_layout)
        self.ass_type_widget.setVisible(False)  # Hidden by default until cr_new is clicked
        asset_names_layout.addWidget(self.ass_type_widget)
        self._ass_type_created = False  # Track if ass_type widget was created via cr_new
        
        # set_this button
        set_this_btn = QtWidgets.QPushButton("set_this")
        set_this_btn.clicked.connect(self._on_set_this_clicked)
        asset_names_layout.addWidget(set_this_btn)
        
        content_layout.addWidget(self.asset_names_group)
        
        # asset_id and asset_name (legacy)
        asset_id_layout = QtWidgets.QHBoxLayout()
        asset_id_layout.addWidget(QtWidgets.QLabel("asset_id:"))
        self.asset_id_edit = QtWidgets.QLineEdit()
        asset_id_layout.addWidget(self.asset_id_edit)
        content_layout.addLayout(asset_id_layout)
        
        asset_name_layout = QtWidgets.QHBoxLayout()
        asset_name_layout.addWidget(QtWidgets.QLabel("asset_name:"))
        self.asset_name_edit = QtWidgets.QLineEdit()
        asset_name_layout.addWidget(self.asset_name_edit)
        content_layout.addLayout(asset_name_layout)
        
        # type (legacy)
        type_legacy_layout = QtWidgets.QHBoxLayout()
        type_legacy_layout.addWidget(QtWidgets.QLabel("type:"))
        self.type_combo = QtWidgets.QComboBox()
        self.type_combo.setEditable(False)
        # Add default asset types (same as ass_type_combo)
        self.type_combo.addItems(['Geometry', 'Animation', 'Rig', 'Scene', 'Usd', 'Camera', 'FX', 'Textures', 'Render', 'Compositing', 'Upload', 'Layout'])
        type_legacy_layout.addWidget(self.type_combo)
        apply_asset_btn = QtWidgets.QPushButton("apply to asset")
        apply_asset_btn.clicked.connect(self._on_apply_asset_clicked)
        type_legacy_layout.addWidget(apply_asset_btn)
        content_layout.addLayout(type_legacy_layout)
        
        # target_asset (empty in standalone)
        target_layout = QtWidgets.QHBoxLayout()
        target_layout.addWidget(QtWidgets.QLabel("target_asset:"))
        self.target_asset_edit = QtWidgets.QLineEdit()
        self.target_asset_edit.setEnabled(False)  # Not used in standalone
        target_layout.addWidget(self.target_asset_edit)
        content_layout.addLayout(target_layout)
        
        # Add content container to main layout
        layout.addWidget(self.task_definition_content)
        
        # Apply initial visibility state
        self._on_use_custom_changed()
        
        parent_layout.addWidget(group)
    
    def _create_task_readonly_section(self, parent_layout):
        """Create Task section (read-only fields)."""
        group = QtWidgets.QGroupBox("Task")
        layout = QtWidgets.QVBoxLayout(group)
        
        self.task_id_label = QtWidgets.QLabel("Task task_id: -")
        layout.addWidget(self.task_id_label)
        self.task_project_label = QtWidgets.QLabel("Task Project: -")
        layout.addWidget(self.task_project_label)
        self.task_parent_label = QtWidgets.QLabel("Task parent: -")
        layout.addWidget(self.task_parent_label)
        self.task_name_label = QtWidgets.QLabel("Task name: -")
        layout.addWidget(self.task_name_label)
        
        parent_layout.addWidget(group)
    
    def _create_asset_readonly_section(self, parent_layout):
        """Create Asset section (read-only fields)."""
        group = QtWidgets.QGroupBox("Asset")
        layout = QtWidgets.QVBoxLayout(group)
        
        self.asset_project_label = QtWidgets.QLabel("Project: -")
        layout.addWidget(self.asset_project_label)
        self.asset_parent_label = QtWidgets.QLabel("Parent: -")
        layout.addWidget(self.asset_parent_label)
        self.asset_type_label = QtWidgets.QLabel("Type: -")
        layout.addWidget(self.asset_type_label)
        self.asset_name_label = QtWidgets.QLabel("Name: -")
        layout.addWidget(self.asset_name_label)
        self.asset_asset_id_label = QtWidgets.QLabel("Asset asset_id: -")
        layout.addWidget(self.asset_asset_id_label)
        
        parent_layout.addWidget(group)
    
    def _create_snapshot_playblast_section(self, parent_layout):
        """Create Snapshot/Playblast section."""
        group = QtWidgets.QGroupBox("Snapshot/Playblast")
        layout = QtWidgets.QVBoxLayout(group)
        
        # use_snapshot
        self.use_snapshot_checkbox = QtWidgets.QCheckBox("use_snapshot")
        self.use_snapshot_checkbox.setChecked(True)
        layout.addWidget(self.use_snapshot_checkbox)
        
        # playblast path
        playblast_layout = QtWidgets.QHBoxLayout()
        playblast_layout.addWidget(QtWidgets.QLabel("playblast:"))
        self.playblast_edit = QtWidgets.QLineEdit()
        playblast_layout.addWidget(self.playblast_edit)
        browse_playblast_btn = QtWidgets.QPushButton("...")
        browse_playblast_btn.setMaximumWidth(30)
        browse_playblast_btn.clicked.connect(self._browse_playblast)
        playblast_layout.addWidget(browse_playblast_btn)
        layout.addLayout(playblast_layout)
        
        # use_playblast
        self.use_playblast_checkbox = QtWidgets.QCheckBox("use_playblast")
        self.use_playblast_checkbox.setChecked(False)
        layout.addWidget(self.use_playblast_checkbox)
        
        # thumbnail_path (optional - for versions without playblast)
        thumbnail_layout = QtWidgets.QHBoxLayout()
        thumbnail_layout.addWidget(QtWidgets.QLabel("thumbnail_path:"))
        self.thumbnail_edit = QtWidgets.QLineEdit()
        self.thumbnail_edit.setPlaceholderText("Optional: image for preview. With playblast: overrides auto-thumbnail. Without: sets preview.")
        thumbnail_layout.addWidget(self.thumbnail_edit)
        browse_thumbnail_btn = QtWidgets.QPushButton("...")
        browse_thumbnail_btn.setMaximumWidth(30)
        browse_thumbnail_btn.clicked.connect(self._browse_thumbnail)
        thumbnail_layout.addWidget(browse_thumbnail_btn)
        layout.addLayout(thumbnail_layout)
        
        parent_layout.addWidget(group)
    
    def _create_components_section(self, parent_layout):
        """Create Components section."""
        group = QtWidgets.QGroupBox("components")
        layout = QtWidgets.QVBoxLayout(group)
        
        # Components count
        comp_count_layout = QtWidgets.QHBoxLayout()
        comp_count_layout.addWidget(QtWidgets.QLabel("components num:"))
        self.components_spin = QtWidgets.QSpinBox()
        self.components_spin.setMinimum(0)
        self.components_spin.setMaximum(100)
        self.components_spin.setValue(0)
        self.components_spin.valueChanged.connect(self._update_component_tabs)
        comp_count_layout.addWidget(self.components_spin)
        plus_btn = QtWidgets.QPushButton("+")
        plus_btn.setMaximumWidth(30)
        plus_btn.clicked.connect(lambda: self.components_spin.setValue(self.components_spin.value() + 1))
        comp_count_layout.addWidget(plus_btn)
        minus_btn = QtWidgets.QPushButton("-")
        minus_btn.setMaximumWidth(30)
        minus_btn.clicked.connect(lambda: self.components_spin.setValue(max(0, self.components_spin.value() - 1)))
        comp_count_layout.addWidget(minus_btn)
        clear_btn = QtWidgets.QPushButton("Clear")
        clear_btn.clicked.connect(lambda: self.components_spin.setValue(0))
        comp_count_layout.addWidget(clear_btn)
        layout.addLayout(comp_count_layout)
        
        # Component tabs
        self.component_tabs = QtWidgets.QTabWidget()
        self.component_tabs.setTabsClosable(False)
        layout.addWidget(self.component_tabs)
        
        parent_layout.addWidget(group)
    
    def _create_comment_section(self, parent_layout):
        """Create Comment section."""
        group = QtWidgets.QGroupBox("Version Comment")
        layout = QtWidgets.QVBoxLayout(group)
        
        self.comment_edit = QtWidgets.QTextEdit()
        self.comment_edit.setMaximumHeight(80)
        self.comment_edit.setPlaceholderText("Enter version comment...")
        layout.addWidget(self.comment_edit)
        
        parent_layout.addWidget(group)
    
    def _update_component_tabs(self, count: int):
        """Update component tabs based on count."""
        current_count = self.component_tabs.count()
        
        # Add new tabs if count increased
        for i in range(current_count, count):
            tab = ComponentTabWidget(i, self)
            self.component_tabs.addTab(tab, str(i + 1))
        
        # Remove tabs if count decreased
        for i in range(count, current_count):
            self.component_tabs.removeTab(count)
    
    def _browse_playblast(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Playblast File", self.playblast_edit.text()
        )
        if file_path:
            self.playblast_edit.setText(file_path)
    
    def _browse_thumbnail(self):
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Select Thumbnail Image",
            self.thumbnail_edit.text() if hasattr(self, 'thumbnail_edit') else "",
            "Images (*.png *.jpg *.jpeg *.bmp *.tiff *.tif);;All Files (*)"
        )
        if file_path and hasattr(self, 'thumbnail_edit'):
            self.thumbnail_edit.setText(file_path)
    
    # Button handlers - Task Definition logic (based on fselector.py)
    def _on_get_from_env_clicked(self):
        """Get task_id from environment (mimics fselector.get_from_env)."""
        task_id = os.getenv("FTRACK_CONTEXTID", "")
        if task_id:
            self.set_parameter('task_Id', task_id)
            self._on_check_taskid_clicked()
        else:
            QtWidgets.QMessageBox.warning(
                self, "Warning", "FTRACK_CONTEXTID environment variable is not set."
            )
    
    def _on_get_from_scene_clicked(self):
        """Get task_id from scene (not applicable in standalone Qt)."""
        QtWidgets.QMessageBox.information(
            self, "Info", "This function is only available in DCC applications (Houdini, Maya, etc.)."
        )
    
    def _on_check_taskid_clicked(self):
        """Check and validate task_id (uses core logic through Qt bridge)."""
        _log.info("[publisher_widget] _on_check_taskid_clicked called")
        if CORE_LOGIC_AVAILABLE:
            _log.info("[publisher_widget] Using core logic (check_task_id_qt)")
            check_task_id_qt(self, self._session, self.task_info_label)
        else:
            _log.warning("[publisher_widget] Core logic not available, using fallback")
            # Fallback to direct implementation
            if not self._session:
                QtWidgets.QMessageBox.warning(
                    self, "Warning", "Ftrack session is not available."
                )
                return
            
            task_id = self.get_parameter('task_Id')
            if not task_id:
                self.task_info_label.setText("project: - parent: - taskname: -")
                return
            
            try:
                task = self._session.get('Task', task_id)
                task_name = task['name']
                parent = task['parent']
                project = parent['project']
                
                info_text = f"project: {project['name']}    parent: {parent['name']}    taskname: {task_name}"
                self.task_info_label.setText(info_text)
            except Exception as e:
                self.task_info_label.setText("")
                QtWidgets.QMessageBox.warning(
                    self, "Error", f"Failed to validate task_id: {e}"
                )
    
    def _on_apply_task_clicked(self):
        """Apply task_id to asset parameters (uses core logic through Qt bridge)."""
        _log.info("[publisher_widget] _on_apply_task_clicked called")
        if CORE_LOGIC_AVAILABLE:
            _log.info("[publisher_widget] Using core logic (apply_task_id_qt)")
            apply_task_id_qt(self, self._session)
        else:
            _log.warning("[publisher_widget] Core logic not available, using fallback")
            # Fallback to direct implementation
            if not self._session:
                QtWidgets.QMessageBox.warning(
                    self, "Warning", "Ftrack session is not available."
                )
                return
            
            task_id = self.get_parameter('task_Id')
            if not task_id:
                self.task_info_label.setText("undefined")
                return
            
            # Simplified fallback - just set task params
            try:
                new_task = self._session.get('Task', task_id)
                new_task_name = new_task['name']
                new_parent = new_task['parent']
                new_parent_name = new_parent['name']
                new_project = new_parent['project']
                new_project_name = new_project['name']
                
                self.set_parameter('p_task_id', task_id)
                self.set_parameter('task_project', new_project_name)
                self.set_parameter('task_parent', new_parent_name)
                self.set_parameter('task_name', new_task_name)
            except Exception as e:
                QtWidgets.QMessageBox.warning(
                    self, "Error", f"Failed to apply task_id: {e}"
                )
    
    def _on_cr_new_clicked(self):
        """Create new asset (mimics fselector.create_new).
        
        Marks name and ass_type as created, marks assets as not created.
        Then applies use_custom visibility rules.
        """
        # Mark name and ass_type as created, assets as not created (mimics HDA behavior)
        self._name_created = True
        self._ass_type_created = True
        self._assets_created = False
        
        # Apply use_custom visibility rules
        self._on_use_custom_changed()
    
    def _on_get_ex_clicked(self):
        """Get existing assets (uses core logic through Qt bridge).
        
        Loads list of assets from task and populates assets menu.
        Marks assets as created, marks name and ass_type as not created.
        Then applies use_custom visibility rules.
        """
        _log.info("[publisher_widget] _on_get_ex_clicked called")
        if not self._session:
            _log.warning("[publisher_widget] Ftrack session is not available")
            QtWidgets.QMessageBox.warning(
                self, "Warning", "Ftrack session is not available."
            )
            return
        
        task_id = self.get_parameter('task_Id')
        _log.info(f"[publisher_widget] Got task_id: {task_id}")
        if not task_id:
            _log.warning("[publisher_widget] Task ID is empty")
            QtWidgets.QMessageBox.warning(
                self, "Warning", "Task ID is empty. Set Task Id first."
            )
            return
        
        try:
            if CORE_LOGIC_AVAILABLE:
                _log.info("[publisher_widget] Using core logic (get_assets_list_qt)")
                unique_version, unique_types = get_assets_list_qt(self._session, task_id)
                _log.info(f"[publisher_widget] Got {len(unique_version)} assets from core logic")
            else:
                # Fallback to direct implementation
                task = self._session.get('Task', task_id)
                parent_id = task['parent_id']
                assets = self._session.query(f'Asset where parent.id is "{parent_id}"').all()
                
                unique_version = {}
                unique_types = {}
                seen = set()
                sorted_assets = sorted(assets, key=lambda asset_entity: asset_entity['name'].lower()) if assets else []
                
                for asset in sorted_assets:
                    try:
                        asset_name = asset['name']
                        asset_id = asset['id']
                        asset_type = asset['type']['name']
                        if asset_name not in seen:
                            unique_version[asset_name] = asset_id
                            unique_types[asset_name] = asset_type
                            seen.add(asset_name)
                    except Exception:
                        continue
            
            # Populate assets combo
            self.assets_combo.clear()
            menu_options_k = []
            menu_options_v = []
            for key, value in unique_version.items():
                menu_options_k.append(str(key) + '    type: ' + unique_types[key])
                menu_options_v.append(str(value))
            
            self.assets_combo.addItems(menu_options_k)
            # Store IDs in userData or separate mapping
            self._assets_menu_ids = menu_options_v
            
            # Mark assets as created, name and ass_type as not created (mimics HDA behavior)
            self._assets_created = True
            self._name_created = False
            self._ass_type_created = False
            
            # Apply use_custom visibility rules
            self._on_use_custom_changed()
            
        except Exception as e:
            QtWidgets.QMessageBox.warning(
                self, "Error", f"Failed to load assets: {e}"
            )
    
    def _on_set_this_clicked(self):
        """Set asset from name/type (uses core logic through Qt bridge)."""
        _log.info("[publisher_widget] _on_set_this_clicked called")
        if not self._session:
            _log.warning("[publisher_widget] Ftrack session is not available")
            QtWidgets.QMessageBox.warning(
                self, "Warning", "Ftrack session is not available."
            )
            return
        
        # Determine which mode we're in (assets menu or name/type fields)
        assets_menu_index = None
        if hasattr(self, '_assets_created') and self._assets_created and self.assets_combo.count() > 0:
            assets_menu_index = self.assets_combo.currentIndex()
            _log.info(f"[publisher_widget] Assets menu mode, index: {assets_menu_index}")
        else:
            _log.info("[publisher_widget] Name/type fields mode")
        
        if CORE_LOGIC_AVAILABLE:
            _log.info("[publisher_widget] Using core logic (apply_name_qt)")
            apply_name_qt(
                self, 
                self._session, 
                assets_menu_ids=self._assets_menu_ids if hasattr(self, '_assets_menu_ids') else None,
                assets_menu_index=assets_menu_index
            )
        else:
            # Fallback to direct implementation
            if assets_menu_index is not None and assets_menu_index >= 0 and assets_menu_index < len(self._assets_menu_ids):
                asset_id = self._assets_menu_ids[assets_menu_index]
                asset_label = self.assets_combo.currentText()
                asset_name = asset_label.split()[0]
                
                try:
                    asset = self._session.get('Asset', asset_id)
                    asset_type = asset['type']['name']
                    
                    if asset_name != 'new_asset':
                        self.set_parameter('asset_id', asset_id)
                        self.set_parameter('asset_name', asset_name)
                        self.set_parameter('type', asset_type)
                except Exception as e:
                    QtWidgets.QMessageBox.warning(
                        self, "Error", f"Failed to load asset: {e}"
                    )
            elif hasattr(self, '_name_created') and self._name_created:
                name = self.name_edit.text()
                ass_type = self.ass_type_combo.currentText() if self.ass_type_combo.currentIndex() >= 0 else ""
                task_id = self.get_parameter('task_Id')
                
                if not task_id:
                    QtWidgets.QMessageBox.warning(
                        self, "Warning", "Task ID is empty. Set Task Id first."
                    )
                    return
                
                # Check if asset with same name already exists
                exists = False
                try:
                    task = self._session.get('Task', task_id)
                    parent_id = task['parent_id']
                    existing_asset = self._session.query(
                        f'Asset where name is "{name}" and parent.id is "{parent_id}"'
                    ).first()
                    if existing_asset is not None:
                        exists = True
                    else:
                        existing_build = self._session.query(
                            f'AssetBuild where name is "{name}" and parent.id is "{parent_id}"'
                        ).first()
                        if existing_build is not None:
                            exists = True
                except Exception as e:
                    _log.warning(f"Failed to validate existing name '{name}': {e}")
                
                if exists:
                    QtWidgets.QMessageBox.warning(
                        self, "Warning", f"Name '{name}' already exists. Try to select from existing assets."
                    )
                    return
                
                # Clear asset_id and set name/type
                self.set_parameter('asset_id', "")
                self.set_parameter('asset_name', name)
                self.set_parameter('type', ass_type)
            else:
                QtWidgets.QMessageBox.information(
                    self, "Info", "No asset selected. Please use 'get_ex' or 'cr_new' first."
                )
    
    def _on_apply_asset_clicked(self):
        """Apply asset parameters (uses core logic through Qt bridge)."""
        _log.info("[publisher_widget] _on_apply_asset_clicked called")
        if CORE_LOGIC_AVAILABLE:
            _log.info("[publisher_widget] Using core logic (apply_asset_params_qt)")
            apply_asset_params_qt(self, self._session, self.task_info_label)
        else:
            # Fallback to direct implementation
            if not self._session:
                QtWidgets.QMessageBox.warning(
                    self, "Warning", "Ftrack session is not available."
                )
                return
            
            try:
                asset_id = self.get_parameter('asset_id')
                asset_name = self.get_parameter('asset_name')
                cur_type = self.get_parameter('type')
                task_id = self.get_parameter('task_Id')
            except Exception as e:
                QtWidgets.QMessageBox.warning(
                    self, "Error", f"Failed to read parameters: {e}"
                )
                return
            
            if asset_id:
                try:
                    asset = self._session.query(f"Asset where id is '{asset_id}'").one()
                    parent = asset['parent']
                    project = parent['project']
                    asset_type_name = cur_type if cur_type else asset['type']['name']
                    asset_name_final = asset_name if asset_name else asset['name']
                    
                    self.set_parameter('p_project', project['name'])
                    self.set_parameter('p_parent', parent['name'])
                    self.set_parameter('p_asset_type', asset_type_name)
                    self.set_parameter('p_asset_name', asset_name_final)
                    self.set_parameter('p_asset_id', asset_id)
                except Exception as e:
                    QtWidgets.QMessageBox.warning(
                        self, "Error", f"Failed to resolve Asset '{asset_id}': {e}"
                    )
                return
            
            if not task_id:
                self.task_info_label.setText('undefined')
                return
            
            try:
                task = self._session.get('Task', task_id)
                parent = task['parent']
                project = parent['project']
                
                self.set_parameter('p_project', project['name'])
                self.set_parameter('p_parent', parent['name'])
                self.set_parameter('p_asset_type', cur_type)
                self.set_parameter('p_asset_name', asset_name)
                self.set_parameter('p_asset_id', "")
            except Exception as e:
                QtWidgets.QMessageBox.warning(
                    self, "Error", f"Failed to apply asset parameters: {e}"
                )
    
    def _on_use_custom_changed(self, checked=None):
        """Handle use_custom checkbox state change.
        
        Logic (based on fselector.py and HDA behavior):
        - In HDA, when use_custom == 0, the ENTIRE "Asset names" group is hidden
        - When use_custom == 1, the group is shown, and individual widgets (assets/name/ass_type)
          are shown/hidden based on which were created (get_ex or cr_new)
        
        So:
        - use_custom == 0 (unchecked): Hide entire asset_names_group
        - use_custom == 1 (checked): Show asset_names_group, then show/hide individual widgets
        """
        if checked is None:
            use_custom = self.use_custom_checkbox.isChecked()
        else:
            use_custom = bool(checked)
        
        # Hide/show entire Task Definition content (everything after use_custom checkbox)
        if hasattr(self, 'task_definition_content'):
            if use_custom:
                self.task_definition_content.show()
            else:
                self.task_definition_content.hide()
        
        # If group is visible, show/hide individual widgets based on whether they were created
        if use_custom:
            if hasattr(self, 'assets_widget') and hasattr(self, '_assets_created'):
                visible = self._assets_created
                if self.assets_widget is not None:
                    if visible:
                        self.assets_widget.show()
                    else:
                        self.assets_widget.hide()
            if hasattr(self, 'name_widget') and hasattr(self, '_name_created'):
                visible = self._name_created
                if self.name_widget is not None:
                    if visible:
                        self.name_widget.show()
                    else:
                        self.name_widget.hide()
            if hasattr(self, 'ass_type_widget') and hasattr(self, '_ass_type_created'):
                visible = self._ass_type_created
                if self.ass_type_widget is not None:
                    if visible:
                        self.ass_type_widget.show()
                    else:
                        self.ass_type_widget.hide()
        
        # Force layout recalculation - find the scroll widget and update it
        if hasattr(self, 'task_definition_content'):
            # Find parent scroll widget
            parent = self.task_definition_content.parent()
            scroll_widget = None
            while parent:
                if isinstance(parent, QtWidgets.QWidget) and hasattr(parent, 'layout'):
                    scroll_widget = parent
                    break
                parent = parent.parent()
            
            # Update the scroll widget's layout
            if scroll_widget and scroll_widget.layout():
                scroll_widget.layout().update()
                scroll_widget.layout().invalidate()
                scroll_widget.updateGeometry()
                scroll_widget.update()
            
            # Also update the content container itself
            self.task_definition_content.updateGeometry()
            self.task_definition_content.update()
            
            # Find and update scroll area if exists
            scroll_parent = self.task_definition_content.parent()
            while scroll_parent:
                if isinstance(scroll_parent, QtWidgets.QScrollArea):
                    scroll_parent.viewport().update()
                    scroll_parent.update()
                    break
                scroll_parent = scroll_parent.parent()
    
    def _on_publish_clicked(self):
        """Publish button clicked."""
        _log.info("[publisher_widget] _on_publish_clicked called")
        
        try:
            # Import publisher components
            from ftrack_inout.publisher.core import JobBuilder, Publisher
            
            # 1. Build PublishJob from widget
            _log.info("[publisher_widget] Building PublishJob from widget...")
            job = JobBuilder.from_qt_widget(self, source_dcc="standalone")
            
            # 2. Validate job
            is_valid, errors = job.validate()
            if not is_valid:
                error_msg = "Validation errors:\n" + "\n".join(f"• {e}" for e in errors)
                _log.warning(f"[publisher_widget] {error_msg}")
                QtWidgets.QMessageBox.warning(self, "Validation Failed", error_msg)
                return
            
            # 3. Execute publish (dry_run=True for now)
            _log.info("[publisher_widget] Executing publish (dry_run=True)...")
            publisher = Publisher(session=self._session, dry_run=True)
            result = publisher.execute(job)
            
            # 4. Show result
            if result.success:
                msg = (
                    f"DRY RUN completed successfully!\n\n"
                    f"Would create:\n"
                    f"• Asset Version #{result.asset_version_number}\n"
                    f"• {len(result.component_ids)} component(s)\n\n"
                    f"Component IDs:\n"
                    + "\n".join(f"  - {cid}" for cid in result.component_ids)
                )
                _log.info(f"[publisher_widget] {msg}")
                QtWidgets.QMessageBox.information(self, "Publish Preview", msg)
            else:
                _log.error(f"[publisher_widget] Publish failed: {result.error_message}")
                QtWidgets.QMessageBox.critical(self, "Publish Failed", result.error_message)
                
        except ImportError as e:
            _log.error(f"[publisher_widget] Import error: {e}", exc_info=True)
            QtWidgets.QMessageBox.critical(
                self, "Import Error",
                f"Failed to import publisher components:\n{e}"
            )
        except Exception as e:
            _log.error(f"[publisher_widget] Unexpected error: {e}", exc_info=True)
            QtWidgets.QMessageBox.critical(
                self, "Error",
                f"Unexpected error during publish:\n{e}"
            )
    
    # Parameter access methods (matching HDA parameter names)
    def get_parameter(self, name: str) -> Any:
        """Get parameter value by name (matching HDA parameter names)."""
        # Map UI widgets to parameter names
        param_map = {
            'task_Id': self.task_id_edit.text(),
            'p_task_id': self.task_id_edit.text(),
            'use_custom': 1 if self.use_custom_checkbox.isChecked() else 0,
            'name': self.name_edit.text(),
            'ass_type': self.ass_type_combo.currentText() if self.ass_type_combo.currentIndex() >= 0 else '',
            'asset_id': self.asset_id_edit.text(),
            'asset_name': self.asset_name_edit.text(),
            'type': self.type_combo.currentText() if self.type_combo.currentIndex() >= 0 else '',
            'p_asset_id': self.asset_id_edit.text(),
            'p_asset_name': self.asset_name_edit.text(),
            'p_asset_type': self.type_combo.currentText() if self.type_combo.currentIndex() >= 0 else '',
            'target_asset': self.target_asset_edit.text(),
            'use_snapshot': 1 if self.use_snapshot_checkbox.isChecked() else 0,
            'use_playblast': 1 if self.use_playblast_checkbox.isChecked() else 0,
            'playblast': self.playblast_edit.text(),
            'thumbnail_path': self.thumbnail_edit.text().strip() if hasattr(self, 'thumbnail_edit') else '',
            'components': self.components_spin.value(),
            'comment': self.comment_edit.toPlainText() if hasattr(self, 'comment_edit') else '',
        }
        
        # Component parameters
        if name.startswith('comp_name') or name.startswith('file_path') or name.startswith('export') or \
           name.startswith('meta_count') or name.startswith('key') or name.startswith('value'):
            # Extract index from parameter name
            for i in range(self.component_tabs.count()):
                tab = self.component_tabs.widget(i)
                comp_data = tab.get_component_data()
                if name in comp_data:
                    return comp_data[name]
            return ''
        
        return param_map.get(name, '')
    
    def set_parameter(self, name: str, value: Any):
        """Set parameter value by name (matching HDA parameter names)."""
        value_str = str(value).strip() if value else ''
        _log.debug(f"[publisher_widget] set_parameter '{name}' = '{value_str}'")
        
        # Map parameter names to UI widgets
        if name == 'task_Id' or name == 'p_task_id':
            self.task_id_edit.setText(value_str)
            if hasattr(self, 'task_id_label'):
                self.task_id_label.setText(f"Task task_id: {value_str}" if value_str else "Task task_id: -")
        elif name == 'task_project':
            if hasattr(self, 'task_project_label'):
                self.task_project_label.setText(f"Task Project: {value_str}" if value_str else "Task Project: -")
        elif name == 'task_parent':
            if hasattr(self, 'task_parent_label'):
                self.task_parent_label.setText(f"Task parent: {value_str}" if value_str else "Task parent: -")
        elif name == 'task_name':
            if hasattr(self, 'task_name_label'):
                self.task_name_label.setText(f"Task name: {value_str}" if value_str else "Task name: -")
        elif name == 'p_project':
            if hasattr(self, 'asset_project_label'):
                self.asset_project_label.setText(f"Project: {value_str}" if value_str else "Project: -")
        elif name == 'p_parent':
            if hasattr(self, 'asset_parent_label'):
                self.asset_parent_label.setText(f"Parent: {value_str}" if value_str else "Parent: -")
        elif name == 'use_custom':
            self.use_custom_checkbox.setChecked(value != 0)
        elif name == 'name':
            self.name_edit.setText(value_str)
        elif name == 'ass_type':
            idx = self.ass_type_combo.findText(value_str)
            if idx >= 0:
                self.ass_type_combo.setCurrentIndex(idx)
        elif name == 'asset_id' or name == 'p_asset_id':
            self.asset_id_edit.setText(value_str)
            if hasattr(self, 'asset_asset_id_label'):
                self.asset_asset_id_label.setText(f"Asset asset_id: {value_str}" if value_str else "Asset asset_id: -")
        elif name == 'asset_name' or name == 'p_asset_name':
            self.asset_name_edit.setText(value_str)
            if hasattr(self, 'asset_name_label'):
                self.asset_name_label.setText(f"Name: {value_str}" if value_str else "Name: -")
        elif name == 'type' or name == 'p_asset_type':
            if value_str:
                idx = self.type_combo.findText(value_str)
                if idx >= 0:
                    self.type_combo.setCurrentIndex(idx)
                    _log.debug(f"[publisher_widget] set_parameter '{name}' = '{value_str}' (index: {idx})")
                else:
                    # Type not found in combo, add it if combo is editable, or log warning
                    _log.warning(f"[publisher_widget] set_parameter '{name}' = '{value_str}' not found in type_combo items. Available: {[self.type_combo.itemText(i) for i in range(self.type_combo.count())]}")
                    # Try to add it if combo allows
                    if self.type_combo.isEditable() or True:  # Always try to add missing types
                        self.type_combo.addItem(value_str)
                        self.type_combo.setCurrentIndex(self.type_combo.count() - 1)
                        _log.info(f"[publisher_widget] Added '{value_str}' to type_combo and set as current")
                # Update asset_type_label
                if hasattr(self, 'asset_type_label'):
                    self.asset_type_label.setText(f"Type: {value_str}")
            else:
                # Clear selection
                self.type_combo.setCurrentIndex(-1)
                _log.debug(f"[publisher_widget] set_parameter '{name}' = '' (cleared)")
                if hasattr(self, 'asset_type_label'):
                    self.asset_type_label.setText("Type: -")
        elif name == 'target_asset':
            self.target_asset_edit.setText(str(value))
        elif name == 'use_snapshot':
            self.use_snapshot_checkbox.setChecked(value != 0)
        elif name == 'use_playblast':
            self.use_playblast_checkbox.setChecked(value != 0)
        elif name == 'playblast':
            self.playblast_edit.setText(str(value))
        elif name == 'thumbnail_path':
            if hasattr(self, 'thumbnail_edit'):
                self.thumbnail_edit.setText(str(value) if value else '')
        elif name == 'components':
            self.components_spin.setValue(int(value) if value else 0)
        elif name == 'comment':
            if hasattr(self, 'comment_edit'):
                self.comment_edit.setPlainText(str(value) if value else '')
        # Component parameters are handled via component tabs
        elif name.startswith('comp_name') or name.startswith('file_path') or name.startswith('export') or \
             name.startswith('meta_count') or name.startswith('key') or name.startswith('value'):
            # Component parameters are set via component tabs
            pass


if __name__ == '__main__':
    import sys
    app = QtWidgets.QApplication(sys.argv)
    widget = PublisherWidget()
    widget.show()
    sys.exit(app.exec_())
