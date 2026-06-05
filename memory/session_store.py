"""Persist short-term chat_history to disk so sessions survive restarts.

Each session is saved as a JSON file under the store directory.
Auto-save is triggered by add_message; load happens on session creation.
"""
import json
import os
import threading
from typing import Optional


class SessionStore:
    def __init__(self, store_dir: str = "./memory_db/sessions"):
        self._dir = store_dir
        self._lock = threading.Lock()
        os.makedirs(self._dir, exist_ok=True)

    def _path(self, prefix: str, target_id: int) -> str:
        return os.path.join(self._dir, f"{prefix}_{target_id}.json")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def save(self, prefix: str, target_id: int, chat_history: list) -> None:
        """Persist chat_history to disk (thread-safe)."""
        with self._lock:
            try:
                tmp = self._path(prefix, target_id) + ".tmp"
                with open(tmp, "w", encoding="utf-8") as fh:
                    json.dump(chat_history, fh, ensure_ascii=False, indent=2)
                os.replace(tmp, self._path(prefix, target_id))
            except OSError as exc:
                print(f"[Session] Failed to save {prefix}_{target_id}: {exc}")

    def load(self, prefix: str, target_id: int) -> list:
        """Load saved chat_history, or empty list if not found."""
        try:
            with open(self._path(prefix, target_id), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return []

    def delete(self, prefix: str, target_id: int) -> bool:
        """Delete a persisted session. Returns True if it existed."""
        path = self._path(prefix, target_id)
        try:
            os.remove(path)
            return True
        except FileNotFoundError:
            return False

    def make_save_callback(self, prefix: str, target_id: int):
        """Return a zero-arg callable that saves the current chat_history.

        Used as a lightweight hook: the session object passes its chat_history
        to this callback on every add_message.
        """
        def cb(chat_history: list):
            self.save(prefix, target_id, chat_history)
        return cb
