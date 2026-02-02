"""
Unreal Engine 5-specific helpers for ftrack_inout.browser.

Empty adapter stub: if needed, wrappers over unreal Python API can be added here
without changing main browser code.
"""

from __future__ import annotations

try:  # pragma: no cover - depends on DCC environment
    import unreal  # type: ignore
    UE_AVAILABLE: bool = True
except Exception:
    unreal = None  # type: ignore
    UE_AVAILABLE = False

__all__ = ["unreal", "UE_AVAILABLE"]


