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


def set_posted(
    task_id: str,
    subject: str = "",
    posted: bool = True,
    now: float | None = None,
    hook: str = "",
    sub_id: str = "",
) -> None:
    with _lock:
        entries = _load()
        if posted:
            entries[task_id] = {
                "subject": str(subject or "")[:200],
                "posted_at": float(now if now is not None else time.time()),
                "hook": str(hook or "")[:800],
                "sub_id": str(sub_id or "").strip()[:50],
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


WINNING_HOOKS_FILENAME = "winning_hooks.json"


def _winning_path() -> str:
    return os.path.join(utils.storage_dir("", create=True), WINNING_HOOKS_FILENAME)


def match_winning_hooks(sub_id_rows: list[dict]) -> list[dict]:
    """Join a commission report's Sub_ID rows with the hooks of posted videos.

    Returns hooks that earned commission, best first, and remembers them in
    ``winning_hooks.json`` so step 1 can offer them again.
    """
    earnings = {
        str(row.get("sub_id") or "").strip().lower(): row
        for row in sub_id_rows
        if str(row.get("sub_id") or "").strip()
    }
    with _lock:
        entries = _load()
        found: dict[str, dict] = {}
        for entry in entries.values():
            sub_id = str(entry.get("sub_id") or "").strip()
            hook = " ".join(str(entry.get("hook") or "").split())
            row = earnings.get(sub_id.lower())
            if not sub_id or not hook or not row or row.get("commission", 0) <= 0:
                continue
            current = found.setdefault(
                hook, {"hook": hook, "commission": 0, "orders": 0, "sub_ids": []}
            )
            current["commission"] += row.get("commission", 0)
            current["orders"] += row.get("orders", 0)
            current["sub_ids"].append(sub_id)
        winners = sorted(found.values(), key=lambda w: (-w["commission"], -w["orders"]))
        if winners:
            merged = {w["hook"]: w for w in load_winning_hooks()}
            merged.update({w["hook"]: w for w in winners})
            ranked = sorted(merged.values(), key=lambda w: (-w["commission"], -w["orders"]))[:50]
            path = _winning_path()
            descriptor, temp_path = tempfile.mkstemp(
                prefix=".winning-hooks-", suffix=".json", dir=os.path.dirname(path)
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as f:
                json.dump(ranked, f, ensure_ascii=False, indent=2)
            os.replace(temp_path, path)
    return winners


def load_winning_hooks() -> list[dict]:
    try:
        with open(_winning_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    return [row for row in data if isinstance(row, dict) and row.get("hook")] if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# Posting schedule: which unposted video goes out on which day.

PLAN_FILENAME = "posting_plan.json"


def _plan_path() -> str:
    return os.path.join(utils.storage_dir("", create=True), PLAN_FILENAME)


def load_plan() -> dict[str, str]:
    """task_id -> "YYYY-MM-DD"."""
    try:
        with open(_plan_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str) and len(v) == 10}


def _save_plan(plan: dict[str, str]) -> None:
    path = _plan_path()
    descriptor, temp_path = tempfile.mkstemp(prefix=".posting-plan-", suffix=".json", dir=os.path.dirname(path))
    with os.fdopen(descriptor, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def set_plan_date(task_id: str, day: str | None) -> None:
    with _lock:
        plan = load_plan()
        if day:
            plan[task_id] = day
        else:
            plan.pop(task_id, None)
        _save_plan(plan)


def auto_plan(task_ids: list[str], today: str, per_day: int = 1) -> dict[str, str]:
    """Give every unplanned video the next free day, ``per_day`` videos a day.

    Days before ``today`` that were planned but not posted move to the free
    days as well, so nothing silently stays overdue.
    """
    from datetime import date, timedelta

    start = date.fromisoformat(today)
    with _lock:
        plan = load_plan()
        posted = _load()
        wanted = [task_id for task_id in task_ids if task_id not in posted]
        keep = {
            task_id: day for task_id, day in plan.items()
            if task_id in wanted and day >= today
        }
        used: dict[str, int] = {}
        for day in keep.values():
            used[day] = used.get(day, 0) + 1
        cursor = start
        for task_id in wanted:
            if task_id in keep:
                continue
            while used.get(cursor.isoformat(), 0) >= max(1, per_day):
                cursor += timedelta(days=1)
            keep[task_id] = cursor.isoformat()
            used[cursor.isoformat()] = used.get(cursor.isoformat(), 0) + 1
        # Posted videos leave the schedule; other plans stay as they were.
        merged = {k: v for k, v in plan.items() if k not in posted and k not in wanted}
        merged.update(keep)
        _save_plan(merged)
        return keep


# Hours when Vietnamese shoppers scroll the most (lunch break and evening).
BEST_POSTING_WINDOWS = ((11, 13), (19, 22))


def posting_window_status(hour: int) -> str:
    """"now" inside a good window, "soon" within the hour before one, else ""."""
    for start, end in BEST_POSTING_WINDOWS:
        if start <= hour < end:
            return "now"
        if hour == start - 1:
            return "soon"
    return ""
