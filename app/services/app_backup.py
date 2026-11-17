"""One-file backup of the seller's own data (no API keys).

The zip holds the posting log, schedule, winning hooks and the WebUI choices
saved in config.toml's [ui] section. Videos are large and stay in the task
folders. API keys have their own backup in Settings and are never put in
this file.
"""

from __future__ import annotations

import io
import json
import os
import time
import zipfile

from app.config import config
from app.services import posting_log
from app.utils import utils

BACKUP_VERSION = 1
_DATA_FILES = (
    posting_log.LOG_FILENAME,
    posting_log.PLAN_FILENAME,
    posting_log.WINNING_HOOKS_FILENAME,
)
_MAX_BACKUP_BYTES = 5 * 1024 * 1024
# UI keys that can hold secrets must never be exported.
_SECRET_HINTS = ("key", "token", "secret", "password", "cookie")


class BackupError(ValueError):
    """The backup cannot be restored; the message is user-facing."""


def _ui_settings() -> dict:
    return {
        key: value
        for key, value in dict(config.ui).items()
        if not any(hint in str(key).lower() for hint in _SECRET_HINTS)
        and isinstance(value, (str, int, float, bool))
    }


def build_backup() -> bytes:
    storage = utils.storage_dir("", create=True)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "manifest.json",
            json.dumps({"app": "MoneyPrinterTurbo", "version": BACKUP_VERSION,
                        "created_at": time.time()}, indent=2),
        )
        archive.writestr("ui_settings.json", json.dumps(_ui_settings(), ensure_ascii=False, indent=2))
        for name in _DATA_FILES:
            path = os.path.join(storage, name)
            if os.path.isfile(path):
                archive.write(path, f"data/{name}")
    return buffer.getvalue()


def restore_backup(data: bytes) -> dict:
    """Restore the data files; return their count and the UI settings to apply."""
    if len(data) > _MAX_BACKUP_BYTES:
        raise BackupError("File sao lưu quá lớn.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise BackupError("File sao lưu bị lỗi hoặc không phải .zip.") from exc
    with archive:
        names = set(archive.namelist())
        if "manifest.json" not in names:
            raise BackupError("Đây không phải file sao lưu của app.")
        try:
            manifest = json.loads(archive.read("manifest.json"))
        except ValueError as exc:
            raise BackupError("File sao lưu bị lỗi.") from exc
        if manifest.get("app") != "MoneyPrinterTurbo":
            raise BackupError("Đây không phải file sao lưu của app.")
        storage = utils.storage_dir("", create=True)
        restored_files = 0
        for name in _DATA_FILES:
            member = f"data/{name}"
            if member not in names or archive.getinfo(member).file_size > _MAX_BACKUP_BYTES:
                continue
            content = archive.read(member)
            try:
                json.loads(content)
            except ValueError:
                continue
            target = os.path.join(storage, name)
            temp = target + ".restore"
            with open(temp, "wb") as f:
                f.write(content)
            os.replace(temp, target)
            restored_files += 1
        settings = {}
        if "ui_settings.json" in names:
            try:
                settings = json.loads(archive.read("ui_settings.json"))
            except ValueError:
                settings = {}
    safe_settings = {}
    if isinstance(settings, dict):
        safe_settings = {
            key: value
            for key, value in settings.items()
            if not any(hint in str(key).lower() for hint in _SECRET_HINTS)
            and isinstance(value, (str, int, float, bool))
        }
    # The caller applies the settings through the WebUI's config writer.
    return {"files": restored_files, "settings": safe_settings}
