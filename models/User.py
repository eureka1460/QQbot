import time
import roles
from api import *


class User:
    _TRIM_SLACK_MIN = 4
    _TRIM_SLACK_MAX = 20

    def __init__(self, user_id, is_super_user, bot_qq, memory=None, window_size=30, save_callback=None):
        self.user_id = user_id
        self.is_super_user = is_super_user
        self.bot_qq = bot_qq
        self.memory = memory
        self._window_size = window_size
        self._save_callback = save_callback
        self.chat_history = [
            {
                "role": "system",
                "content": roles.get_Murasame_goshujin_role(user_id, bot_qq) if is_super_user else roles.get_Murasame_customs_role(user_id, bot_qq),
                "timestamp": int(time.time() * 1000),
            }
        ]

    def get_user_id(self):
        return self.user_id

    def get_is_super_user(self):
        return self.is_super_user

    def get_chat_history(self):
        return self.chat_history

    def add_message(self, role, content, user_id=None, trim=True):
        self.chat_history.append({
            "role": role,
            "content": content,
            "timestamp": int(time.time() * 1000),
        })
        if trim:
            self._trim_chat_history()

        if self._save_callback:
            self._save_callback(self.chat_history)

    async def handle_message(self, message_content, system_role, user_id=None, store_user=True, dynamic_context=""):
        print(f"[Debug] User.handle_message called with system_role length: {len(system_role)}")
        print(f"[Debug] System role preview: {system_role[:200]}...")

        if self.memory and store_user:
            self.memory.store(self.user_id, self.user_id, message_content, "user", prefix="user")

        # Build dynamic context: time/mood + long-term memory
        dynamic_with_memory = dynamic_context
        if self.memory:
            relevant = self.memory.search(self.user_id, message_content, prefix="user")
            if relevant:
                dynamic_with_memory += (
                    "\n\n[来自长期记忆的相关历史对话，供参考]\n"
                    + relevant
                    + "\n[历史记忆结束]"
                )

        # Build messages: [static system] [cached history] [current input] [runtime context]
        tmp_chat_history = [{"role": "system", "content": system_role}]
        for msg in self.chat_history:
            if msg["role"] != "system":
                tmp_chat_history.append(msg)
        tmp_chat_history.append({"role": "user", "content": message_content})
        runtime_message = self._runtime_context_message(dynamic_with_memory)
        if runtime_message:
            tmp_chat_history.append(runtime_message)

        clean_history = [{"role": m["role"], "content": m["content"]} for m in tmp_chat_history]
        gpt_response = await call_llm_api(clean_history)

        self.add_message("user", message_content, self.user_id, trim=False)
        if self.memory:
            self.memory.store(self.user_id, None, gpt_response, "assistant", prefix="user")
        self.add_message("assistant", gpt_response)

        return gpt_response

    def _trim_chat_history(self) -> None:
        max_len = self._window_size + 1
        if len(self.chat_history) <= max_len + self._trim_slack():
            return

        system_msg = self.chat_history[0] if self.chat_history and self.chat_history[0]["role"] == "system" else None
        non_system = [msg for msg in self.chat_history if msg["role"] != "system"]
        self.chat_history = non_system[-self._window_size:]
        if system_msg:
            self.chat_history.insert(0, system_msg)

    def _trim_slack(self) -> int:
        return max(self._TRIM_SLACK_MIN, min(self._TRIM_SLACK_MAX, self._window_size // 5))

    @staticmethod
    def _runtime_context_message(runtime_context: str):
        runtime_context = (runtime_context or "").strip()
        if not runtime_context:
            return None
        return {"role": "system", "content": "[本轮运行时上下文]\n" + runtime_context + "\n[运行时上下文结束]"}
