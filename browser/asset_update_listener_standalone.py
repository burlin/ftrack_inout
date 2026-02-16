"""
Standalone asset update listener for FtrackInputWidget.

Listens to mroya.asset.update-notify events from Asset Watcher.
When running outside Ftrack Connect but with same user/host, event hub receives
notifications and we can show "pending update" and "Accept Update" in the widget.
"""

from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Global singleton
_listener: Optional["StandaloneAssetUpdateListener"] = None
_lock = threading.Lock()


def get_listener(session=None) -> Optional["StandaloneAssetUpdateListener"]:
    """Get or create the singleton listener."""
    global _listener
    with _lock:
        if _listener is None and session:
            _listener = StandaloneAssetUpdateListener(session)
        return _listener


def stop_listener() -> None:
    """Stop the global listener."""
    global _listener
    with _lock:
        if _listener:
            _listener.stop()
            _listener = None


class StandaloneAssetUpdateListener:
    """
    Listens to mroya.asset.update-notify events and invokes callbacks for matching components.

    Same session/user/host as Ftrack Connect - events are received.
    """

    def __init__(self, session: Any) -> None:
        self._session = session
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callbacks: Dict[str, Callable[[Dict[str, Any]], None]] = {}
        self._callback_lock = threading.Lock()
        self._main_thread_callback: Optional[Callable[[Callable], None]] = None

    def set_main_thread_dispatcher(self, dispatcher: Callable[[Callable], None]) -> None:
        """Set a callable to run callbacks on main thread (e.g. Qt QTimer.singleShot)."""
        self._main_thread_callback = dispatcher

    def subscribe(
        self,
        key: str,
        asset_id: str,
        component_name: str,
        component_id: str,
        callback: Callable[[Dict[str, Any]], None],
    ) -> None:
        """Register interest in updates for this component. Key is used for unsubscribe."""
        with self._callback_lock:
            self._callbacks[key] = {
                "asset_id": asset_id,
                "component_name": component_name,
                "component_id": component_id,
                "callback": callback,
            }
        logger.info(
            "Subscribed to updates: key=%s asset=%s component=%s",
            key,
            asset_id,
            component_name,
        )
        if not self._running:
            self._start()

    def unsubscribe(self, key: str) -> None:
        """Remove subscription by key."""
        with self._callback_lock:
            if key in self._callbacks:
                del self._callbacks[key]
                logger.info("Unsubscribed: key=%s", key)
        if not self._callbacks and self._running:
            self.stop()

    def _start(self) -> None:
        """Start event hub listener in background thread."""
        if self._running:
            return
        try:
            if not hasattr(self._session, "event_hub"):
                logger.warning("Session has no event_hub")
                return
            hub = self._session.event_hub
            if not hub.connected:
                hub.connect()
                logger.info("Event hub connected")
            hub.subscribe(
                "topic=mroya.asset.update-notify",
                self._on_update_notify,
                priority=10,
            )
            logger.info("Subscribed to mroya.asset.update-notify")
            self._running = True
            self._thread = threading.Thread(target=self._event_loop, daemon=True)
            self._thread.start()
            logger.info("Standalone asset update listener started")
        except Exception as e:
            logger.error("Failed to start listener: %s", e, exc_info=True)

    def stop(self) -> None:
        """Stop the listener."""
        self._running = False
        self._thread = None
        with self._callback_lock:
            self._callbacks.clear()
        logger.info("Standalone asset update listener stopped")

    def _event_loop(self) -> None:
        """Background event loop."""
        while self._running:
            try:
                self._session.event_hub.wait(1)
            except Exception as e:
                logger.debug("Event loop wait: %s", e)
                import time
                time.sleep(1)

    def _on_update_notify(self, event: Any) -> None:
        """Handle mroya.asset.update-notify event."""
        try:
            data = event.get("data", {}) if hasattr(event, "get") else {}
            asset_id = data.get("asset_id")
            component_name = data.get("component_name")
            version_number = data.get("version_number")
            version_id = data.get("version_id")
            component_id = data.get("component_id")
            status = data.get("status", "update_available")
            logger.info(
                "Received update-notify: asset=%s component=%s v=%s status=%s",
                asset_id,
                component_name,
                version_number,
                status,
            )
            with self._callback_lock:
                for key, info in list(self._callbacks.items()):
                    if info["asset_id"] == asset_id and info["component_name"] == component_name:
                        payload = {
                            "asset_id": asset_id,
                            "component_name": component_name,
                            "version_number": version_number,
                            "version_id": version_id,
                            "component_id": component_id,
                            "status": status,
                        }
                        cb = info["callback"]
                        if self._main_thread_callback:
                            self._main_thread_callback(lambda: cb(payload))
                        else:
                            cb(payload)
                        break
        except Exception as e:
            logger.error("Error handling update notify: %s", e, exc_info=True)
