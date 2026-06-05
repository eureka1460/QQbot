"""Per-user profile storage backed by a single JSON file.

Each profile is keyed by user_id (string) and holds arbitrary fields.
A reserved "updated_at" timestamp tracks last modification.

Non-super-user writes go into a *pending* queue.  Super users can then
approve or reject individual submissions.

Intended for small-to-medium scale (hundreds of users); reads and writes
are synchronous — fine for a single-threaded async bot.
"""
import json
import os
import threading
import time
from typing import Any, Optional

PROFILE_FIELDS = ["name", "nickname", "hobbies", "appearance", "extra"]


class ProfileManager:
    def __init__(self, file_path: str = "./memory_db/profiles.json"):
        self._path = file_path
        self._pending_path = file_path.replace(".json", "_pending.json")
        self._lock = threading.Lock()
        self._profiles: dict[str, dict[str, Any]] = {}
        self._pending: dict[str, dict[str, Any]] = {}
        self._load()

    # ------------------------------------------------------------------
    # Public CRUD
    # ------------------------------------------------------------------

    def get(self, user_id: int) -> Optional[dict[str, Any]]:
        with self._lock:
            return self._profiles.get(str(user_id))

    def set(self, user_id: int, field: str, value: str) -> dict[str, Any]:
        """Direct write — caller must have already checked permissions."""
        with self._lock:
            uid = str(user_id)
            profile = self._profiles.setdefault(uid, {})
            profile[field] = value
            profile["updated_at"] = int(time.time() * 1000)
            self._save()
            return dict(profile)

    def delete(self, user_id: int) -> bool:
        with self._lock:
            uid = str(user_id)
            if uid not in self._profiles:
                return False
            del self._profiles[uid]
            self._save()
            return True

    # ------------------------------------------------------------------
    # Pending submissions (for non-super users)
    # ------------------------------------------------------------------

    def submit(self, user_id: int, updates: dict[str, str]) -> dict[str, Any]:
        """Queue a profile update for super-user approval.

        *updates* is a dict of field→value.  A special key ``_delete``
        (value ``"1"``) signals a deletion request.
        """
        with self._lock:
            uid = str(user_id)
            entry = self._pending.setdefault(uid, {})
            for k, v in updates.items():
                entry[k] = v
            entry["submitted_at"] = int(time.time() * 1000)
            entry["submitted_by"] = uid
            self._save_pending()
            return dict(entry)

    def list_pending(self) -> list[dict[str, Any]]:
        """Return all pending submissions as a list of flat dicts."""
        with self._lock:
            result = []
            for uid, entry in self._pending.items():
                item = dict(entry)
                item["user_id"] = uid
                result.append(item)
            result.sort(key=lambda x: x.get("submitted_at", 0))
            return result

    def approve(self, user_id: int) -> Optional[dict[str, Any]]:
        """Apply pending changes for *user_id* to the real profile.

        Returns the updated profile dict, or None if nothing was pending.
        """
        with self._lock:
            uid = str(user_id)
            pending = self._pending.pop(uid, None)
            if pending is None:
                return None

            if pending.pop("_delete", None) == "1":
                self._profiles.pop(uid, None)
                self._save()
                self._save_pending()
                return {}

            profile = self._profiles.setdefault(uid, {})
            for field in PROFILE_FIELDS:
                if field in pending:
                    profile[field] = pending[field]
            profile["updated_at"] = int(time.time() * 1000)
            self._save()
            self._save_pending()
            return dict(profile)

    def reject(self, user_id: int) -> bool:
        """Discard pending changes for *user_id*."""
        with self._lock:
            uid = str(user_id)
            if uid not in self._pending:
                return False
            del self._pending[uid]
            self._save_pending()
            return True

    # ------------------------------------------------------------------
    # Prompt helper
    # ------------------------------------------------------------------

    def to_prompt(self, user_id: int) -> str:
        profile = self.get(user_id)
        if not profile:
            return ""

        parts = []
        for field in PROFILE_FIELDS:
            val = profile.get(field)
            if val:
                label = _FIELD_LABELS.get(field, field)
                parts.append(f"{label}: {val}")

        if not parts:
            return ""

        return "[用户档案] " + " / ".join(parts)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load(self):
        self._profiles = self._load_json(self._path)
        self._pending = self._load_json(self._pending_path)

    @staticmethod
    def _load_json(path: str) -> dict:
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            return raw if isinstance(raw, dict) else {}
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[Profile] Failed to load {path}: {exc}")
            return {}

    def _save(self):
        self._write_json(self._path, self._profiles)

    def _save_pending(self):
        self._write_json(self._pending_path, self._pending)

    def _write_json(self, path: str, data: dict):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except OSError as exc:
            print(f"[Profile] Failed to save {path}: {exc}")


_FIELD_LABELS = {
    "name": "姓名",
    "nickname": "绰号",
    "hobbies": "爱好",
    "appearance": "外貌",
    "extra": "备注",
}
