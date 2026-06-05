import time
from typing import Callable, Dict, Optional

import roles
from cachetools import TTLCache
from models import Group, User


class SessionManager:
    """Owns conversation session lifecycle for private and group chats."""

    def __init__(self, bot_qq: int, is_super_user: Callable[[int], bool], memory=None, window_size: int = 30, session_store=None):
        self.bot_qq = bot_qq
        self.is_super_user = is_super_user
        self.private_sessions: Dict[int, User] = {}
        self.group_sessions: Dict[int, Group] = TTLCache(maxsize=1024, ttl=43200)
        self.memory = memory
        self.window_size = window_size
        self.session_store = session_store

    def get_private_session(self, user_id: int) -> User:
        user_id = int(user_id)
        if user_id not in self.private_sessions:
            is_super = self.is_super_user(user_id)
            save_cb = self.session_store.make_save_callback("user", user_id) if self.session_store else None

            # Restore saved short-term memory if available
            saved = self.session_store.load("user", user_id) if self.session_store else []
            system_msg = {
                "role": "system",
                "content": self._default_private_role(user_id),
                "timestamp": int(time.time() * 1000),
            }

            if saved and saved[0]["role"] == "system":
                # Replace old system prompt with fresh one, keep the rest
                chat_history = [system_msg] + saved[1:]
            else:
                chat_history = [system_msg] + saved

            user = User(user_id, is_super, self.bot_qq, memory=self.memory, window_size=self.window_size, save_callback=save_cb)
            user.chat_history = chat_history
            self.private_sessions[user_id] = user
        return self.private_sessions[user_id]

    def get_group_session(self, group_id: int) -> Group:
        group_id = int(group_id)
        if group_id not in self.group_sessions:
            save_cb = self.session_store.make_save_callback("group", group_id) if self.session_store else None

            saved = self.session_store.load("group", group_id) if self.session_store else []
            group = Group(group_id, self.bot_qq, memory=self.memory, window_size=self.window_size, save_callback=save_cb)
            group.chat_history = saved
            self.group_sessions[group_id] = group
        return self.group_sessions[group_id]

    def reset_private_session(self, user_id: int) -> bool:
        user_id = int(user_id)
        session = self.private_sessions.get(user_id)
        if session is None:
            return False

        session.chat_history = [{
            "role": "system",
            "content": self._default_private_role(user_id),
        }]
        # Also wipe persisted session
        if self.session_store:
            self.session_store.delete("user", user_id)
        return True

    def reset_group_session(self, group_id: int) -> bool:
        group_id = int(group_id)
        session = self.get_group_session(group_id)
        session.chat_history = []
        if self.session_store:
            self.session_store.delete("group", group_id)
        return True

    def _default_private_role(self, user_id: int) -> str:
        if self.is_super_user(user_id):
            return roles.get_Murasame_goshujin_role(user_id, self.bot_qq)
        return roles.get_Murasame_customs_role(user_id, self.bot_qq)
