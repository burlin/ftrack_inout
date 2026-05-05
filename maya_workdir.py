"""
Maya-only working directory override.

Persisted per-user via QSettings under ("mroya", "ftrack_inout"),
key "MAYA_WORKDIR". Surfaced in the User Tasks widget (only when running
inside Maya) via a "Set…" button on a dedicated toolbar row.

Reason: ftrack-connect wipes/overwrites process env vars (including
FTRACK_WORKDIR) when launching Maya, so we keep this in QSettings
instead. Maya-only — Houdini and other DCCs continue to use FTRACK_WORKDIR.
"""

from __future__ import annotations

from typing import Optional


_QSETTINGS_ORG = "mroya"
_QSETTINGS_APP = "ftrack_inout"
_KEY = "MAYA_WORKDIR"


def _qsettings():
    """Return a QSettings instance, or None if Qt is unavailable."""
    try:
        from PySide6 import QtCore  # type: ignore
        return QtCore.QSettings(_QSETTINGS_ORG, _QSETTINGS_APP)
    except Exception:
        pass
    try:
        from PySide2 import QtCore  # type: ignore
        return QtCore.QSettings(_QSETTINGS_ORG, _QSETTINGS_APP)
    except Exception:
        return None


def get_maya_workdir() -> Optional[str]:
    """Return the persisted Maya working directory, or None if not set."""
    s = _qsettings()
    if s is None:
        return None
    val = s.value(_KEY)
    return str(val) if val else None


def set_maya_workdir(path: Optional[str]) -> bool:
    """Persist the Maya working directory. Pass None or "" to clear.

    Returns True if persisted successfully, False if Qt is unavailable.
    """
    s = _qsettings()
    if s is None:
        return False
    if path:
        s.setValue(_KEY, str(path))
    else:
        s.remove(_KEY)
    s.sync()
    return True
