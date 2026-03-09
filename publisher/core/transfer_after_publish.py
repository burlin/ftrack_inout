"""
Transfer job primitive: create one transfer Job and publish mroya.transfer.request.

Caller is responsible for: which components, from/to locations, filtering.
"""

from __future__ import annotations

import json
import logging
import re
import socket
from typing import Any, List, Optional

_log = logging.getLogger(__name__)

# Excluded from "target location" dropdown (system locations)
_LOCATION_EXCLUDE_NAMES = frozenset({
    "ftrack.origin", "ftrack.connect", "ftrack.server",
    "ftrack.unmanaged", "ftrack.review",
})


def _location_type(loc: Any) -> str:
    """Return 's3', 'disk', or 'unknown' from location accessor."""
    try:
        acc = getattr(loc, "accessor", None)
        if not acc:
            return "unknown"
        mod = type(acc).__module__.lower()
        name = type(acc).__name__.lower()
        if "s3" in mod or "s3" in name:
            return "s3"
        if "disk" in mod or "disk" in name:
            return "disk"
    except Exception:
        pass
    return "unknown"


def get_locations_with_accessor(session) -> List[dict]:
    """
    Return list of locations that have an accessor (real storage), for dropdowns.

    Usable from standalone publisher, Houdini, Maya: pass current ftrack session.

    Returns:
        List of dicts: [{"id": "...", "name": "...", "label": "...", "location_type": "s3"|"disk"|"unknown"}, ...]
        Sorted by label/name; excluded system locations (ftrack.origin, etc.).
    """
    out: List[dict] = []
    try:
        locations = session.query("Location").all()
        for loc in locations:
            if not getattr(loc, "accessor", None):
                continue
            name = (loc.get("name") or "").strip()
            if name in _LOCATION_EXCLUDE_NAMES:
                continue
            loc_id = loc.get("id")
            if not loc_id:
                continue
            out.append({
                "id": loc_id,
                "name": name,
                "label": (loc.get("label") or name or "").strip(),
                "location_type": _location_type(loc),
            })
        out.sort(key=lambda x: (x.get("label") or x.get("name") or "").lower())
    except Exception as e:
        _log.warning("get_locations_with_accessor: %s", e)
    return out

# UUID: 32 hex chars (no dashes) or 36 with dashes (8-4-4-4-12)
_UUID_RE = re.compile(r"^[0-9a-f]{32}$", re.I)
_UUID_DASHED_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _normalize_location_id(s: str) -> Optional[str]:
    """Return 32-char hex id for session.get('Location', id), or None if not a valid uuid."""
    if not s or not s.strip():
        return None
    s = s.strip()
    # Already 32 hex (no dashes)
    if _UUID_RE.match(s):
        return s
    # Dashed form: remove dashes to get 32 hex
    if _UUID_DASHED_RE.match(s):
        return s.replace("-", "")
    # Truncated dashed (e.g. 6c73a09a-0931-450a-b824-260c9f79): try without dashes if 32 chars
    no_dash = s.replace("-", "")
    if len(no_dash) == 32 and _UUID_RE.match(no_dash):
        return no_dash
    return None


def get_component_location_id(session, component_id: str) -> Optional[str]:
    """Get location_id where the component currently is (first ComponentLocation)."""
    try:
        cl = session.query(
            f'ComponentLocation where component_id is "{component_id}"'
        ).first()
        if cl:
            return cl.get("location_id")
    except Exception as e:
        _log.debug("get_component_location_id %s: %s", component_id[:16], e)
    return None


def resolve_location_id(session, name_or_id: str) -> Optional[str]:
    """Resolve location by name or by id. Returns location_id or None."""
    if not name_or_id or not name_or_id.strip():
        return None
    s = name_or_id.strip()
    try:
        # ftrack_api session.get often expects id with dashes (as returned by API)
        if _UUID_DASHED_RE.match(s):
            loc = session.get("Location", s)
            return loc["id"] if loc else None
        normalized_id = _normalize_location_id(s)
        if normalized_id:
            loc = session.get("Location", normalized_id)
            return loc["id"] if loc else None
        loc = session.query(f'Location where name is "{s}"').first()
        return loc["id"] if loc else None
    except Exception as e:
        _log.debug("resolve_location_id %r: %s", s[:32], e)
    return None


def _get_user_id(session) -> Optional[str]:
    try:
        user = session.query(
            f'User where username is "{session.api_user}"'
        ).first()
        return user["id"] if user else None
    except Exception as e:
        _log.debug("get_user_id: %s", e)
    return None


def create_transfer_job(
    session,
    component_id: str,
    from_location_id: str,
    to_location_id: str,
    *,
    user_id: Optional[str] = None,
    component_label: str = "",
    to_location_name: Optional[str] = None,
) -> Optional[str]:
    """
    Create one transfer Job and publish mroya.transfer.request.

    Returns job_id on success, None on failure.
    """
    if from_location_id == to_location_id:
        _log.debug("create_transfer_job: from == to, skip")
        return None

    uid = user_id or _get_user_id(session)
    if not uid:
        _log.warning("create_transfer_job: no user_id")
        return None

    try:
        comp = session.get("Component", component_id)
        label = component_label or comp.get("name", "component") or "component"
    except Exception:
        label = component_label or "component"

    payload_meta = {
        "tag": "mroya_transfer",
        "description": (
            f"Transfer: {label} to {to_location_name or to_location_id[:8]} "
            "(from Publisher)"
        ),
        "component_label": label,
        "from_location_id": from_location_id,
        "to_location_id": to_location_id,
        "to_location_name": to_location_name or "",
    }

    try:
        job = session.create(
            "Job",
            {
                "user_id": uid,
                "status": "running",
                "data": json.dumps(payload_meta),
            },
        )
        session.commit()
        job_id = job["id"]
    except Exception as e:
        _log.warning("create_transfer_job: Job create failed: %s", e)
        return None

    try:
        from ftrack_api.event.base import Event
        try:
            session.event_hub.connect()
        except Exception:
            pass
        payload = {
            "job_id": job_id,
            "user_id": uid,
            "from_location_id": from_location_id,
            "to_location_id": to_location_id,
            "selection": [{"entityType": "Component", "entityId": component_id}],
            "ignore_component_not_in_location": False,
            "ignore_location_errors": False,
        }
        hostname = socket.gethostname().lower()
        event = Event(
            topic="mroya.transfer.request",
            data=payload,
            source={"hostname": hostname, "user": {"username": session.api_user}},
        )
        session.event_hub.publish(event, on_error="ignore")
        _log.info("create_transfer_job: job %s for component %s", job_id[:8], component_id[:8])
        return job_id
    except Exception as e:
        _log.warning("create_transfer_job: event publish failed: %s", e)
        return job_id  # Job was created, return it anyway
