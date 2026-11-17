"""Remember which finished videos were posted, to keep a steady posting pace.

Shopee only unlocks product tagging on videos after an account posts regularly
(about 5 videos in 30 days), so the WebUI shows how many videos went out in the
last 30 days. The log is a small JSON file in the storage folder.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time

from loguru import logger

from app.utils import utils

LOG_FILENAME = "posting_log.json"
TARGET_POSTS = 5
WINDOW_DAYS = 30
_MAX_ENTRIES = 1000
_lock = threading.RLock()


def _log_path() -> str:
    return os.path.join(utils.storage_dir("", create=True), LOG_FILENAME)


def _load() -> dict[str, dict]:
    try:
        with open(_log_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning(f"posting log unreadable, starting a new one: {exc}")
        return {}
    if not isinstance(data, dict):
        return {}
    return {
        str(task_id): entry
        for task_id, entry in data.items()
        if isinstance(entry, dict) and isinstance(entry.get("posted_at"), (int, float))
    }


def _save(entries: dict[str, dict]) -> None:
    if len(entries) > _MAX_ENTRIES:
        newest = sorted(entries.items(), key=lambda kv: kv[1]["posted_at"])[-_MAX_ENTRIES:]
        entries = dict(newest)
    path = _log_path()
    descriptor, temp_path = tempfile.mkstemp(
        prefix=".posting-log-", suffix=".json", dir=os.path.dirname(path)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, path)
    except Exception:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise


def is_posted(task_id: str) -> bool:
    with _lock:
        return task_id in _load()


def set_posted(task_id: str, subject: str = "", posted: bool = True, now: float | None = None) -> None:
    with _lock:
        entries = _load()
        if posted:
            entries[task_id] = {
                "subject": str(subject or "")[:200],
                "posted_at": float(now if now is not None else time.time()),
            }
        else:
            entries.pop(task_id, None)
        _save(entries)


def recent_posts(now: float | None = None, days: int = WINDOW_DAYS) -> list[dict]:
    """Posts in the last ``days`` days, newest first."""
    now = float(now if now is not None else time.time())
    cutoff = now - days * 86400
    with _lock:
        entries = _load()
    recent = [
        {"task_id": task_id, **entry}
        for task_id, entry in entries.items()
        if entry["posted_at"] >= cutoff
    ]
    return sorted(recent, key=lambda entry: entry["posted_at"], reverse=True)


def pace(now: float | None = None) -> dict:
    """How far the account is from the posting target in the 30-day window."""
    now = float(now if now is not None else time.time())
    posts = recent_posts(now)
    count = len(posts)
    remaining = max(0, TARGET_POSTS - count)
    # The window is rolling: the oldest post in it drops out first.
    drops_at = None
    if posts and count <= TARGET_POSTS:
        drops_at = posts[-1]["posted_at"] + WINDOW_DAYS * 86400
    return {
        "count": count,
        "target": TARGET_POSTS,
        "remaining": remaining,
        "posts": posts,
        "oldest_drops_at": drops_at,
        "days_since_last": (now - posts[0]["posted_at"]) / 86400 if posts else None,
    }
