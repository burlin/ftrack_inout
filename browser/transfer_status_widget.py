"""
Transfer Status Widget for Ftrack Browser / Mroya Transfer Manager

This module provides a non-modal dialog to monitor the status of
Ftrack component transfer jobs.

Used in both DCC (PySide6) and inside ftrack Connect (usually PySide2),
so Qt import is done with fallback.
"""
import logging
import threading
import json

try:  # Prefer PySide6 when available (newer DCC / standalone tools)
    from PySide6 import QtWidgets, QtCore, QtGui  # type: ignore
except Exception:  # Fallback for ftrack Connect / legacy environments
    from PySide2 import QtWidgets, QtCore, QtGui  # type: ignore

import ftrack_api

# Configure logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Global singleton instance so browser and finput can share one window
_global_dialog_instance = None

class TransferStatusDialog(QtWidgets.QDialog):
    """A dialog to show and monitor ftrack transfer jobs.

    - If parent is None -> behaves as separate tool window (DCC/standalone).
    - If parent is set (e.g., widget in ftrack Connect) -> embeds
      into parent as regular dialog without top-level flags.
    """

    # Signal to notify when a transfer is complete, passing the component ID
    transfer_completed = QtCore.Signal(str)

    def __init__(self, session, parent=None):
        # When parent is passed (MroyaTransferManagerWidget inside Connect),
        # allow Qt to make it a child widget. Otherwise -- separate window.
        super(TransferStatusDialog, self).__init__(parent)

        if parent is None:
            # DCC / standalone: separate tool window on top of Houdini, etc.
            try:
                self.setWindowFlag(QtCore.Qt.Tool, True)
            except Exception:
                pass
            self.setWindowModality(QtCore.Qt.NonModal)
            self.setWindowTitle("Transfer Manager")
            self.setMinimumSize(600, 300)
        else:
            # Embedded in Connect widget: title/size managed by container.
            self.setWindowTitle("Transfer Manager")
        
        self.session = session
        self.active_jobs = {}  # {job_id: {'row': int, 'component_id': str}}

        # Signal to handle event hub callbacks into Qt thread
        self._event_signal = QtCore.Signal(dict) if not hasattr(self, '_event_signal') else self._event_signal

        # UI Setup
        self._setup_ui()

        # By default keep the dialog "always on top" like original behavior.
        try:
            self.always_on_top_chk.setChecked(True)
        except Exception:
            pass

        # Timer for polling job statuses
        self.poll_timer = QtCore.QTimer(self)
        self.poll_timer.timeout.connect(self._check_job_statuses)
        self.poll_timer.start(5000)  # Poll every 5 seconds

        # Start event listener thread (best-effort)
        try:
            self._start_event_listener()
        except Exception as _e:
            logger = logging.getLogger(__name__)
            logger.warning(
                "Failed to start transfer status event listener; falling back to polling only. Reason: %s",
                _e,
            )

    def _setup_ui(self):
        """Create the user interface."""
        self.main_layout = QtWidgets.QVBoxLayout(self)
        
        self.job_table = QtWidgets.QTableWidget()
        self.job_table.setColumnCount(6)
        self.job_table.setHorizontalHeaderLabels(["Component", "Destination", "Size", "Progress", "Job ID", "Status"])
        header = self.job_table.horizontalHeader()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QtWidgets.QHeaderView.ResizeToContents)
        self.job_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.job_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.job_table.setAlternatingRowColors(True)
        # Subtle dark theme for readability (matches browser dialog)
        self.job_table.setStyleSheet(
            "QTableWidget {"
            "  background-color: #1e1e1e;"
            "  alternate-background-color: #242424;"
            "  color: #dddddd;"
            "}"
            "QHeaderView::section {"
            "  background-color: #333333;"
            "  color: #dddddd;"
            "  font-weight: bold;"
            "  padding: 4px;"
            "}"
            "QTableWidget::item {"
            "  padding: 3px;"
            "}"
        )

        self.main_layout.addWidget(self.job_table)

        # Bottom controls: "Always on top" + Close
        bottom_layout = QtWidgets.QHBoxLayout()

        self.always_on_top_chk = QtWidgets.QCheckBox("Stay on Top")
        # Flag enabled by default so window doesn't get lost behind others.
        self.always_on_top_chk.setChecked(True)
        self.always_on_top_chk.toggled.connect(self._on_always_on_top_toggled)
        bottom_layout.addWidget(self.always_on_top_chk)

        bottom_layout.addStretch(1)

        self.close_button = QtWidgets.QPushButton("Close")
        self.close_button.clicked.connect(self.hide)
        bottom_layout.addWidget(self.close_button)

        self.main_layout.addLayout(bottom_layout)

    def _start_event_listener(self):
        """Subscribe to ftrack transfer status events and run event_hub in a background thread."""
        self._logger = logging.getLogger(__name__)

        # Define Qt signal in runtime-safe way
        class _Bridge(QtCore.QObject):
            event_received = QtCore.Signal(dict)
        self._bridge = _Bridge()
        self._bridge.event_received.connect(self._on_transfer_event)

        def _handler(event):
            try:
                data = event.get('data') or {}
                self._logger.info(f"[TransferDialog] Event received: {data}")
                self._bridge.event_received.emit(dict(data))
            except Exception as e:
                self._logger.warning(f"Event handler error: {e}")

        # Ensure event hub is connected to server (remote events)
        try:
            self._logger.info("[TransferDialog] Connecting to Event Hub...")
            self.session.event_hub.connect()
            self._logger.info("[TransferDialog] Event Hub connected.")
        except Exception as e:
            self._logger.warning(f"Event hub connect failed: {e}")

        # Subscribe and spin event hub in thread
        self._logger.info("[TransferDialog] Subscribing to topic 'ftrack.transfer.status'")
        self.session.event_hub.subscribe('topic=ftrack.transfer.status', _handler)

        def _run():
            try:
                self._logger.info("[TransferDialog] Event hub loop started.")
                while True:
                    # Short wait to keep UI responsive and allow thread to exit on app close
                    self.session.event_hub.wait(1)
            except Exception as e:
                self._logger.warning(f"Event hub loop ended: {e}")

        self._event_thread = threading.Thread(target=_run, daemon=True)
        self._event_thread.start()

    @QtCore.Slot(bool)
    def _on_always_on_top_toggled(self, checked):
        """Toggle 'stay on top' behavior for the dialog."""
        try:
            flags = self.windowFlags()
            if checked:
                flags |= QtCore.Qt.WindowStaysOnTopHint
            else:
                flags &= ~QtCore.Qt.WindowStaysOnTopHint
            self.setWindowFlags(flags)
            # Re-show to apply new flags
            self.show()
            self.raise_()
            self.activateWindow()
        except Exception as e:
            logger.warning(f"[TransferDialog] Failed to toggle stay-on-top: {e}")

    @QtCore.Slot(dict)
    def _on_transfer_event(self, data):
        """Update status row immediately when we receive events from the action.

        Currently displaying only text status (running/done/failed),
        without percentages, to keep interface simple and predictable.
        """
        try:
            job_id = data.get('job_id')
            status = data.get('status')
            if not job_id or not status:
                logging.getLogger(__name__).debug(f"[TransferDialog] Ignoring event without job_id/status: {data}")
                return

            job_info = self.active_jobs.get(job_id)
            if not job_info:
                logging.getLogger(__name__).debug(f"[TransferDialog] Event for unknown job {job_id}, active: {list(self.active_jobs.keys())}")
                return

            row = job_info['row']
            status_item = self.job_table.item(row, 5)  # Status column index changed
            progress_item = self.job_table.item(row, 3)  # Progress column

            if status_item:
                status_item.setText(status)
                status_item.setToolTip(f"Status: {status}")
                logging.getLogger(__name__).info(f"[TransferDialog] Job {job_id} -> {status} (event)")
            
            # Update progress from event data
            progress = data.get('progress', 0.0)
            if progress_item and progress is not None:
                progress_percent = int(progress * 100) if isinstance(progress, (int, float)) else 0
                progress_item.setText(f"{progress_percent}%")
                progress_item.setToolTip(f"Progress: {progress_percent}%")

            # Style & finalize immediately on terminal statuses from events
            if status in ('done', 'failed', 'killed'):
                color = QtGui.QColor("#6abf69") if status == 'done' else QtGui.QColor("#d06a6a")
                text_color = QtGui.QColor("#000000")
                bold_font = self.font()
                bold_font.setBold(True)
                for col in range(self.job_table.columnCount()):
                    item = self.job_table.item(row, col)
                    if item:
                        item.setBackground(color)
                        item.setForeground(text_color)
                        item.setFont(bold_font)

                # Remove from active jobs immediately to stop further polling
                job_info = self.active_jobs.pop(job_id, None)
                if job_info and status == 'done':
                    component_id = job_info.get('component_id')
                    logging.getLogger(__name__).info(
                        f"[TransferDialog] Transfer for component {component_id} completed successfully (event)."
                    )
                    self.transfer_completed.emit(component_id)

                if not self.active_jobs:
                    logging.getLogger(__name__).info("[TransferDialog] All monitored jobs have completed (event).")
        except Exception as e:
            logging.getLogger(__name__).warning(f"Failed to apply transfer event: {e}")

    def add_job(self, job, component_name, to_location_name, component_id, total_size_bytes: int = 0):
        """Add a new job to the monitoring table.
        
        Args:
            job: Ftrack Job entity
            component_name: Display name for the component
            to_location_name: Display name for destination location
            component_id: Component ID (for signals)
            total_size_bytes: Total size of components in bytes (0 if unknown)
        """
        if not job or not job.get('id'):
            logger.error("Attempted to add an invalid job.")
            return

        job_id = job['id']
        if job_id in self.active_jobs:
            logger.warning(f"Job {job_id} is already being monitored.")
            return

        row_position = self.job_table.rowCount()
        self.job_table.insertRow(row_position)

        comp_item = QtWidgets.QTableWidgetItem(component_name)
        dest_item = QtWidgets.QTableWidgetItem(to_location_name)
        
        # Size column
        size_text = _format_size(total_size_bytes) if total_size_bytes > 0 else "N/A"
        size_item = QtWidgets.QTableWidgetItem(size_text)
        size_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        
        # Progress column
        progress_item = QtWidgets.QTableWidgetItem("0%")
        progress_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        
        id_item = QtWidgets.QTableWidgetItem(job_id)
        status_text = job.get('status', 'initializing')
        status_item = QtWidgets.QTableWidgetItem(status_text)

        # Tooltips for clarity
        comp_item.setToolTip(f"Component: {component_name}\nID: {component_id}")
        dest_item.setToolTip(f"Destination location: {to_location_name}")
        size_item.setToolTip(f"Total size: {size_text}")
        progress_item.setToolTip("Progress: 0%")
        id_item.setToolTip(job_id)
        status_item.setToolTip(f"Status: {status_text}")

        self.job_table.setItem(row_position, 0, comp_item)
        self.job_table.setItem(row_position, 1, dest_item)
        self.job_table.setItem(row_position, 2, size_item)
        self.job_table.setItem(row_position, 3, progress_item)
        self.job_table.setItem(row_position, 4, id_item)
        self.job_table.setItem(row_position, 5, status_item)

        self.active_jobs[job_id] = {
            'row': row_position,
            'component_id': component_id,
            'total_size_bytes': total_size_bytes
        }
        
        logger.info(f"Started monitoring job {job_id} for component {component_id} at row {row_position}.")
        
        # DISABLED: Do not show window automatically.
        # All transfers are now visualized via "Mroya Transfer Manager" tab in ftrack Connect.
        # Local window is no longer used - it was causing unwanted popups in DCC.
        parent_widget = self.parent()
        logger.info(
            f"TransferStatusDialog.add_job: parent={parent_widget}, "
            f"parent_type={type(parent_widget).__name__ if parent_widget else 'None'}, "
            f"will_not_show=True (transfers managed in ftrack Connect)"
        )
        # Do not show window regardless of parent - all transfers are managed in Connect

        # Kick an early poll shortly after adding the job to catch fast-completing transfers
        try:
            QtCore.QTimer.singleShot(1500, self._check_job_statuses)
        except Exception:
            pass

    @QtCore.Slot()
    def _check_job_statuses(self):
        """Periodically check the status of active jobs."""
        if not self.active_jobs:
            return

        job_ids_to_check = list(self.active_jobs.keys())
        logger.info(f"[TransferDialog] Polling {len(job_ids_to_check)} jobs for status update...")
        completed_jobs = []
        
        try:
            # Batch query (use dialog session; event hub will push terminal updates)
            quoted = ",".join([f'"{jid}"' for jid in job_ids_to_check])
            jobs = self.session.query(f'Job where id in ({quoted})').all()

            for job in jobs:
                job_id = job['id']
                job_info = self.active_jobs.get(job_id)
                if not job_info:
                    continue

                row = job_info['row']
                status_item = self.job_table.item(row, 5)  # Status column index changed
                progress_item = self.job_table.item(row, 3)  # Progress column
                current_status = status_item.text() if status_item else ""
                new_status = job.get('status')

                # Prevent regressions: never downgrade terminal → non-terminal due to commit lag
                terminal = lambda s: s in ('done', 'failed', 'killed')
                if not new_status:
                    continue
                if terminal(current_status) and not terminal(new_status):
                    logger.info(f"[TransferDialog] Ignoring regression {current_status} -> {new_status} for job {job_id}")
                    continue

                # Update status
                if new_status != current_status:
                    status_item.setText(new_status)
                    status_item.setToolTip(f"Status: {new_status}")
                    logger.info(
                        "[TransferDialog] Job %s status changed (poll) %s -> %s",
                        job_id,
                        current_status,
                        new_status,
                    )
                
                # Update progress from job.data
                try:
                    raw_data = job.get('data')
                    job_data = {}
                    if isinstance(raw_data, dict):
                        job_data = raw_data
                    elif isinstance(raw_data, str) and raw_data.strip():
                        job_data = json.loads(raw_data)
                    
                    progress = job_data.get('progress', 0.0)
                    if progress_item and progress is not None:
                        progress_percent = int(progress * 100) if isinstance(progress, (int, float)) else 0
                        progress_item.setText(f"{progress_percent}%")
                        progress_item.setToolTip(f"Progress: {progress_percent}%")
                except Exception as e:
                    logger.debug(f"[TransferDialog] Failed to parse progress for job {job_id}: {e}")

                if new_status in ['done', 'failed', 'killed']:
                    completed_jobs.append(job_id)
                    
                    # Style the row based on status
                    color = QtGui.QColor("#6abf69") if new_status == 'done' else QtGui.QColor("#d06a6a")
                    text_color = QtGui.QColor("#000000") if new_status == 'done' else QtGui.QColor("#000000")
                    bold_font = self.font()
                    bold_font.setBold(True)
                    for col in range(self.job_table.columnCount()):
                        item = self.job_table.item(row, col)
                        if not item:
                            continue
                        item.setBackground(color)
                        item.setForeground(text_color)
                        item.setFont(bold_font)
                    
                    # Emit signal on successful completion
                    if new_status == 'done':
                        component_id = job_info.get('component_id')
                        logger.info(f"[TransferDialog] Transfer for component {component_id} completed successfully.")
                        self.transfer_completed.emit(component_id)

            # Remove completed jobs from the active list
            for job_id in completed_jobs:
                if job_id in self.active_jobs:
                    del self.active_jobs[job_id]
            
            if not self.active_jobs:
                logger.info("[TransferDialog] All monitored jobs have completed.")

        except Exception as e:
            logger.error(f"[TransferDialog] Failed to check job statuses: {e}", exc_info=True)

    def closeEvent(self, event):
        """Hide the dialog on close instead of deleting it."""
        event.ignore()
        self.hide() 


def get_transfer_dialog(session):
    """(Deprecated) TransferStatusDialog now lives only in ftrack Connect (Mroya Transfer Manager).
    
    All transfers are visualized via "Mroya Transfer Manager" tab in Connect,
    local window is no longer used.
    """
    return None