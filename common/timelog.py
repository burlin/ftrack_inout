"""Automatic time logging on publish.

Records publish timestamps to a daily log file and creates ftrack Timelog
entities on the tasks being published to.

The first publish of the day counts from DEFAULT_DAY_START (10:00 AM).
Each subsequent publish counts from the previous one.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Default day-start time (hours, minutes). Change this or make user-configurable later.
DEFAULT_DAY_START = (10, 0)

# Directory for daily log files
TIMELOG_DIR = Path("D:/mroya/temp/timelogs")


def _today_log_path() -> Path:
    """Return path like D:/mroya/temp/timelogs/2026-02-19.json."""
    return TIMELOG_DIR / f"{datetime.now():%Y-%m-%d}.json"


def _read_log(path: Path) -> list[str]:
    """Read list of ISO timestamps from today's log file."""
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("publishes", [])
    except Exception:
        logger.warning("Could not read timelog file: %s", path, exc_info=True)
        return []


def _write_log(path: Path, publishes: list[str]) -> None:
    """Write timestamps to log file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"publishes": publishes}, indent=2),
        encoding="utf-8",
    )


def format_duration(seconds: float) -> str:
    """Format seconds into a human-readable string like '1h 14m'."""
    total = max(int(seconds), 0)
    h, remainder = divmod(total, 3600)
    m, s = divmod(remainder, 60)
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m"
    return f"{s}s"


def parse_duration(text: str) -> float | None:
    """Parse a human-readable duration string into seconds.

    Accepted formats:
        "1h 30m", "1h30m", "2h", "45m", "90" (treated as minutes),
        "1:30" (h:mm).

    Returns:
        Total seconds, or None if parsing failed.
    """
    import re

    text = text.strip().lower()
    if not text:
        return None

    # Try "H:MM" format
    match = re.match(r'^(\d+):(\d{1,2})$', text)
    if match:
        h, m = int(match.group(1)), int(match.group(2))
        return float(h * 3600 + m * 60)

    # Try "XhYm" / "Xh Ym" / "Xh" / "Ym" combinations
    hours = 0
    minutes = 0
    found = False

    h_match = re.search(r'(\d+)\s*h', text)
    if h_match:
        hours = int(h_match.group(1))
        found = True

    m_match = re.search(r'(\d+)\s*m', text)
    if m_match:
        minutes = int(m_match.group(1))
        found = True

    if found:
        return float(hours * 3600 + minutes * 60)

    # Plain number — treat as minutes
    try:
        return float(int(text) * 60)
    except ValueError:
        return None


def record_publish(task_count: int = 1) -> tuple[float, str]:
    """Record a publish event and return time information.

    Reads today's log file to find the last publish time (or uses
    DEFAULT_DAY_START if this is the first publish of the day), calculates
    the elapsed time, and appends the current timestamp to the log.

    Args:
        task_count: Number of tasks in this publish batch.
            Time is split equally among them.

    Returns:
        (seconds_per_task, formatted_total) tuple.
        ``seconds_per_task`` is the portion each task gets.
        ``formatted_total`` is the total elapsed time before splitting.
    """
    now = datetime.now()
    log_path = _today_log_path()
    publishes = _read_log(log_path)

    if publishes:
        last = datetime.fromisoformat(publishes[-1])
    else:
        # First publish of the day — count from day start
        last = now.replace(
            hour=DEFAULT_DAY_START[0],
            minute=DEFAULT_DAY_START[1],
            second=0,
            microsecond=0,
        )

    delta = max((now - last).total_seconds(), 0)
    per_task = delta / max(task_count, 1)

    # Append current timestamp
    publishes.append(now.isoformat())
    try:
        _write_log(log_path, publishes)
    except Exception:
        logger.warning("Could not write timelog file: %s", log_path, exc_info=True)

    return per_task, format_duration(delta)


def create_ftrack_timelog(
    session,
    task_id: str,
    seconds: float,
    comment: str = "",
) -> bool:
    """Create a Timelog entity on the given ftrack task.

    Args:
        session: An ``ftrack_api.Session`` instance.
        task_id: The ftrack Task ID to log time against.
        seconds: Duration in seconds.
        comment: Optional description for the timelog entry.

    Returns:
        True if the timelog was created successfully, False otherwise.
    """
    if session is None or not task_id or seconds <= 0:
        return False

    try:
        user = session.query(
            'User where username is "{}"'.format(session.api_user)
        ).first()
        if not user:
            logger.error("Could not find ftrack user: %s", session.api_user)
            return False

        session.create("Timelog", {
            "user_id": user["id"],
            "context_id": task_id,
            "duration": int(seconds),
            "start": datetime.now(),
            "name": comment or "Auto-logged on publish",
        })
        session.commit()
        logger.info(
            "Timelog created: %ds on task %s", int(seconds), task_id
        )
        return True
    except Exception as exc:
        logger.error("Failed to create timelog: %s", exc)
        return False
