"""Ban-list manager backed by a single JSON file.

Banned users are ignored by the bot entirely — their messages are not
processed and they receive no reply in either group or private chat.
"""
import json
import os
import threading
import time
from typing import Any, Optional


class BanManager:
    def __init__(self, file_path: str = "./memory_db/bans.json"):
        self._path = file_path
        self._lock = threading.Lock()
        self._bans: dict[str, dict[str, Any]] = {}
        self._load()

    # ------------------------------------------------------------------
    # API
    # ------------------------------------------------------------------

    def is_banned(self, user_id: int) -> bool:
        with self._lock:
            return str(user_id) in self._bans

    def get(self, user_id: int) -> Optional[dict[str, Any]]:
        with self._lock:
            return self._bans.get(str(user_id))

    def ban(self, user_id: int, reason: str = "", banned_by: str = "") -> dict[str, Any]:
        with self._lock:
            uid = str(user_id)
            entry = {
                "reason": reason,
                "banned_at": int(time.time() * 1000),
                "banned_by": str(banned_by),
            }
            self._bans[uid] = entry
            self._save()
            return dict(entry)

    def unban(self, user_id: int) -> bool:
        with self._lock:
            uid = str(user_id)
            if uid not in self._bans:
                return False
            del self._bans[uid]
            self._save()
            return True

    def list_all(self) -> list[dict[str, Any]]:
        with self._lock:
            result = []
            for uid, entry in self._bans.items():
                item = dict(entry)
                item["user_id"] = uid
                result.append(item)
            result.sort(key=lambda x: x.get("banned_at", 0), reverse=True)
            return result

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load(self):
        if not os.path.exists(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                self._bans = raw
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[Ban] Failed to load bans: {exc}")
            self._bans = {}

    def _save(self):
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        tmp = self._path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._bans, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
        except OSError as exc:
            print(f"[Ban] Failed to save bans: {exc}")
